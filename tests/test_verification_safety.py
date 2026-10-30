import contextlib
import csv
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
import verify


class VerificationSafetyTests(unittest.TestCase):
    def test_campus_detector_does_not_modify_input_by_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = pathlib.Path(temporary)
            (directory / 'data').mkdir()
            path = directory / 'data/affiliation-map.csv'
            with path.open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['raw_affiliation', 'status', 'institution_id',
                                                      'institution_name', 'country_code', 'institution_type'])
                writer.writeheader()
                writer.writerow({'raw_affiliation': 'University of California, San Diego',
                                 'status': 'auto', 'institution_id': 'Iwrong', 'institution_name': 'Wrong',
                                 'country_code': 'US', 'institution_type': 'education'})
            before = path.read_bytes()
            result = subprocess.run([sys.executable, str(ROOT / 'pipeline/fix_campus_clusters.py')],
                                    cwd=directory, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Fixed: 1', result.stdout)
            self.assertEqual(path.read_bytes(), before)

    def test_a_dead_venue_is_not_hidden_by_a_healthy_venue_in_the_same_area(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = pathlib.Path(temporary)
            with (directory / 'inst-area-year.csv').open('w') as f:
                f.write('institution_id,institution_name,area,year,pub_count,adjusted_count\nI1,University,a,2025,2,1.5\n')
            with (directory / 'inst-venue-year.csv').open('w') as f:
                f.write('institution_id,institution_name,area,venue,year,pub_count,adjusted_count\nI1,University,a,healthy,2025,2,1.5\n')
            registry = {'areas': {'a': {'name': 'Area', 'default_on': True,
                                       'venues': [{'key': 'healthy'}, {'key': 'missing'}]}}}
            args = types.SimpleNamespace(area=None, update_snapshots=False)
            with mock.patch.object(verify, 'SITE_DATA', str(directory)), \
                 mock.patch.object(verify, 'INST_JSON', str(directory / 'no-institutions.json')), \
                 mock.patch.object(verify, 'KNOWN_JSON', str(directory / 'no-known.json')), \
                 contextlib.redirect_stdout(io.StringIO()):
                flags = verify.phase3_aggregate(registry, args)
            self.assertTrue(any('[missing]' in message for message in flags['critical']))
            self.assertFalse((directory / '.ranking-snapshot.json').exists())


if __name__ == '__main__':
    unittest.main()
