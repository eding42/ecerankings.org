import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))

import audit_bylines as B
import audit_map_sample as S
import dropped_credit as D
import verify_authors as V

CREDIT = {'education', 'facility', 'government', 'nonprofit'}


def map_row(raw, iid='I1', name='Uni', kind='education', status='auto', cc='US', via=''):
    return {'raw_affiliation': raw, 'status': status, 'institution_id': f'https://openalex.org/{iid}' if iid else '',
            'institution_name': name, 'institution_type': kind, 'country_code': cc, 'matched_via': via}


class WilsonTests(unittest.TestCase):
    def test_interval_brackets_the_estimate_and_narrows_with_n(self):
        p, low, high = S.wilson(3, 58)
        self.assertAlmostEqual(p, 3 / 58)
        self.assertLess(low, p)
        self.assertGreater(high, p)
        self.assertLess(S.wilson(30, 580)[2] - S.wilson(30, 580)[1], high - low)
        self.assertEqual(S.wilson(0, 0), (0.0, 0.0, 1.0))


class MapAuditTests(unittest.TestCase):
    def item(self, **current):
        base = {'status': 'auto', 'institution_id': 'https://openalex.org/I1', 'institution_name': 'Uni',
                'institution_type': 'education', 'country_code': 'US', 'matched_via': ''}
        return {'key': 'k', 'raw_affiliation': 'x', 'strata': {'credit': 1}, 'current': {**base, **current},
                'credit_share': 1.0}

    def test_each_outcome(self):
        aliases = {'I9': 'I1'}
        cases = [
            (self.item(), {'decision': 'supported', 'institution_id': 'https://openalex.org/I1'}, 'correct'),
            (self.item(), {'decision': 'corrected', 'institution_id': 'I9'}, 'correct'),      # alias of the same institution
            (self.item(), {'decision': 'corrected', 'institution_id': 'I2'}, 'wrong_institution'),
            (self.item(), {'decision': 'noneducation'}, 'wrong_credited'),
            (self.item(), {'decision': 'unresolved'}, 'undecidable'),
            (self.item(status='manual', institution_id='', institution_type=''), {'decision': 'corrected', 'institution_id': 'I2'}, 'missed_credit'),
            (self.item(status='manual', institution_id='', institution_type=''), {'decision': 'noneducation'}, 'correct'),
        ]
        for item, decision, expected in cases:
            self.assertEqual(S.classify(item, decision, aliases), expected, decision)

    def test_draw_is_deterministic_and_blind(self):
        rows = [map_row(f'University {i}, Somewhere', iid=f'I{i}', name=f'University {i}') for i in range(60)]
        rows += [map_row('Acme Labs, Palo Alto', iid='I99', name='Palo Alto University', via='Palo Alto')]
        share = {r['raw_affiliation']: 1.0 + i % 3 for i, r in enumerate(rows)}
        index = {r['institution_id']: {'id': r['institution_id'], 'display_name': r['institution_name'], 'alternatives': [], 'acronyms': []}
                 for r in rows}
        a, _ = S.draw_sample(rows, share, index, 40, seed=7)
        b, _ = S.draw_sample(list(reversed(rows)), share, index, 40, seed=7)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertNotEqual(json.dumps(a, sort_keys=True), json.dumps(S.draw_sample(rows, share, index, 40, seed=8)[0], sort_keys=True))
        with tempfile.TemporaryDirectory() as out:
            S.write_sample(out, a, {'seed': 7})
            blind = json.loads((Path(out) / 'blind-batch-0001.json').read_text())
            self.assertEqual(set(blind['rows'][0]), {'key', 'raw_affiliation'})

    def test_report_gates_on_the_credit_stratum(self):
        sample = {'items': [{**self.item(), 'key': str(i), 'raw_affiliation': str(i)} for i in range(10)]}
        decisions = {str(i): {'decision': 'noneducation' if i < 3 else 'supported', 'institution_id': 'I1'} for i in range(10)}
        per, outcomes = S.score(sample, decisions, {})
        report, failing = S.render_report(sample, per, outcomes, 1, 1000, 0.03)
        self.assertTrue(failing)
        self.assertIn('30.0%', report)
        self.assertIn('Disagreements', report)


