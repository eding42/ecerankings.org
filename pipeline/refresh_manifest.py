#!/usr/bin/env python3
"""Write the refresh manifest consumed by build_release.py.

The release builder refuses to aggregate unless every cache file it reads is
declared in advance with a SHA-256. This script produces that declaration from
the current cache tree, so a manual refresh can use the same validated release
path as an automated one.

Usage:
    python3 pipeline/refresh_manifest.py --cache-dir cache --out .tmp/refresh.json
"""
import argparse
import hashlib
import json
import pathlib

LFS_POINTER = b'version https://git-lfs.github.com/spec/v1'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir', type=pathlib.Path, default=pathlib.Path('cache'),
                        help='Cache tree containing <venue>/<year>/works.jsonl (default: cache)')
    parser.add_argument('--out', type=pathlib.Path, required=True,
                        help='Manifest path, usually .tmp/refresh.json')
    args = parser.parse_args()

    cache = args.cache_dir.resolve()
    if not cache.is_dir():
        parser.error(f'Cache directory not found: {cache}')

    files = []
    for path in sorted(cache.glob('*/*/works.jsonl')):
        with path.open('rb') as handle:
            head = handle.read(len(LFS_POINTER))
        if head == LFS_POINTER:
            parser.error(
                f'LFS pointer, not materialized data: {path}\n'
                'Run: git lfs pull --include="cache/**"'
            )
        files.append({
            'venue': path.parts[-3],
            'year': path.parts[-2],
            'bytes': path.stat().st_size,
            'sha256': digest(path),
        })

    if not files:
        parser.error(f'No cache/*/*/works.jsonl files found under {cache}')

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({'files': files}, indent=2) + '\n')
    print(f'Wrote {len(files)} cache entries to {args.out}')


if __name__ == '__main__':
    main()
