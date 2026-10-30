"""Deterministic venue scheduling, content-addressed shards, and provenance.

Workers own their accumulators. Only the parent reduces them, in venue order.
An edition edit invalidates its whole venue, preserving cross-year deduplication.
"""
import concurrent.futures
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time

SCHEMA_VERSION = 2
TABLE_FILES = ('inst-area-year.csv', 'inst-venue-year.csv', 'author-info.csv')
ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = ('pipeline/aggregate.py', 'pipeline/aggregation_runtime.py', 'pipeline/workkey.py',
                'data/areas.json', 'data/affiliation-map.csv', 'data/institution-aliases.csv',
                'data/excluded-works.csv')
_state = threading.local()


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def digest_files(paths, workers=None):
    paths = list(paths)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers or available_cpus(), 32)) as pool:
        return dict(zip(paths, pool.map(digest, paths)))


def available_cpus():
    counter = getattr(os, 'process_cpu_count', os.cpu_count)
    return max(1, counter() or 1)


def gil_disabled():
    return hasattr(sys, '_is_gil_enabled') and not sys._is_gil_enabled()


def select_executor(executor):
    if executor == 'auto':
        return 'threads' if gil_disabled() else 'processes'
    if executor == 'threads' and not gil_disabled():
        raise ValueError('Thread aggregation requires a free-threaded interpreter with the GIL disabled')
    return executor


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _initialize(v2a, year, affiliation_map, excluded, aliases, cache_dir, venue_exclusions):
    from aggregate import process_venues
    _state.kernel = process_venues
    _state.arguments = (v2a, year, affiliation_map, excluded, aliases, cache_dir, venue_exclusions)


def _encode(result):
    area, venue, author, inst_names, author_names, metrics, nested = result
    return [ [[*key, val['pub_count'], val['adjusted_count']] for key, val in area.items()],
             [[*key, val['pub_count'], val['adjusted_count']] for key, val in venue.items()],
             [[*key, val] for key, val in author.items()],
             inst_names, list(author_names.items()), metrics, nested ]


