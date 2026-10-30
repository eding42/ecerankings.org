import json
import pathlib
import sys
import tempfile
import unittest
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
from build_release import validate
from package_site import package, PACKAGE_MARKER
from prepare_refresh import preserve_paper_evidence, collection_evidence
import promote_release as promotion
import aggregate


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = pathlib.Path(self.tmp.name)
        self.registry = {'areas': {'a': {'name': 'Area', 'default_on': True,
                                         'venues': [{'key': 'journal'}]}}}

    def candidate(self):
        out = self.path / 'candidate'
        out.mkdir()
        (out / 'institutions.json').write_text(json.dumps({'I1': {'name': 'University', 'country': 'US'}}))
        (out / 'inst-area-year.csv').write_text('institution_id,institution_name,area,year,pub_count,adjusted_count\nI1,University,a,2025,1,0.5\n')
        (out / 'inst-venue-year.csv').write_text('institution_id,institution_name,area,venue,year,pub_count,adjusted_count\nI1,University,a,journal,2025,1,0.5\n')
        (out / 'author-info.csv').write_text('author_id,institution_id,area,year,adjusted_count\nA1,I1,a,2025,0.5\n')
        (out / 'a.json').write_text(json.dumps([{'i': 'I1', 'n': 'University', 'y': 2025, 'p': 1, 'a': .5}]))
        (out / 'a').mkdir()
        (out / 'a/journal.json').write_text((out / 'a.json').read_text())
        return out

    def test_valid_candidate_reconciles(self):
        self.assertEqual(validate(self.candidate(), self.registry)['status'], 'passed')

    def test_a_dead_venue_in_an_otherwise_healthy_area_blocks_release(self):
        self.registry['areas']['a']['venues'].append({'key': 'missing'})
        with self.assertRaisesRegex(ValueError, 'venues with no credit'):
            validate(self.candidate(), self.registry)

    def test_json_paper_count_must_match_csv(self):
        out = self.candidate()
        rows = json.loads((out / 'a.json').read_text())
        rows[0]['p'] = 100
        (out / 'a.json').write_text(json.dumps(rows))
        with self.assertRaisesRegex(ValueError, 'JSON differs'):
            validate(out, self.registry)

    def test_author_credit_must_reconcile(self):
        out = self.candidate()
        (out / 'author-info.csv').write_text('author_id,institution_id,area,year,adjusted_count\nA1,I1,a,2025,0.9\n')
        with self.assertRaisesRegex(ValueError, 'Author and area credit'):
            validate(out, self.registry)

    def test_venue_json_must_match_csv(self):
        out = self.candidate()
        (out / 'a/journal.json').write_text('[]')
        with self.assertRaisesRegex(ValueError, 'Venue JSON is incomplete'):
            validate(out, self.registry)

    def test_duplicate_venue_credit_fails(self):
        out = self.candidate()
        path = out / 'inst-venue-year.csv'
        path.write_text(path.read_text() + path.read_text().splitlines()[-1] + '\n')
        with self.assertRaisesRegex(ValueError, 'Duplicate or invalid venue'):
            validate(out, self.registry)

    def test_packager_preserves_unrelated_existing_directory(self):
        out = self.path / 'unrelated'
        out.mkdir()
        sentinel = out / 'keep.txt'
        sentinel.write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'Refusing to replace'):
            package(self.path / 'not-read', out)
        self.assertEqual(sentinel.read_text(), 'preserve')

    def test_package_hash_failure_preserves_previous_package(self):
        site, out = self.path / 'site', self.path / 'public'
        (site / 'data').mkdir(parents=True)
        (site / 'data/areas.json').write_text(json.dumps(self.registry))
        (site / 'data/institutions.json').write_text('{}')
        (site / 'data/a.json').write_text('[]')
        for name in ['index.html', '404.html', 'methodology.html', 'coverage.html', 'styles.css', 'main.js',
                     'rank.js', 'methodology.js', 'coverage.js', 'eding-shared.css', '_headers']:
            (site / name).write_text('fixture')
        (site / 'data/manifest.json').write_text(json.dumps({'validation': {'status': 'passed'}, 'artifacts': {}}))
        out.mkdir()
        (out / PACKAGE_MARKER).write_text('generated')
        (out / 'index.html').write_text('previous release')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            package(site, out)
        self.assertEqual((out / 'index.html').read_text(), 'previous release')

    def test_lfs_promotion_keeps_a_cache_that_can_be_aggregated(self):
        source = self.path / 'source.jsonl'
        work = {'doi': '10.1/example', 'title': 'A paper', 'publication_year': 2025, 'type': 'article',
                'authorships': [{'author_id': 'A1', 'author_name': 'Author',
                                 'institutions': [{'id': 'I1', 'display_name': 'University', 'type': 'education'}]}]}
        source.write_text(json.dumps(work) + '\n')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        pointer = f'version https://git-lfs.github.com/spec/v1\noid sha256:{digest}\nsize {source.stat().st_size}\n'.encode()
        target = self.path / 'cache/journal/2025/works.jsonl'
        with patch.object(promotion, 'ROOT', self.path):
            with patch.object(promotion.subprocess, 'run', return_value=SimpleNamespace(stdout=pointer)):
                promotion.export_lfs(source, target, digest)
        self.assertEqual(target.read_bytes(), source.read_bytes())
        result = aggregate.process_venues(['journal'], {'journal': ('a', 'Area')}, None, {},
                                           cache_dir=str(self.path / 'cache'))
        self.assertEqual(result[0][('https://openalex.org/I1', 'a', 2025)]['adjusted_count'], 1)

    def test_bad_lfs_result_preserves_previous_working_file(self):
        source, target = self.path / 'source', self.path / 'cache/working'
        source.write_text('candidate')
        target.parent.mkdir()
        target.write_text('previous')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        with patch.object(promotion, 'ROOT', self.path):
            with patch.object(promotion.subprocess, 'run', return_value=SimpleNamespace(stdout=b'bad pointer')):
                with self.assertRaisesRegex(ValueError, 'LFS clean result differs'):
                    promotion.export_lfs(source, target, digest)
        self.assertEqual(target.read_text(), 'previous')

    def test_profile_affiliations_cannot_be_carried_into_historical_evidence(self):
        old = {'source': 'semanticscholar', 'authorships': [{'author_name': 'Author', 'raw_affiliations': ['Current University']}]}
        fresh = {'authorships': [{'author_name': 'Author', 'raw_affiliations': [], 'institutions': []}]}
        result, retained = preserve_paper_evidence(fresh, old)
        self.assertEqual(result, fresh)
        self.assertEqual(retained, 0)

    def test_initials_and_diacritics_retain_verified_paper_affiliations(self):
        old = {'doi': '10.1/example', 'title': 'A research paper',
               'authorships': [{'author_name': 'Sun-Yuan Kung', 'institutions': [{'id': 'I1'}]},
                              {'author_name': 'Daniel Ménard', 'institutions': [{'id': 'I2'}]}]}
        fresh = {'doi': 'https://doi.org/10.1/example', 'title': 'A research paper',
                 'authorships': [{'author_name': 'S. Y. Kung', 'institutions': [], 'raw_affiliations': []},
                                {'author_name': 'D. Menard', 'institutions': [], 'raw_affiliations': []}]}
        result, retained = preserve_paper_evidence(fresh, old)
        self.assertEqual(retained, 2)
        self.assertEqual([a['institutions'][0]['id'] for a in result['authorships']], ['I1', 'I2'])
        self.assertFalse(fresh['authorships'][0]['institutions'])

    def test_ambiguous_initials_do_not_assign_an_affiliation(self):
        old = {'doi': '10.1/example', 'title': 'A research paper',
               'authorships': [{'author_name': 'John Smith', 'institutions': [{'id': 'I1'}]},
                              {'author_name': 'Jane Smith', 'institutions': [{'id': 'I2'}]}]}
        fresh = {'doi': '10.1/example', 'title': 'A research paper',
                 'authorships': [{'author_name': 'J. Smith', 'institutions': [], 'raw_affiliations': []}]}
        result, retained = preserve_paper_evidence(fresh, old)
        self.assertEqual(result, fresh)
        self.assertEqual(retained, 0)

    def test_reconciled_affiliations_keep_the_new_complete_byline(self):
        old = {'doi': '10.1/example', 'title': 'A research paper',
               'authorships': [{'author_name': 'Alice Jones', 'institutions': [{'id': 'I1'}]}]}
        fresh = {'doi': '10.1/example', 'title': 'A research paper',
                 'authorships': [{'author_name': 'Alice Jones', 'institutions': [], 'raw_affiliations': []},
                                {'author_name': 'Bob Green', 'institutions': [], 'raw_affiliations': []}]}
        result, retained = preserve_paper_evidence(fresh, old)
        self.assertEqual(retained, 1)
        self.assertEqual(len(result['authorships']), 2)
        self.assertEqual(result['authorships'][0]['institutions'], [{'id': 'I1'}])
        self.assertFalse(result['authorships'][1]['institutions'])

    def test_prior_affiliations_require_paper_identity_and_matching_middle_names(self):
        old = {'doi': '10.1/example', 'title': 'A research paper',
               'authorships': [{'author_name': 'John Michael Smith', 'institutions': [{'id': 'I1'}]}]}
        fresh = {'doi': '10.1/example', 'title': 'A research paper',
                 'authorships': [{'author_name': 'John Robert Smith', 'institutions': [], 'raw_affiliations': []}]}
        self.assertEqual(preserve_paper_evidence(fresh, old)[1], 0)
        fresh['authorships'][0]['author_name'] = 'John Michael Smith'
        fresh['doi'] = '10.1/different'
        self.assertEqual(preserve_paper_evidence(fresh, old)[1], 0)
        fresh['doi'] = old['doi']
        fresh['title'] = 'An unrelated publication'
        self.assertEqual(preserve_paper_evidence(fresh, old)[1], 0)

    def test_current_explicit_raw_affiliation_is_not_overridden_by_prior_resolution(self):
        old = {'doi': '10.1/example', 'title': 'A research paper',
               'authorships': [{'author_name': 'Alice Jones', 'institutions': [{'id': 'I1'}]}]}
        fresh = {'doi': '10.1/example', 'title': 'A research paper',
                 'authorships': [{'author_name': 'A. Jones', 'institutions': [],
                                  'raw_affiliations': ['Current provider affiliation']}]}
        result, retained = preserve_paper_evidence(fresh, old)
        self.assertEqual(retained, 0)
        self.assertEqual(result, fresh)

    def test_repaired_collection_errors_are_not_final_gaps(self):
        path = self.path / 'collection.json'
        manifest = {'years': {'journal': {'2025': {'status': 'complete'}}},
                    'errors': [{'venue': 'journal', 'year': 2025, 'error': 'old failure'},
                               {'venue': 'journal', 'year': 2026, 'error': 'still incomplete'}]}
        path.write_text(json.dumps(manifest))
        result = collection_evidence('journals', path, manifest)
        self.assertEqual(result['status_counts'], {'complete': 1, 'blocked': 1})
        self.assertEqual([(r['year'], r['reason']) for r in result['unresolved_scopes']],
                         [(2026, 'still incomplete')])


if __name__ == '__main__':
    unittest.main()
