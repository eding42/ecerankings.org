import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
from build_release import validate


class ReleaseValidationTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