def _decode(payload):
    if not isinstance(payload, list) or len(payload) != 7:
        raise ValueError('Invalid aggregation shard')
    tables = []
    for rows, width, with_count in zip(payload[:3], (3, 4, 4), (True, True, False)):
        if not isinstance(rows, list):
            raise ValueError('Invalid shard table')
        table = {}
        for row in rows:
            if len(row) != width + (2 if with_count else 1):
                raise ValueError('Invalid shard row width')
            key = tuple(row[:width])
            year_index = 3 if width == 4 and with_count else 2
            if type(key[year_index]) is not int or any(
                    not isinstance(v, str) and not (not with_count and i == 0 and v is None)
                    for i, v in enumerate(key) if i != year_index):
                raise ValueError('Invalid shard identity')
            value = row[-1]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or key in table:
                raise ValueError('Invalid or duplicate shard credit')
            if with_count:
                count = row[-2]
                if type(count) is not int or count < 1 or value > count + 1e-8:
                    raise ValueError('Invalid shard paper count')
                table[key] = {'pub_count': count, 'adjusted_count': value}
            else:
                table[key] = value
        tables.append(table)
    if not isinstance(payload[3], dict) or not isinstance(payload[4], list):
        raise ValueError('Invalid shard names')
    author_names = {}
    for key, value in payload[4]:
        if (key is not None and not isinstance(key, str)) or key in author_names:
            raise ValueError('Invalid or duplicate shard author')
        author_names[key] = value
    for names in (payload[3], author_names):
        if any(v is not None and not isinstance(v, str) for v in names.values()):
            raise ValueError('Invalid shard names')
    if len(payload[5]) != 7 or any(type(v) is not int or v < 0 for v in payload[5]):
        raise ValueError('Invalid shard metrics')
    if not isinstance(payload[6], dict):
        raise ValueError('Invalid shard lineage')
    nested = {}
    for iid, value in payload[6].items():
        if (not isinstance(value, list) or len(value) != 2 or not isinstance(value[0], str)
                or not isinstance(value[1], list) or any(not isinstance(v, str) for v in value[1])):
            raise ValueError('Invalid shard lineage record')
        nested[iid] = (value[0], value[1])
    if (any(key[0] not in payload[3] for table in tables[:2] for key in table)
            or any(key[0] not in author_names or key[3] not in payload[3] for key in tables[2])):
        raise ValueError('Incomplete shard names')
    return (*tables, payload[3], author_names, tuple(payload[5]), nested)


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.aggregation-', delete=False) as handle:
            temporary = Path(handle.name)
            # dumps uses the C encoder; dump's streaming iterator spends much
            # more CPU walking millions of small aggregate rows in Python.
            handle.write(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
            handle.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _process(task):
    venue, fingerprint, sources, destination, persistent = task
    path = Path(destination)
    if persistent:
        try:
            return True, _read(task)
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            pass
    result = _state.kernel([venue], *_state.arguments, prepared=True)
    if any(digest(source) != expected for source, expected in sources):
        raise ValueError(f'Source changed during aggregation: {venue}')
    if persistent:
        _atomic_json(path, {'schema_version': SCHEMA_VERSION, 'fingerprint': fingerprint,
                            'result': _encode(result)})
        _atomic_json(path.with_suffix('.meta'), {'schema_version': SCHEMA_VERSION,
                                               'fingerprint': fingerprint, 'sha256': digest(path)})
    return False, result


def _read(task):
    path = Path(task[3])
    # Hash the bytes actually decoded, including when another build replaces a shard.
    raw = path.read_bytes()
    metadata = json.loads(path.with_suffix('.meta').read_text())
    if (metadata['schema_version'] != SCHEMA_VERSION or metadata['fingerprint'] != task[1]
            or metadata['sha256'] != hashlib.sha256(raw).hexdigest()):
        raise ValueError('Aggregation shard hash mismatch')
    payload = json.loads(raw)
    if payload['schema_version'] != SCHEMA_VERSION or payload['fingerprint'] != task[1]:
        raise ValueError('Aggregation shard dependency mismatch')
    return _decode(payload['result'])


def restore_tables(cache, fingerprint, output):
    """Restore a complete export only after checking its exact dependency key."""
    source = Path(cache) / 'tables' / fingerprint
    try:
        metadata = json.loads((source / 'complete.json').read_text())
        if not isinstance(metadata, dict):
            return None
        record_digest = metadata.pop('record_sha256')
        if (metadata['schema_version'] != SCHEMA_VERSION or metadata['fingerprint'] != fingerprint
                or set(metadata['files']) != set(TABLE_FILES) or _fingerprint(metadata) != record_digest):
            return None
        for name in TABLE_FILES:
            if digest(source / name) != metadata['files'][name]:
                return None
        Path(output).mkdir(parents=True, exist_ok=True)
        for name in TABLE_FILES:
            _atomic_copy(source / name, Path(output) / name)
            if digest(Path(output) / name) != metadata['files'][name]:
                raise ValueError('Cached export changed while copying')
        return metadata['metrics']
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _atomic_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.aggregation-', delete=False) as handle:
            temporary = Path(handle.name)
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def store_tables(cache, fingerprint, output, metrics):
    destination = Path(cache) / 'tables' / fingerprint
    # Publish the completion record last. Readers either verify a complete
    # generation or compute again; cached exports never bypass release validation.
    for name in TABLE_FILES:
        _atomic_copy(Path(output) / name, destination / name)
    metadata = {
        'schema_version': SCHEMA_VERSION, 'fingerprint': fingerprint,
        'files': {name: digest(destination / name) for name in TABLE_FILES}, 'metrics': metrics}
    metadata['record_sha256'] = _fingerprint(metadata)
    _atomic_json(destination / 'complete.json', metadata)


def aggregate_venues(venues, v2a, year, affiliation_map, excluded, aliases, cache_dir,
                     venue_exclusions, *, workers=None, executor='auto', sequential=False,
                     aggregation_cache_dir=None, report=None, output=None):
    """Yield one verified venue result at a time, in canonical reduction order."""
    start = time.perf_counter()
    report = report if report is not None else {}
    if workers is not None and workers < 1:
        raise ValueError('--workers must be positive')
    backend = 'sequential' if sequential else select_executor(executor)
    venues = sorted(set(venues))
    unknown = [v for v in venues if v not in v2a]
    for venue in unknown:
        print(f'  [{venue}] not in data/areas.json, skipping.', file=sys.stderr)
    venues = [v for v in venues if v in v2a]
    n_workers = 1 if sequential else min(workers or available_cpus(), max(1, len(venues)))
    cache_dir = Path(cache_dir)
    sources = {v: sorted(p for p in (cache_dir / v).glob('*/works.jsonl')
                         if p.parent.name.isdigit() and (year is None or int(p.parent.name) == year))
               for v in venues}
    for venue in venues:
        if not sources[venue]:
            print(f'  [{venue}] no cached years match, skipping.', file=sys.stderr)
    venues = [v for v in venues if sources[v]]
    sources = {v: sources[v] for v in venues}
    hashes = digest_files([p for paths in sources.values() for p in paths], n_workers)
    dependencies = digest_files([ROOT / p for p in DEPENDENCIES], n_workers)
    config = _fingerprint({'schema_version': SCHEMA_VERSION,
                           'dependencies': {str(p.relative_to(ROOT)): h for p, h in dependencies.items()},
                           'runtime': sys.version, 'year': year, 'v2a': v2a,
                           'affiliation_map': affiliation_map, 'aliases': aliases,
                           'excluded': sorted(excluded),
                           'venue_exclusions': {v: sorted(keys) for v, keys in venue_exclusions.items()}})
    report.update(executor=backend, workers=n_workers, cache_hits=0, cache_misses=0, venues=[],
                  runtime={'version': sys.version, 'gil_disabled': gil_disabled()})
    arguments = (v2a, year, affiliation_map, excluded, aliases, str(cache_dir), venue_exclusions)
    _initialize(*arguments)
    with tempfile.TemporaryDirectory(prefix='ecerankings-aggregation-') as temporary:
        destination = Path(aggregation_cache_dir) if aggregation_cache_dir else Path(temporary)
        tasks = []
        for venue in venues:
            fingerprint = _fingerprint([config, venue, [(str(p.relative_to(cache_dir)), hashes[p])
                                                        for p in sources[venue]]])
            tasks.append((venue, fingerprint, [(str(p), hashes[p]) for p in sources[venue]],
                          str(destination / (fingerprint + '.json')), bool(aggregation_cache_dir)))
        report['fingerprint'] = _fingerprint([SCHEMA_VERSION, [task[1] for task in tasks], config])
        report['table_cache_hit'] = False
        cached_metrics = (restore_tables(destination, report['fingerprint'], output)
                          if aggregation_cache_dir and output is not None else None)
        if cached_metrics is not None:
            report.update(table_cache_hit=True, cache_hits=len(tasks), metrics=cached_metrics)
            report['venues'] = [{'venue': task[0], 'fingerprint': task[1], 'cache_hit': True} for task in tasks]
        pool = None
        futures = {}
        try:
            if cached_metrics is None and not sequential and tasks:
                if backend == 'threads':
                    pool = concurrent.futures.ThreadPoolExecutor(max_workers=n_workers,
                                initializer=_initialize, initargs=arguments)
                else:
                    pool = concurrent.futures.ProcessPoolExecutor(max_workers=n_workers,
                                mp_context=multiprocessing.get_context('spawn'),
                                initializer=_initialize, initargs=arguments)
                # Submission order improves utilization; reduction order never changes.
                for task in sorted(tasks, key=lambda t: -sum(Path(p).stat().st_size for p, _ in t[2])):
                    futures[task[0]] = pool.submit(_process, task)
            for task in ([] if cached_metrics is not None else tasks):
                if pool:
                    future = futures.pop(task[0])
                    hit, result = future.result()
                    del future
                else:
                    hit, result = _process(task)
                report['cache_hits' if hit else 'cache_misses'] += 1
                report['venues'].append({'venue': task[0], 'fingerprint': task[1], 'cache_hit': hit})
                yield result
                del result
        finally:
            if pool:
                pool.shutdown(wait=True, cancel_futures=True)
        current = {v: sorted(p for p in (cache_dir / v).glob('*/works.jsonl')
                            if p.parent.name.isdigit() and (year is None or int(p.parent.name) == year))
                   for v in venues}
        if sources != current or digest_files(hashes, n_workers) != hashes:
            raise ValueError('Source inventory changed during aggregation')
        if digest_files(dependencies, n_workers) != dependencies:
            raise ValueError('Aggregation code or curated inputs changed during aggregation')
    if backend == 'threads' and not gil_disabled():
        raise ValueError('The GIL was enabled during threaded aggregation')
    report['aggregation_seconds'] = time.perf_counter() - start
