#!/usr/bin/env python3
"""Combine complete refresh outputs with retained baseline data, with an audit trail.

Creates a separate candidate cache; never modifies the baseline or live cache.
"""
import argparse
import collections
import difflib
import hashlib
import html
import json
import pathlib
import re
import shutil
import sys
import unicodedata

from workkey import record_key, norm_doi

ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(path):
    with path.open() as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            if line.startswith('version https://git-lfs.github.com/spec/v1'):
                raise ValueError(f'Unmaterialized LFS pointer: {path}')
            work = json.loads(line)
            if not isinstance(work, dict) or not isinstance(work.get('authorships'), list):
                raise ValueError(f'Invalid work at {path}:{number}')
            yield work


def richness(work):
    authors = work.get('authorships') or []
    return (sum(bool(a.get('institutions')) for a in authors), len(authors),
            sum(bool(a.get('raw_affiliations')) for a in authors), str(work.get('id') or ''))


def collection_evidence(provider, path, manifest):
    """Expose final collection gaps without mistaking repaired errors for gaps."""
    rows = manifest.get('results')
    if rows is None:
        rows = [dict(row, venue=venue, year=int(year))
                for venue, years in manifest.get('years', {}).items()
                for year, row in years.items()]
    by_scope = {(r['venue'], int(r['year'])): r for r in rows}
    for row in manifest.get('errors', []):
        key = (row['venue'], int(row['year']))
        if by_scope.get(key, {}).get('status') != 'complete':
            by_scope[key] = dict(row, status='blocked')
    for row in manifest.get('unresolved_scopes', []):
        key = (row['venue'], int(row['year']))
        if by_scope.get(key, {}).get('status') != 'complete':
            by_scope[key] = dict(row, status=row.get('status', 'blocked'))
    unresolved = [dict(provider=provider, venue=venue, year=year,
                       status=row.get('status', 'unknown'),
                       reason=row.get('error') or row.get('reason') or row.get('status', 'unknown'))
                  for (venue, year), row in sorted(by_scope.items())
                  if row.get('status') != 'complete']
    return {'manifest': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'status_counts': dict(collections.Counter(r.get('status', 'unknown')
                                                     for r in by_scope.values())),
            'unresolved_scopes': unresolved}


def name_tokens(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD', html.unescape(value or ''))
                    if not unicodedata.combining(c))
    return tuple(re.findall(r'[^\W\d_]+', value.casefold()))


def compatible_names(first, second):
    """Match full names and initials, without guessing surnames or transliteration."""
    if not first or not second:
        return False
    if first == second:
        return True
    if len(first) < 2 or len(second) < 2 or first[-1] != second[-1]:
        return False
    left, right = first[:-1], second[:-1]
    if ''.join(left) == ''.join(right):
        return True  # Hyphens and spaces can divide the same given name.
    for a, b in zip(left, right):
        if a != b and not (len(a) == 1 and b.startswith(a)) and not (len(b) == 1 and a.startswith(b)):
            return False
    return True  # An otherwise matching source may omit middle names.


def author_matches(before, after):
    """Return only independently unique author identities within this paper."""
    old_tokens = [name_tokens(a.get('author_name')) for a in before]
    new_tokens = [name_tokens(a.get('author_name')) for a in after]
    matches, used = {}, set()
    # Strong provider IDs and exact names precede abbreviated-name candidates.
    for keys in (
        lambda a, t: a.get('author_id') if re.fullmatch(r'https?://openalex\.org/A\d+', a.get('author_id') or '') else None,
        lambda a, t: t or None,
    ):
        old_index, new_index = collections.defaultdict(list), collections.defaultdict(list)
        for i, author in enumerate(before):
            if key := keys(author, old_tokens[i]):
                old_index[key].append(i)
        for i, author in enumerate(after):
            if key := keys(author, new_tokens[i]):
                new_index[key].append(i)
        for key, new_indices in new_index.items():
            old_indices = old_index.get(key, [])
            if len(new_indices) != 1 or len(old_indices) != 1:
                continue
            new, old = new_indices[0], old_indices[0]
            if new not in matches and old not in used:
                matches[new] = old
                used.add(old)
    families = collections.defaultdict(list)
    for i, tokens in enumerate(old_tokens):
        if tokens:
            families[tokens[-1]].append(i)
    candidates = {}
    inverse = collections.Counter()
    for i, tokens in enumerate(new_tokens):
        options = [j for j in families.get(tokens[-1], []) if compatible_names(old_tokens[j], tokens)] if tokens else []
        candidates[i] = options
        inverse.update(options)
    for new, options in candidates.items():
        if new not in matches and len(options) == 1 and inverse[options[0]] == 1 and options[0] not in used:
            matches[new] = options[0]
            used.add(options[0])
    return matches


