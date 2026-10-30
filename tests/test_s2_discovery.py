import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
from pipeline import s2_discovery as s2, harvest_s2


class Response(io.BytesIO):
    status = 200


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 0
        self.calls = []
        self.events = []

    def sleep(self, seconds):
        self.now += seconds

    def opener(self, request, timeout):
        self.calls.append((self.now, request))
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        return Response(json.dumps(event).encode())

    def client(self, **kwargs):
        return s2.Client(self.tmp.name, api_key='', opener=self.opener,
                         clock=lambda: self.now, sleep=self.sleep, jitter=lambda: 0, **kwargs)

    def error(self, status, headers=None):
        return urllib.error.HTTPError(s2.BASE, status, 'error', headers or {}, io.BytesIO(b'{}'))

    def test_retry_spacing_cache_and_offline(self):
        self.events = [self.error(429, {'Retry-After': '5'}), {'data': []}, {'data': []}]
        c = self.client()
        c.search('one')
        c.search('two')
        self.assertEqual([round(t, 1) for t, _ in self.calls], [0, 5, 6.1])
        self.assertEqual(self.client(offline=True).search('one'), [])
        self.assertEqual(len(self.calls), 3)

    def test_retry_http_date(self):
        self.events = [self.error(503, {'Retry-After': 'Thu, 01 Jan 1970 00:00:10 GMT'}), {}]
        self.client(wall_clock=lambda: 0).request('paper/x')
        self.assertEqual(self.calls[-1][0], 10)

    def test_failures_not_cached(self):
        for status in (429, 503, 403):
            self.events = [self.error(status)]
            with self.assertRaises(s2.S2Error):
                self.client(attempts=1).request('paper/x')
        self.assertEqual(list(Path(self.tmp.name).glob('*.json')), [])
        with self.assertRaises(s2.S2Error):
            self.client(offline=True).request('paper/x')

    def test_batch_nulls_chunking_and_metrics_opt_in(self):
        p = paper()
        p['citationCount'] = 12
        self.events = [[p, None], [p]]
        result = self.client().batch(['a', 'b', 'c'], batch_size=2, metrics=True)
        self.assertIsNone(result[1])
        self.assertEqual(result[0]['informational_metrics']['citationCount'], 12)
        self.assertEqual(json.loads(self.calls[0][1].data), {'ids': ['a', 'b']})
        self.assertNotIn('informational_metrics', s2.safe_paper(p))
        self.assertNotIn('affiliations', json.dumps(result))

    def test_cache_keys_include_body(self):
        self.events = [[paper()], [None]]
        c = self.client()
        c.batch(['a'])
        self.assertEqual(c.batch(['b']), [None])
        self.assertEqual(len(list(Path(self.tmp.name).glob('*.json'))), 2)

    def test_identity_ambiguity_and_handoff(self):
        canonical = {'title': 'A Study!', 'authors': ['Ada Lovelace'], 'year': 2025}
        p = paper()
        result = s2.discover(canonical, [p])
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['openalex_lookups'][0]['value'], '10.48550/arXiv.1234.5678')
        self.assertNotIn('affiliations', json.dumps(result))
        q = dict(p, paperId='other')
        self.assertEqual(s2.discover(canonical, [p, q])['status'], 'ambiguous')
        for q in (dict(p, authors=[]), dict(p, title='other'), dict(p, year=2020)):
            self.assertEqual(s2.discover(canonical, [q])['status'], 'unresolved')
        self.assertEqual(canonical['authors'], ['Ada Lovelace'])

    def test_reconciliation(self):
        report = s2.reconcile([{'id': 'publisher:1', 'title': 'A Study', 'authors': [], 'year': 2025},
                               {'title': 'Missing', 'authors': []}], [paper()])
        self.assertIn('author_count_mismatch', report['papers'][0]['issues'])
        self.assertIn('possible_version_mismatch', report['papers'][0]['issues'])
        self.assertEqual(report['papers'][1]['issues'], ['missing_in_s2'])
        self.assertTrue(report['audit_only'])

    def test_env_precedence(self):
        path = Path(self.tmp.name) / '.env'
        path.write_text('export S2_API_KEY="file-key"\nOTHER=private\n')
        with patch.dict('os.environ', {'S2_API_KEY': 'env-key'}):
            self.assertEqual(s2.load_api_key(path), 'env-key')
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(s2.load_api_key(path), 'file-key')

    def test_legacy_cannot_write_ranking_cache_or_profile_attribution(self):
        p = {'year': 2025, 'venue_key': 'iclr', 'authors': [{'authorId': '1', 'name': 'Ada'}]}
        with patch.object(harvest_s2, 'REPO_ROOT', self.tmp.name):
            harvest_s2.write_cache([p], {'1': ['Current University']})
        self.assertFalse((Path(self.tmp.name) / 'cache').exists())
        row = json.loads(next(Path(self.tmp.name).rglob('candidates.jsonl')).read_text())
        a = row['authorships'][0]
        self.assertEqual(a['raw_affiliations'], [])
        self.assertEqual(a['institutions'], [])
        self.assertEqual(a['s2_profile_affiliations_audit_only'], ['Current University'])

    def test_transport_retry_and_corrupt_cache(self):
        self.events = [urllib.error.URLError('offline'), {'data': []}]
        c = self.client()
        c.search('test')
        cache = next(Path(self.tmp.name).glob('*.json'))
        cache.write_text('broken')
        with self.assertRaises(s2.S2Error):
            self.client(offline=True).search('test')
        self.events = [{'data': [paper()]}]
        self.assertNotIn('affiliations', json.dumps(c.search('test')))

    def test_permanent_error_and_batch_validation(self):
        self.events = [self.error(401), []]
        c = self.client()
        with self.assertRaises(s2.S2Error):
            c.search('test')
        with self.assertRaises(s2.S2Error):
            c.batch(['one'])
        with self.assertRaises(ValueError):
            c.batch(['one'], batch_size=501)
        with self.assertRaises(ValueError):
            c.request('https://example.com')

def paper():
    return {'paperId': 's1', 'title': 'A Study', 'year': 2024,
            'externalIds': {'ArXiv': '1234.5678v2'},
            'authors': [{'name': 'Ada Lovelace', 'affiliations': ['Current University']}],
            'authorships': [{'raw_affiliations': ['POISON']}]}
