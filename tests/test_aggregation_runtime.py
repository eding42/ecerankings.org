import copy
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
import aggregate
import aggregation_runtime as runtime
import build_release
from compare_aggregates import compare_table


def paper(doi, name='University', author='Author', year=2025, kind='article'):
    return {'doi': doi, 'publication_year': year, 'type': kind,
            'authorships': [{'author_id': 'A1', 'author_name': author,
                            'institutions': [{'id': 'I1', 'display_name': name, 'type': 'education'}]}]}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / '.tmp'
        scratch.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.path = pathlib.Path(self.tmp.name)
        self.raw = self.path / 'raw'
        self.cache = self.path / 'aggregates'
        self.v2a = {'isscc': ('circuits', 'Circuits'), 'jssc': ('circuits', 'Circuits')}
        self.write('isscc', 2024, [paper('10.1/first', 'First', 'First author', 2024)])
        # The earlier edition owns this DOI, even though its publication year differs.
        self.write('isscc', 2025, [paper('10.1/first', 'Duplicate', 'Duplicate author'),
                                  paper('10.1/second', 'Second', 'Second author')])
        self.write('jssc', 2025, [paper('10.1/third', 'Last', 'Last author')])

    def write(self, venue, year, works):
        path = self.raw / venue / str(year) / 'works.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(w) + '\n' for w in works))
        return path

    def run_aggregation(self, **kwargs):
        report = {}
        result = aggregate.merge_results(runtime.aggregate_venues(
            ['jssc', 'isscc'], self.v2a, None, {}, set(), {}, str(self.raw), {},
            aggregation_cache_dir=self.cache, report=report, **kwargs))
        return result, report

    def test_parallel_preserves_sequential_names_counts_and_cross_year_deduplication(self):
        reference = aggregate.merge_results([aggregate.process_venues(
            ['isscc', 'jssc'], self.v2a, None, {}, cache_dir=str(self.raw))])
        sequential, _ = self.run_aggregation(sequential=True)
        parallel, report = self.run_aggregation(executor='processes', workers=2)
        self.assertEqual(reference, sequential)
        self.assertEqual(sequential, parallel)
        self.assertEqual(parallel[3]['https://openalex.org/I1'], 'Last')
        self.assertEqual(parallel[4]['A1'], 'Last author')
        self.assertEqual(report['cache_hits'], 2)

    def test_only_changed_venue_is_invalidated(self):
        self.run_aggregation(sequential=True)
        _, warm = self.run_aggregation(sequential=True)
        self.assertEqual((warm['cache_hits'], warm['cache_misses']), (2, 0))
        self.write('isscc', 2025, [paper('10.1/new')])
        _, changed = self.run_aggregation(sequential=True)
        self.assertEqual((changed['cache_hits'], changed['cache_misses']), (1, 1))
        (self.raw / 'isscc/2024/works.jsonl').unlink()
        _, deleted = self.run_aggregation(sequential=True)
        self.assertEqual((deleted['cache_hits'], deleted['cache_misses']), (1, 1))
        self.write('isscc', 2023, [paper('10.1/new', year=2023)])
        _, added = self.run_aggregation(sequential=True)
        self.assertEqual((added['cache_hits'], added['cache_misses']), (1, 1))

    def test_corrupt_and_structurally_invalid_shards_are_rebuilt(self):
        expected, first = self.run_aggregation(sequential=True)
        path = self.cache / (first['venues'][0]['fingerprint'] + '.json')
        path.write_text('corrupt')
        result, report = self.run_aggregation(sequential=True)
        self.assertEqual(result, expected)
        self.assertEqual(report['cache_misses'], 1)
        payload = json.loads(path.read_text())
        payload['result'][0][0][-1] = -1
        path.write_text(json.dumps(payload))
        metadata = json.loads(path.with_suffix('.meta').read_text())
        metadata['sha256'] = runtime.digest(path)
        path.with_suffix('.meta').write_text(json.dumps(metadata))
        result, report = self.run_aggregation(sequential=True)
        self.assertEqual(result, expected)
        self.assertEqual(report['cache_misses'], 1)

    def test_methodology_configuration_invalidates_all_shards(self):
        self.run_aggregation(sequential=True)
        self.v2a['isscc'] = ('different', 'Different')
        _, report = self.run_aggregation(sequential=True)
        self.assertEqual(report['cache_misses'], 2)

    def test_source_mutation_fails(self):
        kernel = aggregate.process_venues

        def mutate(*args, **kwargs):
            result = kernel(*args, **kwargs)
            self.write('isscc', 2024, [paper('10.1/changed')])
            return result

        with patch.object(aggregate, 'process_venues', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'Source changed during aggregation'):
                self.run_aggregation(sequential=True)

    def test_nonresearch_first_occurrence_still_owns_duplicate(self):
        self.write('isscc', 2024, [paper('10.1/first', kind='editorial')])
        result, _ = self.run_aggregation(sequential=True)
        self.assertNotIn(('https://openalex.org/I1', 'circuits', 2024), result[0])
        self.assertEqual(result[5], 2)  # second paper plus jssc, not the duplicate

    def test_missing_author_id_is_distinct_from_literal_null(self):
        missing, literal = paper('10.1/missing', author='Missing ID'), paper('10.1/literal', author='Literal ID')
        missing['authorships'][0]['author_id'] = None
        literal['authorships'][0]['author_id'] = 'null'
        self.write('jssc', 2025, [missing, literal])
        result, _ = self.run_aggregation(sequential=True)
        self.assertEqual(result[4][None], 'Missing ID')
        self.assertEqual(result[4]['null'], 'Literal ID')
        warm, _ = self.run_aggregation(sequential=True)
        self.assertEqual(result, warm)

    def test_worker_failure_leaves_no_completed_shard(self):
        self.write('isscc', 2024, [{'broken': True}])
        with self.assertRaises(KeyError):
            self.run_aggregation(sequential=True)
        self.assertFalse(list(self.cache.glob('*.meta')))

    def test_csv_bytes_are_identical_across_worker_counts_and_cache_hits(self):
        outputs = []
        for label, flags in [('sequential', ['--sequential']), ('one', ['--workers', '1']),
                              ('two', ['--workers', '2'])]:
            output = self.path / label
            command = [sys.executable, str(ROOT / 'pipeline/aggregate.py'), '--all-cached',
                       '--cache-dir', str(self.raw), '--out', str(output),
                       '--no-aggregation-cache', '--executor', 'processes', *flags]
            subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
            outputs.append({p.name: p.read_bytes() for p in output.glob('*.csv')})
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])

    def test_cached_export_corruption_is_detected(self):
        output = self.path / 'output'
        base = [sys.executable, str(ROOT / 'pipeline/aggregate.py'), '--all-cached',
                '--cache-dir', str(self.raw), '--out', str(output), '--sequential',
                '--aggregation-cache-dir', str(self.cache), '--stats', str(self.path / 'stats.json')]
        subprocess.run(base, capture_output=True, check=True, timeout=30)
        expected = {p.name: p.read_bytes() for p in output.glob('*.csv')}
        shard = next((self.cache / 'tables').glob('*/author-info.csv'))
        shard.write_text('corrupt')
        subprocess.run(base, capture_output=True, check=True, timeout=30)
        self.assertEqual(expected, {p.name: p.read_bytes() for p in output.glob('*.csv')})
        self.assertFalse(json.loads((self.path / 'stats.json').read_text())['table_cache_hit'])
        completion = next((self.cache / 'tables').glob('*/complete.json'))
        completion.write_text('null')
        subprocess.run(base, capture_output=True, check=True, timeout=30)
        self.assertEqual(expected, {p.name: p.read_bytes() for p in output.glob('*.csv')})
        self.assertFalse(json.loads((self.path / 'stats.json').read_text())['table_cache_hit'])

    @unittest.skipUnless(runtime.gil_disabled(), 'requires a free-threaded interpreter')
    def test_threads_match_sequential_without_cache(self):
        sequential, _ = self.run_aggregation(sequential=True)
        self.cache = self.path / 'fresh-thread-cache'
        threaded, report = self.run_aggregation(executor='threads', workers=2)
        self.assertEqual(sequential, threaded)
        self.assertEqual(report['cache_misses'], 2)

    def test_gil_enabled_threads_are_rejected(self):
        with patch.object(runtime, 'gil_disabled', return_value=False):
            with self.assertRaisesRegex(ValueError, 'GIL disabled'):
                runtime.select_executor('threads')
            self.assertEqual(runtime.select_executor('auto'), 'processes')
        with patch.object(runtime, 'gil_disabled', return_value=True):
            self.assertEqual(runtime.select_executor('auto'), 'threads')

    def test_prepared_affiliations_preserve_order_and_type_precedence(self):
        mapping = {'company': {'institution_id': 'I1', 'institution_type': 'company',
                               'institution_name': 'Company', 'status': 'manual'},
                   'education': {'institution_id': 'I1', 'institution_type': 'education',
                                 'institution_name': 'University', 'status': 'auto'},
                   'rejected': {'institution_id': 'I2', 'status': 'unresolved'}}
        before = copy.deepcopy(mapping)
        prepared = aggregate.prepare_affiliation_map(mapping)
        for raw in [['company', 'education'], ['education', 'company'], ['rejected']]:
            self.assertEqual(aggregate.resolve_raw_affiliations(raw, mapping),
                             aggregate.resolve_raw_affiliations(raw, prepared))
        self.assertEqual(mapping, before)

    def test_comparator_checks_names_and_counts_independently_of_tolerance(self):
        baseline = self.path / 'baseline.csv'
        candidate = self.path / 'candidate.csv'
        baseline.write_text('institution_id,area,year,institution_name,pub_count,adjusted_count\n'
                            'I1,a,2025,University,2,0.5\n')
        candidate.write_text(baseline.read_text().replace('0.5\n', '0.50001\n'))
        keys = ('institution_id', 'area', 'year')
        self.assertTrue(compare_table(baseline, candidate, keys, 1e-4)['passed'])
        candidate.write_text(candidate.read_text().replace('University,2', 'Changed,3'))
        result = compare_table(baseline, candidate, keys, 1e-4)
        self.assertFalse(result['passed'])
        self.assertEqual(result['field_mismatches'], {'institution_name': 1, 'pub_count': 1})

    def test_candidate_release_is_parallel_reproducible_and_promotable(self):
        fixture = self.path / 'project'
        for relative in build_release.CODE_FILES:
            target = fixture / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        data = fixture / 'data'
        data.mkdir(exist_ok=True)
        registry = {'areas': {'circuits': {'name': 'Circuits', 'default_on': True,
                                         'venues': [{'key': 'isscc'}, {'key': 'jssc'}]}}}
        (data / 'areas.json').write_text(json.dumps(registry))
        (data / 'affiliation-map.csv').write_text('raw_affiliation,institution_id,status\n')
        (data / 'institution-aliases.csv').write_text('duplicate_id,canonical_id,canonical_name\n')
        (data / 'excluded-works.csv').write_text('work_key\n')
        (data / 'institutions.json').write_text(json.dumps({'by_id': {
            'https://openalex.org/I1': {'display_name': 'University', 'country_code': 'US'}}}))
        manifest = self.path / 'refresh.json'
        manifest.write_text(json.dumps({'files': [
            {'venue': p.parts[-3], 'year': int(p.parts[-2]), 'sha256': runtime.digest(p)}
            for p in self.raw.glob('*/*/works.jsonl')]}))
        releases = []
        for name in ['cold', 'warm']:
            output = self.path / name
            execution = subprocess.run([sys.executable, str(fixture / 'pipeline/build_release.py'),
                            '--cache-dir', str(self.raw), '--out', str(output),
                            '--refresh-manifest', str(manifest), '--workers', '2',
                            '--executor', 'processes'], capture_output=True, text=True,
                           timeout=30)
            self.assertEqual(execution.returncode, 0, execution.stderr + execution.stdout)
            releases.append(json.loads((output / 'manifest.json').read_text()))
        self.assertEqual(releases[0]['aggregation']['cache_misses'], 2)
        self.assertEqual(releases[1]['aggregation']['cache_hits'], 2)
        self.assertEqual(releases[0]['artifacts'], releases[1]['artifacts'])
        import promote_release
        with patch.object(promote_release, 'ROOT', fixture):
            promote_release.validate_candidate(self.raw, self.path / 'warm')


if __name__ == '__main__':
    unittest.main()