class AuthorIntegrityTests(unittest.TestCase):
    def test_name_tests(self):
        self.assertTrue(V.is_group_name('The Supernova Cosmology Project'))
        self.assertTrue(V.is_group_name('(Spitzer Team)'))
        self.assertFalse(V.is_group_name('Ann Teamer'))
        self.assertTrue(V.is_garbled('Fran�ois Diederich'))
        self.assertTrue(V.is_garbled('R&#xE9;mi Gribonval'))
        self.assertFalse(V.is_garbled('Gáspár Å. Bakos'))

    def write_cache(self, root, venue, works):
        d = Path(root) / venue / '2020'
        d.mkdir(parents=True)
        (d / 'works.jsonl').write_text('\n'.join(json.dumps(w) for w in works))

    def work(self, i, n, **extra):
        return {'id': f'W{i}', 'doi': f'10.1/{i}', 'title': f'Paper {i}', 'type': 'article',
                'authorships': [{'author_id': f'A{i}-{k}', 'author_name': f'Person {k}', 'institutions': []} for k in range(n)], **extra}

    def test_truncation_duplicates_and_groups_are_found(self):
        works = [self.work(i, 100) for i in range(12)] + [self.work(100 + i, 7) for i in range(3)]
        dup = self.work(200, 4)
        dup['authorships'][1]['author_id'] = dup['authorships'][0]['author_id']
        dup['authorships'][2]['author_name'] = 'The Foo Collaboration'
        works.append(dup)
        registry = {'areas': {'a': {'default_on': True, 'venues': [{'key': 'v'}]}}}
        with tempfile.TemporaryDirectory() as root:
            self.write_cache(root, 'v', works)
            result = V.scan(root, registry)
        flags = V.check({'critical': [], 'high': [], 'medium': [], 'low': []}, result)
        text = ' '.join(sum(flags.values(), []))
        self.assertIn('[authors/truncated] v: 12 works', text)
        self.assertEqual(result['venues']['v']['dup_works'], 1)
        self.assertEqual(result['venues']['v']['group_authors'], 1)

    def test_front_matter_without_authors_is_not_a_finding(self):
        works = [{'id': f'W{i}', 'doi': f'10.1/{i}', 'title': 'Blank page', 'type': 'article', 'authorships': []}
                 for i in range(30)] + [self.work(100 + i, 3) for i in range(30)]
        registry = {'areas': {'a': {'default_on': True, 'venues': [{'key': 'v'}]}}}
        with tempfile.TemporaryDirectory() as root:
            self.write_cache(root, 'v', works)
            flags = V.check({'critical': [], 'high': [], 'medium': [], 'low': []}, V.scan(root, registry))
        self.assertEqual([m for m in sum(flags.values(), []) if 'authors/none' in m], [])


class DroppedCreditTests(unittest.TestCase):
    types = {'I1': 'education', 'I2': 'company'}

    def reason(self, author, doi='10.1/x', native=True, amap=None, negative=frozenset()):
        return D.classify_author(author, doi, native, amap or {}, self.types, negative, CREDIT)[0]

    def test_reasons(self):
        credited = {'institutions': [{'id': 'https://openalex.org/I1', 'type': 'education'}]}
        self.assertIsNone(self.reason(credited))
        self.assertEqual(self.reason({'institutions': [{'id': 'https://openalex.org/I2', 'type': 'company'}]}), 'openalex_noncredit')
        self.assertEqual(self.reason({'institutions': [{'id': 'https://openalex.org/I1', 'type': None, 'display_name': 'Tampere'}]}),
                         'untyped_institution')
        self.assertEqual(self.reason({'raw_affiliations': ['UCR']}, amap={'UCR': ('I1', 'UC Riverside', 'other')}), 'retyped_row')
        self.assertEqual(self.reason({'raw_affiliations': ['Acme']}, amap={'Acme': ('I2', 'Acme', 'company')}), 'raw_noncredit')
        self.assertEqual(self.reason({'raw_affiliations': ['??']}), 'raw_unmapped')
        self.assertEqual(self.reason({}), 'no_affiliation:never_backfilled')
        self.assertEqual(self.reason({}, native=False), 'no_affiliation:other')
        self.assertEqual(self.reason({}, doi='10.1/x', negative={'10.1/x'}), 'no_affiliation:backfill_tried')
        self.assertEqual(self.reason({}, doi=''), 'no_affiliation:no_doi')


class BylineAuditTests(unittest.TestCase):
    def test_comparison_outcomes(self):
        self.assertEqual(B.compare(['a', 'b'], ['a', 'b']), 'exact')
        self.assertEqual(B.compare(['b', 'a'], ['a', 'b']), 'reordered')
        self.assertEqual(B.compare(['a'], ['a', 'b', 'c']), 'cache_short')
        self.assertEqual(B.compare(['a', 'b', 'c'], ['a']), 'cache_long')
        self.assertEqual(B.compare(['a', 'b', 'c'], ['a', 'b', 'd']), 'names_differ')
        self.assertEqual(B.compare(['x', 'y'], []), 'no_reference')

    def test_names_compare_across_scripts_and_hyphens(self):
        self.assertEqual(B.family_key('José‐Luis Olvera‐Cervantes'), B.family_key('Jose-Luis Olvera-Cervantes'))
        self.assertEqual(B.family_key('Eric H. Neilsen, Jr.'), 'neilsen')


if __name__ == '__main__':
    unittest.main()
