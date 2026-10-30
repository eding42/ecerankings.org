#!/usr/bin/env python3
"""Promote a verified local candidate and store changed raw files through Git LFS.

Does not stage Git changes, commit, push, or deploy. Writes the release manifest
last, so the site packager rejects an interrupted or mixed publication.
"""
import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
INPUTS = {
    'registry': 'data/areas.json',
    'affiliation_map': 'data/affiliation-map.csv',
    'institution_aliases': 'data/institution-aliases.csv',
    'excluded_works': 'data/excluded-works.csv',
    'institution_metadata_overrides': 'data/institution-metadata-overrides.json',
    'institution_metadata_snapshot': 'data/institutions.json',
    'institution_metadata_refresh': 'data/refresh/institution-records-2026-10-28.json',
}


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def check_inputs(manifest):
    for name, expected in manifest['input_hashes'].items():
        if name not in INPUTS or digest(ROOT / INPUTS[name]) != expected:
            raise ValueError(f'Curated input changed since build: {name}')
    for name, expected in manifest.get('code_hashes', {}).items():
        source = (ROOT / name).resolve()
        if not source.is_relative_to(ROOT) or digest(source) != expected:
            raise ValueError(f'Build code changed since build: {name}')


def validate_candidate(cache, release):
    manifest = json.loads((release / 'manifest.json').read_text())
    if manifest.get('validation', {}).get('status') != 'passed':
        raise ValueError('A passing candidate release is required')
    check_inputs(manifest)
    for relative, evidence in manifest['artifacts'].items():
        source = (release / relative).resolve()
        if not source.is_relative_to(release) or digest(source) != evidence['sha256']:
            raise ValueError(f'Candidate artifact differs: {relative}')
    inventory = {(r['venue'], str(r['year'])): r for r in manifest['refresh']['files']}
    files = {(p.parts[-3], p.parts[-2]): p for p in cache.glob('*/*/works.jsonl')}
    if not inventory or set(files) != set(inventory):
        raise ValueError('Candidate cache differs from the complete release inventory')
    for key, path in files.items():
        if digest(path) != inventory[key]['sha256']:
            raise ValueError(f'Candidate cache changed: {key}')
    return manifest, files


def atomic_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.release-tmp')
    shutil.copyfile(source, temporary)
    temporary.replace(destination)


def export_lfs(source, destination, expected):
    size = source.stat().st_size
    pointer = (f'version https://git-lfs.github.com/spec/v1\noid sha256:{expected}\nsize {size}\n'.encode()
               if size else b'')
    if destination.exists() and destination.read_bytes() == pointer:
        # Keep the normal working tree usable by the data pipeline. Git LFS
        # stores pointers in Git; source files on disk remain materialized.
        atomic_copy(source, destination)
        return False
    with source.open('rb') as handle:
        result = subprocess.run(['git-lfs', 'clean', str(destination.relative_to(ROOT))],
                                stdin=handle, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=ROOT, check=True)
    if result.stdout != pointer:
        raise ValueError(f'LFS clean result differs from candidate: {destination}')
    atomic_copy(source, destination)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', required=True, type=pathlib.Path)
    parser.add_argument('--release', required=True, type=pathlib.Path)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    cache, release = args.cache_dir.resolve(), args.release.resolve()
    public = (ROOT / 'site/data').resolve()
    if release == public or public in release.parents:
        parser.error('Use the separate candidate release, outside site/data')
    try:
        manifest, files = validate_candidate(cache, release)
        if args.check_only:
            print(f'Candidate verified: {len(files)} cache files; no files promoted')
            return
        if not shutil.which('git-lfs'):
            raise ValueError('Install Git LFS before promoting raw cache data')
        required = subprocess.run(['git', 'config', '--get', 'filter.lfs.required'],
                                  cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        if required != 'true':
            raise ValueError('Git LFS must be configured as a required Git filter before promotion')
        inventory = {(r['venue'], str(r['year'])): r for r in manifest['refresh']['files']}
        changed = 0
        for index, ((venue, year), source) in enumerate(sorted(files.items()), 1):
            row = inventory[(venue, year)]
            changed += export_lfs(source, ROOT / 'cache' / venue / year / 'works.jsonl', row['sha256'])
            if index % 100 == 0:
                print(f'Cache files verified: {index}; changed pointers: {changed}', flush=True)
        for relative, evidence in manifest['artifacts'].items():
            source, destination = release / relative, public / relative
            if relative == 'author-info.csv':
                export_lfs(source, destination, evidence['sha256'])
            else:
                atomic_copy(source, destination)
        check_inputs(manifest)
        atomic_copy(release / 'manifest.json', public / 'manifest.json')
        print(f'Promoted {len(files)} materialized cache files ({changed} changed LFS objects) and validated public data; no commit or deployment')
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(2, f'Promotion refused: {error}\n')


if __name__ == '__main__':
    main()
