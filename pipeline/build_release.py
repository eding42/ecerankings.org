#!/usr/bin/env python3
"""Build and validate a full candidate release in a separate output directory.

This command never promotes its outputs into site/data or deploys them.
"""
import argparse
import collections
import csv
import datetime
import hashlib
import json
import math
import pathlib
import subprocess
import sys

from aggregation_runtime import digest_files, select_executor

ROOT = pathlib.Path(__file__).resolve().parents[1]
CODE_FILES = ['pipeline/aggregate.py', 'pipeline/aggregation_runtime.py', 'pipeline/workkey.py',
              'pipeline/split.py', 'pipeline/build_release.py', 'pipeline/verify.py',
              'pipeline/promote_release.py']


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def read_csv(path):
    with path.open(newline='') as handle:
        yield from csv.DictReader(handle)


def validate(output, registry):
    """Return measured artifact facts, raising on structural inconsistencies."""
    areas = registry['areas']
    institutions = json.loads((output / 'institutions.json').read_text())
    expected = {}
    expected_rows = {}
    totals = collections.Counter()
    years = set()
    unique = set()
    for row in read_csv(output / 'inst-area-year.csv'):
        key = (row['institution_id'], row['area'], int(row['year']))
        score, count = float(row['adjusted_count']), int(row['pub_count'])
        if key in unique or key[1] not in areas or key[0] not in institutions:
            raise ValueError(f'Duplicate or invalid aggregate key: {key}')
        if not math.isfinite(score) or score < 0 or score > count + 1e-5 or count < 1:
            raise ValueError(f'Invalid credit at {key}: {score}, {count}')
        unique.add(key)
        expected[key] = score
        expected_rows[key] = {'i': row['institution_id'], 'n': row['institution_name'],
                              'y': int(row['year']), 'p': count, 'a': score}
        totals[key[1]] += score
        years.add(key[2])
    venue_sums = collections.Counter()
    venue_rows = collections.Counter()
    venue_expected = collections.defaultdict(dict)
    known_venues = {v['key']: area for area, a in areas.items() for v in a['venues']}
    for row in read_csv(output / 'inst-venue-year.csv'):
        if known_venues.get(row['venue']) != row['area']:
            raise ValueError(f'Invalid venue ownership: {row["venue"]}')
        key = (row['institution_id'], row['area'], int(row['year']))
        score, count = float(row['adjusted_count']), int(row['pub_count'])
        identity = (key[0], key[2])
        table = venue_expected[(key[1], row['venue'])]
        if (identity in table or key[0] not in institutions or not math.isfinite(score)
                or score < 0 or count < 1 or score > count + 1e-5):
            raise ValueError(f'Duplicate or invalid venue aggregate: {key}, {row["venue"]}')
        table[identity] = {'i': key[0], 'n': row['institution_name'], 'y': key[2], 'p': count, 'a': score}
        venue_sums[key] += score
        venue_rows[row['venue']] += 1
    if set(expected) != set(venue_sums):
        raise ValueError('Area and venue tables have different institution/area/year keys')
    for key, score in expected.items():
        if abs(score - venue_sums[key]) > 1e-4:
            raise ValueError(f'Area and venue credit do not reconcile: {key}')
    missing_default_venues = [venue for venue, area in known_venues.items()
                              if areas[area].get('default_on') and not venue_rows[venue]]
    if missing_default_venues:
        raise ValueError('Default-on venues with no credit: ' + ', '.join(missing_default_venues))
    for (area, venue), expected_venue in venue_expected.items():
        records = json.loads((output / area / f'{venue}.json').read_text())
        seen = set()
        for row in records:
            key = (row['i'], row['y'])
            if key in seen or row != expected_venue.get(key):
                raise ValueError(f'Venue JSON differs from CSV: {venue}, {key}')
            seen.add(key)
        if seen != expected_venue.keys():
            raise ValueError(f'Venue JSON is incomplete: {venue}')
    for area in areas:
        records = json.loads((output / f'{area}.json').read_text())
        seen = set()
        for row in records:
            key = (row['i'], area, row['y'])
            if key in seen or key not in expected or row != expected_rows[key]:
                raise ValueError(f'Area JSON differs from CSV: {key}')
            seen.add(key)
        if seen != {key for key in expected if key[1] == area}:
            raise ValueError(f'Area JSON is incomplete: {area}')
        if areas[area].get('default_on') and not records:
            raise ValueError(f'Default-on area has no credited institutions: {area}')
    author_sums = collections.Counter()
    author_rows = collections.Counter()
    for row in read_csv(output / 'author-info.csv'):
        key = (row['institution_id'], row['area'], int(row['year']))
        value = float(row['adjusted_count'])
        if key not in expected or not math.isfinite(value) or value < 0:
            raise ValueError(f'Invalid author credit: {key}')
        author_sums[key] += value
        author_rows[key] += 1
    if set(author_sums) != set(expected):
        raise ValueError('Author and area tables have different keys')
    for key, score in expected.items():
        # Each CSV cell was independently rounded to five decimals.
        bound = .000005 * (author_rows[key] + 1) + 1e-8
        if abs(author_sums[key] - score) > bound:
            raise ValueError(f'Author and area credit do not reconcile: {key}')
    return {'status': 'passed', 'checks': [
                'unique aggregate keys', 'finite nonnegative credit bounded by paper count',
                'venue ownership', 'venue-to-area credit reconciliation',
                'area and venue JSON-to-CSV equality', 'complete institution metadata keys',
                'author-to-area credit reconciliation within declared rounding bound',
                'nonempty default-on areas'],
            'aggregate_rows': len(unique), 'institutions': len(institutions),
            'year_min': min(years), 'year_max': max(years),
            'adjusted_count_by_area': {a: round(totals[a], 5) for a in areas},
            'venues_without_credit': sorted(set(known_venues) - venue_rows.keys()),
            'institutions_without_country': sum(not v.get('country') for v in institutions.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', required=True, type=pathlib.Path)
    parser.add_argument('--out', required=True, type=pathlib.Path)
    parser.add_argument('--workers', type=int, default=None,
                        help='Aggregation workers (default: available CPU allocation)')
    parser.add_argument('--executor', choices=('auto', 'processes', 'threads'), default='auto')
    parser.add_argument('--sequential', action='store_true', help='Diagnostic single-worker execution')
    parser.add_argument('--aggregation-cache-dir', type=pathlib.Path,
                        default=ROOT / '.tmp/aggregation-cache')
    parser.add_argument('--no-aggregation-cache', action='store_true')
    parser.add_argument('--refresh-manifest', type=pathlib.Path,
                        required=True,
                        help='Evidence of accepted fresh and retained cache files')
    args = parser.parse_args()
    if args.workers is not None and args.workers < 1:
        parser.error('--workers must be positive')
    if not args.sequential:
        try:
            select_executor(args.executor)
        except ValueError as error:
            parser.error(str(error))
    output = args.out.resolve()
    public_data = (ROOT / 'site/data').resolve()
    if output == public_data or public_data in output.parents or output.exists():
        parser.error('Use a new candidate output directory, outside site/data')
    refresh = json.loads(args.refresh_manifest.read_text())
    inventory = {(row['venue'], str(row['year'])): row for row in refresh.get('files', [])}
    cache_files = {(path.parts[-3], path.parts[-2]): path
                   for path in args.cache_dir.glob('*/*/works.jsonl')}
    if not inventory or set(cache_files) != set(inventory):
        parser.error('Candidate cache must match the complete declared refresh inventory')
    source_hashes = digest_files(cache_files.values(), args.workers)
    for key, path in cache_files.items():
        if source_hashes[path] != inventory[key]['sha256']:
            parser.error(f'Candidate cache hash differs from inventory: {key}')
    initial_hashes = {path: digest(ROOT / path) for path in [
        'data/areas.json', 'data/affiliation-map.csv', 'data/institution-aliases.csv',
        'data/excluded-works.csv', 'data/institution-metadata-overrides.json',
        'data/institutions.json', 'data/refresh/institution-records-2026-10-28.json']
        if (ROOT / path).exists()}
    code_hashes = {path: digest(ROOT / path) for path in CODE_FILES}
    output.mkdir(parents=True)
    registry = json.loads((ROOT / 'data/areas.json').read_text())
    command = [sys.executable, str(ROOT / 'pipeline/aggregate.py'), '--all-cached',
               '--cache-dir', str(args.cache_dir.resolve()), '--out', str(output),
               '--executor', args.executor, '--aggregation-cache-dir', str(args.aggregation_cache_dir.resolve()),
               '--stats', str(output / 'aggregation-stats.log')]
    if args.workers is not None:
        command += ['--workers', str(args.workers)]
    if args.sequential:
        command.append('--sequential')
    if args.no_aggregation_cache:
        command.append('--no-aggregation-cache')
    with (output / 'aggregate.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    subprocess.run([sys.executable, str(ROOT / 'pipeline/split.py'),
                    '--area-input', str(output / 'inst-area-year.csv'),
                    '--venue-input', str(output / 'inst-venue-year.csv'),
                    '--areas', str(ROOT / 'data/areas.json'), '--out', str(output)],
                   cwd=ROOT, check=True)
    live_path = ROOT / 'data/refresh/institution-records-2026-10-28.json'
    live = json.loads(live_path.read_text())['by_id'] if live_path.exists() else {}
    snapshot = json.loads((ROOT / 'data/institutions.json').read_text())['by_id']
    override_path = ROOT / 'data/institution-metadata-overrides.json'
    overrides = json.loads(override_path.read_text()) if override_path.exists() else {}
    metadata = {}
    for row in read_csv(output / 'inst-area-year.csv'):
        iid = row['institution_id']
        canonical = 'https://openalex.org/' + iid.rstrip('/').split('/')[-1]
        source = live.get(canonical) or snapshot.get(canonical) or {}
        override = overrides.get(canonical, {})
        metadata[iid] = {'name': override.get('name') or source.get('display_name') or row['institution_name'],
                         'country': override.get('country') or source.get('country_code') or ''}
    (output / 'institutions.json').write_text(json.dumps(dict(sorted(metadata.items())),
                                                        ensure_ascii=False, separators=(',', ':')) + '\n')
    result = validate(output, registry)
    if any(digest(ROOT / path) != value for path, value in initial_hashes.items()):
        raise ValueError('Curated inputs changed during release build; rebuild from a stable input set')
    if any(digest(ROOT / path) != value for path, value in code_hashes.items()):
        raise ValueError('Build code changed during release build')
    final_cache = {(p.parts[-3], p.parts[-2]): p for p in args.cache_dir.glob('*/*/works.jsonl')}
    if final_cache != cache_files or digest_files(cache_files.values(), args.workers) != source_hashes:
        raise ValueError('Candidate cache changed during release build')
    public_inputs = {'registry': initial_hashes['data/areas.json'],
                     'affiliation_map': initial_hashes['data/affiliation-map.csv'],
                     'institution_aliases': initial_hashes['data/institution-aliases.csv'],
                     'excluded_works': initial_hashes['data/excluded-works.csv']}
    if override_path.exists():
        public_inputs['institution_metadata_overrides'] = initial_hashes['data/institution-metadata-overrides.json']
    public_inputs['institution_metadata_snapshot'] = initial_hashes['data/institutions.json']
    if live_path.exists():
        public_inputs['institution_metadata_refresh'] = initial_hashes['data/refresh/institution-records-2026-10-28.json']
    artifacts = {str(path.relative_to(output)): {'sha256': digest(path), 'bytes': path.stat().st_size}
                 for path in sorted(output.rglob('*')) if path.is_file() and path.suffix in ('.csv', '.json')}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    # LFS clean filters can require writes even for status. A read-only build
    # still has complete code/input hashes; conservatively mark status failures dirty.
    status = subprocess.run(['git', '--no-optional-locks', 'status', '--porcelain'], cwd=ROOT,
                            capture_output=True, text=True)
    dirty = status.returncode != 0 or bool(status.stdout.strip())
    manifest = {'schema_version': 1, 'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'source_revision': revision, 'source_tree_dirty': dirty,
                'source_tree_status': 'available' if status.returncode == 0 else 'unavailable; assumed dirty',
                'source_revision_meaning': 'Git baseline at build time; code_hashes identify the actual working-tree files, including uncommitted changes.',
                'code_hashes': code_hashes,
                'aggregation': json.loads((output / 'aggregation-stats.log').read_text()),
                'latest_complete_year': datetime.date.today().year - 1,
                'latest_complete_year_meaning': 'Last completed calendar year; publisher coverage may still be incomplete.',
                'methodology': 'Equal 1/N author credit, split between unique education institutions; geometric mean of 1+area counts minus 1.',
                'input_hashes': public_inputs, 'artifacts': artifacts, 'validation': result,
                'refresh': refresh,
                'coverage_note': 'Source indexing and affiliation coverage vary by venue and year. Carried-forward scopes were not refreshed in this build. Machine Learning remains off by default.'}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
