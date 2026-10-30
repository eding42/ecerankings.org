import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
import aggregate


def iid(value):
    return 'https://openalex.org/' + value


def institution(iid):
    return {'id': iid, 'display_name': iid, 'type': 'education'}


def work(doi='10.1/research', institutions=None):
    return {'id': 'W1', 'doi': doi, 'title': 'Research', 'publication_year': 2025,
            'type': 'article', 'authorships': [
                {'author_id': 'A1', 'author_name': 'Author',
                 'institutions': institutions or [institution('I1')]}]}


class AggregateSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, venue, works):
        path = self.cache / venue / '2025' / 'works.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(w) + '\n' for w in works))

    def test_replayed_work_does_not_inflate_credit(self):
        self.write('journal', [work(), work()])
        result = aggregate.process_venues(['journal'], {'journal': ('area', 'Area')},
                                          None, {}, cache_dir=str(self.cache))
        self.assertEqual(result[0][(iid('I1'), 'area', 2025)],
                         {'pub_count': 1, 'adjusted_count': 1.0})

    def test_explicit_venue_ownership_applies_to_existing_cache(self):
        self.write('tecs', [work()])
        self.write('emsoft', [work()])
        result = aggregate.process_venues(
            ['tecs', 'emsoft'], {'tecs': ('embedded', 'Embedded'), 'emsoft': ('embedded', 'Embedded')},
            None, {}, cache_dir=str(self.cache),
            venue_exclusions={'tecs': {'doi:10.1/research'}})
        self.assertEqual(result[0][(iid('I1'), 'embedded', 2025)]['adjusted_count'], 1.0)
        self.assertEqual(set(k[2] for k in result[1]), {'emsoft'})

    def test_distinct_no_doi_records_with_same_title_remain_distinct(self):
        first, second = work(doi=None), work(doi=None)
        second['id'] = 'W2'
        self.write('journal', [first, second])
        result = aggregate.process_venues(['journal'], {'journal': ('area', 'Area')},
                                          None, {}, cache_dir=str(self.cache))
        self.assertEqual(result[0][(iid('I1'), 'area', 2025)]['pub_count'], 2)

    def test_scoped_command_rejects_a_symlink_to_public_data(self):
        link = self.cache / 'public-link'
        link.symlink_to(ROOT / 'site/data', target_is_directory=True)
        result = subprocess.run([sys.executable, str(ROOT / 'pipeline/aggregate.py'),
                                 '--venue', 'jssc', '--out', str(link)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Scoped runs require --out', result.stderr)

    def test_canonical_affiliations_are_deduplicated_before_division(self):
        self.write('journal', [work(institutions=[institution('I1'), institution('I2'), institution('I3')])])
        result = aggregate.process_venues(
            ['journal'], {'journal': ('area', 'Area')}, None, {},
            aliases={'I1': ('I0', 'Canonical'), 'I2': ('I0', 'Canonical')},
            cache_dir=str(self.cache))
        self.assertEqual(result[0][(iid('I0'), 'area', 2025)]['adjusted_count'], .5)
        self.assertEqual(result[0][(iid('I3'), 'area', 2025)]['adjusted_count'], .5)

    def test_alias_lookup_accepts_url_and_bare_id_forms(self):
        self.write('journal', [work(institutions=[institution(iid('I1'))])])
        result = aggregate.process_venues(['journal'], {'journal': ('area', 'Area')}, None, {},
                                          aliases={'I1': ('I2', 'Canonical')}, cache_dir=str(self.cache))
        self.assertEqual(result[0][(iid('I2'), 'area', 2025)]['adjusted_count'], 1)

    def test_alias_cycles_fail_instead_of_misassigning_credit(self):
        with self.assertRaisesRegex(ValueError, 'alias cycle'):
            aggregate.canonical_aliases({'I1': ('I2', ''), 'I2': ('I1', '')})

    def test_scoped_command_cannot_overwrite_public_outputs(self):
        sentinel = ROOT / 'site/data/inst-area-year.csv'
        before = sentinel.read_bytes()
        result = subprocess.run([sys.executable, str(ROOT / 'pipeline/aggregate.py'),
                                 '--venue', 'jssc', '--year', '2025'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Scoped runs require --out', result.stderr)
        self.assertEqual(sentinel.read_bytes(), before)

    def test_lfs_preflight_fails_before_any_output_is_written(self):
        path = self.cache / 'jssc/2025/works.jsonl'
        path.parent.mkdir(parents=True)
        path.write_text('version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 100\n')
        output = self.cache / 'output'
        result = subprocess.run([sys.executable, str(ROOT / 'pipeline/aggregate.py'),
                                 '--all-cached', '--cache-dir', str(self.cache), '--out', str(output)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unmaterialized Git LFS pointer', result.stderr)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