def preserve_paper_evidence(fresh, baseline):
    """Carry paper-specific old assertions only when author identities align.

    Semantic Scholar author-profile affiliations cannot supply historical data.
    Fresh nonempty provider assertions take precedence; conflicting assertions
    are preserved in the immutable original input, not guessed into a merge.
    """
    if any(work.get('source') == 'semanticscholar' and work.get('backfilled_from') != 'openalex'
           for work in (fresh, baseline)):
        return fresh, 0
    if not norm_doi(fresh.get('doi')) or norm_doi(fresh.get('doi')) != norm_doi(baseline.get('doi')):
        return fresh, 0
    before, after = baseline.get('authorships') or [], fresh.get('authorships') or []
    has_prior_institutions = any(a.get('institutions') for a in before)
    has_prior_raw = any(a.get('raw_affiliations') for a in before)
    if not any(not a.get('raw_affiliations') and
               (has_prior_raw or (not a.get('institutions') and has_prior_institutions)) for a in after):
        return fresh, 0
    def title(work):
        text = html.unescape(re.sub(r'<[a-zA-Z/][^>]*>', '', work.get('title') or ''))
        text = unicodedata.normalize('NFKD', text).casefold()
        return ''.join(c for c in text if c.isalnum() and not unicodedata.combining(c))
    old_title, new_title = title(baseline), title(fresh)
    if not old_title or not new_title or (old_title != new_title and
            difflib.SequenceMatcher(None, old_title, new_title, autojunk=False).ratio() < .97):
        return fresh, 0
    matches = author_matches(before, after)
    result, retained = [], 0
    for index, new in enumerate(after):
        merged = dict(new)
        if index not in matches:
            result.append(merged)
            continue
        old = before[matches[index]]
        changed = False
        if not new.get('institutions') and new.get('raw_affiliations'):
            # Keep an explicit current provider affiliation ahead of a prior
            # structured assertion; resolution of conflicting claims is separate.
            result.append(merged)
            continue
        if not new.get('institutions') and old.get('institutions'):
            merged['institutions'] = old['institutions']
            changed = True
        if not new.get('raw_affiliations') and old.get('raw_affiliations'):
            merged['raw_affiliations'] = old['raw_affiliations']
            changed = True
        if changed:
            merged['retained_affiliation_assertion'] = {
                'source': 'previous paper-specific source observation',
                'identity': 'exact DOI, strongly matching title and unique author ID/full-name/initials match',
                'prior_author_name': old.get('author_name'),
                'prior_author_id': old.get('author_id'),
            }
            retained += 1
        result.append(merged)
    return dict(fresh, authorships=result), retained


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=pathlib.Path, required=True)
    parser.add_argument('--out', type=pathlib.Path, required=True)
    parser.add_argument('--report', type=pathlib.Path, required=True)
    parser.add_argument('--journal-cache', type=pathlib.Path, default=ROOT / '.tmp/refresh-2026-10-28/journals/cache')
    parser.add_argument('--journal-manifest', type=pathlib.Path, default=ROOT / 'data/refresh/journal-works-2026-10-28.json')
    parser.add_argument('--conference-cache', type=pathlib.Path, default=ROOT / '.tmp/refresh-2026-10-28/conferences/cache')
    parser.add_argument('--conference-manifest', type=pathlib.Path, default=ROOT / 'data/refresh/conference-works-2026-10-28.json')
    parser.add_argument('--ml-cache', type=pathlib.Path, default=ROOT / '.tmp/refresh-2026-10-28/ml/cache')
    parser.add_argument('--ml-manifest', type=pathlib.Path, default=ROOT / 'data/refresh/ml-works-2026-10-28.json')
    args = parser.parse_args()
    output, baseline = args.out.resolve(), args.baseline.resolve()
    if args.out.exists() or output == baseline or baseline in output.parents or output in baseline.parents:
        parser.error('Output must be a new directory separate from baseline')
    registry = json.loads((ROOT / 'data/areas.json').read_text())
    venues = {v['key']: v for a in registry['areas'].values() for v in a['venues']}
    fresh = {}
    operations = {}
    journal = json.loads(args.journal_manifest.read_text())
    for venue, years in journal.get('years', {}).items():
        for year, row in years.items():
            if row.get('status') == 'complete' and venues[venue]['kind'] == 'journal':
                fresh[(venue, year)] = (args.journal_cache / venue / year / 'works.jsonl', row['sha256'])
                operations[(venue, year)] = 'journal_source_query'
    conference = json.loads(args.conference_manifest.read_text())
    for row in conference.get('results', []):
        venue, year = row.get('venue'), str(row.get('year'))
        if row.get('status') == 'complete' and venues.get(venue, {}).get('kind') == 'conference':
            fresh[(venue, year)] = (args.conference_cache / venue / year / 'works.jsonl', row['checksum_sha256'])
            operations[(venue, year)] = 'conference_edition_query'
    baseline_files = {(p.parts[-3], p.parts[-2]): p for p in args.baseline.glob('*/*/works.jsonl')}
    if args.ml_manifest.exists():
        ml = json.loads(args.ml_manifest.read_text())
        ml_keys = {v['key'] for v in registry['areas']['ml']['venues']}
        for row in ml.get('results', []):
            venue, year = row.get('venue'), str(row.get('year'))
            if row.get('status') == 'complete' and venue in ml_keys:
                fresh[(venue, year)] = (args.ml_cache / venue / year / 'works.jsonl', row['sha256'])
                operations[(venue, year)] = 'cached_membership_doi_affiliation_recovery'
    collection = [collection_evidence('journals', args.journal_manifest, journal),
                  collection_evidence('conferences', args.conference_manifest, conference)]
    if args.ml_manifest.exists():
        collection.append(collection_evidence('ml', args.ml_manifest, ml))
    report = {'baseline_files': len(baseline_files), 'accepted_refreshed_files': len(fresh),
              'collection_results': collection,
              'unresolved_scopes': [row for result in collection for row in result['unresolved_scopes']],
              'files': [], 'quarantined_out_of_edition_records': 0,
              'quarantined_pre_inception_records': 0,
              'duplicate_records_removed': 0, 'author_profile_affiliations_withheld': 0,
              'retained_paper_specific_affiliation_assertions': 0,
              'crossref_journal_membership_records_retained': 0,
              'coverage_note': 'Completed source queries and checked enrichment of cached proceedings are combined with explicitly carried-forward files. Per-file operations distinguish membership queries from DOI affiliation recovery. API completeness is not publisher completeness.'}
    quarantine = args.report.with_suffix('.quarantine.jsonl')
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with quarantine.open('w') as rejected:
        for (venue, year), baseline_path in sorted({**baseline_files, **{k: v[0] for k, v in fresh.items()}}.items()):
            source, expected_hash = fresh.get((venue, year), (baseline_path, None))
            if expected_hash and hashlib.sha256(source.read_bytes()).hexdigest() != expected_hash:
                raise ValueError(f'Refresh evidence checksum mismatch for {venue}/{year}')
            old = list(read(baseline_files[(venue, year)])) if (venue, year) in fresh and (venue, year) in baseline_files else []
            old_by_doi = {norm_doi(w.get('doi')): w for w in old if norm_doi(w.get('doi'))}
            works = list(read(source))
            transformed = False
            membership_retained = 0
            # Crossref establishes journal membership for registry-declared
            # fallback years. A smaller native OpenAlex result is an enrichment
            # source, not evidence that the missing publisher DOIs vanished.
            entry = venues[venue].get('years', {}).get(year, {})
            if old and venues[venue]['kind'] == 'journal' and entry.get('source') == 'crossref':
                present = {norm_doi(w.get('doi')) for w in works if norm_doi(w.get('doi'))}
                retained = [w for w in old if norm_doi(w.get('doi')) not in present]
                works.extend(retained)
                transformed = bool(retained)
                membership_retained = len(retained)
                report['crossref_journal_membership_records_retained'] += len(retained)
            chosen = {}
            for work in works:
                if venue == 'iclr' and int(year) < 2013:
                    # The provider labels some preprints as earlier editions.
                    # First ICLR: the official 2013 call explicitly says "1st".
                    transformed = True
                    rejected.write(json.dumps({'reason': 'No ICLR edition existed before 2013; paper membership/year requires independent verification',
                                               'evidence': 'https://iclr.cc/archive/2013/call-for-papers.html',
                                               'venue': venue, 'bucket': year, 'work': work}, ensure_ascii=False) + '\n')
                    report['quarantined_pre_inception_records'] += 1
                    continue
                if venue == 'vlsi-tech' and year == '2021' and work.get('publication_year') != 2021:
                    transformed = True
                    rejected.write(json.dumps({'reason': 'Source spans other editions; not a 2021 work', 'venue': venue, 'bucket': year, 'work': work}, ensure_ascii=False) + '\n')
                    report['quarantined_out_of_edition_records'] += 1
                    continue
                if venue == 'dac' and year in ('2001', '2003') and work.get('publication_year') != int(year):
                    transformed = True
                    work['provider_publication_year'] = work['publication_year']
                    work['publication_year'] = int(year)
                    work['year_override_evidence'] = 'data/areas.json: DAC edition source and DOI-verified year correction'
                prior = old_by_doi.get(norm_doi(work.get('doi')))
                if prior:
                    previous = work
                    work, retained = preserve_paper_evidence(work, prior)
                    transformed = transformed or work != previous
                    report['retained_paper_specific_affiliation_assertions'] += retained
                if work.get('source') == 'semanticscholar' and not work.get('backfilled_from'):
                    for author in work.get('authorships') or []:
                        if author.get('raw_affiliations') and not author.get('institutions'):
                            transformed = True
                            author['profile_affiliations'] = author.pop('raw_affiliations')
                            author['raw_affiliations'] = []
                            author['affiliation_scope'] = 'author profile; unverified at publication'
                            report['author_profile_affiliations_withheld'] += 1
                identity = record_key(work, venue, year)
                if identity in chosen:
                    transformed = True
                    report['duplicate_records_removed'] += 1
                if identity not in chosen or richness(work) > richness(chosen[identity]):
                    chosen[identity] = work
            destination = args.out / venue / year / 'works.jsonl'
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            slots = covered = 0
            with destination.open('wb') as out:
                for key in chosen:
                    work = chosen[key]
                    data = (json.dumps(work, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
                    out.write(data)
                    digest.update(data)
                    for author in work.get('authorships') or []:
                        slots += 1
                        covered += bool(author.get('institutions') or author.get('raw_affiliations'))
            if not transformed:
                # Preserve exact provider bytes for unchanged observations;
                # normalization-only rewrites would waste large LFS objects.
                shutil.copyfile(source, destination)
                digest = hashlib.sha256(destination.read_bytes())
            report['files'].append({'venue': venue, 'year': int(year),
                                    'source_state': 'refreshed' if (venue, year) in fresh else 'carried_forward',
                                    'refresh_operation': operations.get((venue, year), 'retained_source_observation'),
                                    'prior_publisher_membership_records_retained': membership_retained,
                                    'works': len(chosen), 'sha256': digest.hexdigest(),
                                    'author_slots': slots, 'slots_with_affiliation_signal': covered})
    report['carried_forward_files'] = sum(r['source_state'] == 'carried_forward' for r in report['files'])
    report['total_works'] = sum(r['works'] for r in report['files'])
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    main()
