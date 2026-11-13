import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))

import verify_global as G


def education(name, cc):
    return {'status': 'auto', 'institution_type': 'education', 'institution_id': 'I1',
            'institution_name': name, 'country_code': cc}


class CountryTests(unittest.TestCase):
    def test_string_country_excludes_mapped_country(self):
        self.assertEqual(G.country_contradiction('Southeast University,Nanjing,China', 'BD'), {'CN'})
        self.assertEqual(G.country_contradiction('MERL,Cambridge,MA,USA', 'GB'), {'US'})
        # A country inside the institution's own name counts as naming it.
        self.assertEqual(G.country_contradiction('Korea University', 'JP'), {'KR'})

    def test_matching_and_equivalent_countries_pass(self):
        self.assertIsNone(G.country_contradiction('Tsinghua University, Beijing, China', 'CN'))
        self.assertIsNone(G.country_contradiction('HKUST, Hong Kong, China', 'HK'))
        self.assertIsNone(G.country_contradiction('Syracuse University', 'US'))  # names no country
        self.assertIsNone(G.country_contradiction('Anything, China', ''))

    def test_place_names_containing_a_country_are_not_that_country(self):
        self.assertIsNone(G.country_contradiction('University of New Mexico, Albuquerque, NM', 'US'))
        self.assertIsNone(G.country_contradiction('University of New South Wales', 'AU'))
        self.assertIsNone(G.country_contradiction('Purdue University, West Lafayette, Indiana', 'US'))

    def test_company_strings(self):
        self.assertTrue(G.looks_like_company('Sony Semiconductor Solutions Corporation,Kanagawa,Japan'))
        self.assertTrue(G.looks_like_company('MediaTek Inc.,San Jose,CA,USA'))
        self.assertFalse(G.looks_like_company('Dept. of EE, Stanford University, CA, USA'))
        self.assertFalse(G.looks_like_company('Samsung Advanced Institute of Technology'))


class CheckTests(unittest.TestCase):
    def test_mismapped_rows_rank_by_credit_and_small_ones_are_summarised(self):
        raw_big, raw_small, raw_ok = 'Southeast University,Nanjing,China', 'York University,Toronto,Canada', 'MIT, USA'
        amap = {raw_big: education('Southeast University', 'BD'), raw_small: education('York University', 'US'),
                raw_ok: education('Massachusetts Institute of Technology', 'US')}
        flags = G.empty_flags()
        G.check_mismapped(flags, amap, Counter({raw_big: 30.0, raw_small: 1.0, raw_ok: 99.0}))
        self.assertEqual(len(flags['critical']), 1)
        self.assertIn('Southeast University (BD)', flags['critical'][0])
        self.assertEqual(flags['high'], [])
        self.assertIn('1 more rows', flags['medium'][0])

    def test_unaccepted_rows_are_ignored(self):
        row = {**education('Southeast University', 'BD'), 'status': 'review'}
        flags = G.empty_flags()
        G.check_mismapped(flags, {'Southeast University, China': row}, Counter({'Southeast University, China': 99}))
        self.assertEqual(flags, G.empty_flags())

    def registry(self, **venue):
        return {'areas': {'robotics': {'default_on': True, 'venues': [{'key': 'icra', **venue}]}}}

    def stats(self, papers, credit=None):
        return {('icra', y): Counter(papers=n, credit=(credit or {}).get(y, n * 0.8)) for y, n in papers.items()}

    def test_missing_year_in_window_is_flagged_unless_declared_or_biennial(self):
        years = {y: 900 for y in range(2016, 2026) if y != 2022}
        flags = G.empty_flags()
        G.check_missing_years(flags, self.registry(), self.stats(years), (2016, 2025), {})
        self.assertIn('no papers for 2022', flags['high'][0])
        flags = G.empty_flags()
        G.check_missing_years(flags, self.registry(years={'2022': {'source': 'none'}}), self.stats(years), (2016, 2025), {})
        self.assertEqual(flags['high'], [])
        flags = G.empty_flags()
        G.check_missing_years(flags, self.registry(), self.stats({y: 900 for y in range(2017, 2026, 2)}), (2016, 2025), {})
        self.assertEqual(flags['high'], [])
        flags = G.empty_flags()
        G.check_missing_years(flags, self.registry(), self.stats({2010: 5}), (2016, 2025), {})
        self.assertIn('no papers in 2016–2025', flags['critical'][0])

    def test_first_year_of_a_new_venue_is_not_a_gap(self):
        flags = G.empty_flags()
        G.check_missing_years(flags, self.registry(), self.stats({y: 100 for y in range(2020, 2026)}),
                              (2016, 2025), {'icra': 2020})
        self.assertEqual(flags['high'], [])

    def test_coverage_collapse_and_count_spike(self):
        papers = {y: 1000 for y in range(2016, 2026)}
        flags = G.empty_flags()
        G.check_venue_years(flags, self.registry(), self.stats(papers, {2025: 80}), (2016, 2025))
        self.assertEqual(len(flags['critical']), 1)
        self.assertIn('[icra/2025] 8% of paper credit', flags['critical'][0])
        papers[2019] = 4000
        flags = G.empty_flags()
        G.check_venue_years(flags, self.registry(), self.stats(papers), (2016, 2025))
        self.assertTrue(any('[icra/2019] 4000 papers' in f for f in flags['high']))

    def test_steady_growth_and_launch_years_are_not_outliers(self):
        growth = {2016: 60, 2017: 60, 2018: 70, 2019: 80, 2020: 90, 2021: 80, 2022: 85, 2023: 144, 2024: 198, 2025: 179}
        flags = G.empty_flags()
        G.check_venue_years(flags, self.registry(), self.stats(growth), (2016, 2025))
        self.assertEqual(flags['high'], [])
        launch = {2017: 17, 2018: 150, 2019: 150, 2020: 160, 2021: 160, 2022: 160}
        flags = G.empty_flags()
        G.check_venue_years(flags, self.registry(), self.stats(launch), (2016, 2025))
        self.assertEqual(flags['high'], [])

    def test_partial_year_far_above_the_norm_is_flagged(self):
        papers = {**{y: 260 for y in range(2016, 2026)}, 2026: 600}
        flags = G.empty_flags()
        G.check_venue_years(flags, self.registry(), self.stats(papers), (2016, 2025))
        self.assertTrue(any('[icra/2026] 600 papers' in f for f in flags['high']))

    def test_single_author_credit_and_front_matter(self):
        stats = {('icra', 2020): Counter(papers=500, credit=400.0, solo=150, solo_credit=90.0, front_matter=12,
                                         front_matter_credit=6.0)}
        flags = G.empty_flags()
        G.check_nonresearch(flags, self.registry(), stats, (2016, 2025))
        self.assertTrue(any('22% of university credit' in f for f in flags['critical']))
        self.assertTrue(any('12 front-matter records' in f for f in flags['high']))


class ScanTests(unittest.TestCase):
    def test_scan_credits_like_the_aggregator_and_reports_reference_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'cache/icra/2020').mkdir(parents=True)
            works = [
                {'doi': '10.1/a', 'title': 'A paper', 'type': 'article', 'authorships': [
                    {'institutions': [{'type': 'education'}]}, {'institutions': [{'type': 'company'}]}]},
                {'doi': '10.1/a', 'title': 'A paper', 'type': 'article', 'authorships': [
                    {'institutions': [{'type': 'education'}]}]},                      # duplicate DOI
                {'doi': '10.1/b', 'title': 'Session 3 overview', 'type': 'article', 'authorships': [
                    {'institutions': [], 'raw_affiliations': ['Southeast University, China']}]},
                {'doi': '10.1/c', 'title': 'Editorial', 'type': 'editorial', 'authorships': [
                    {'institutions': [{'type': 'education'}]}]},
            ]
            (tmp / 'cache/icra/2020/works.jsonl').write_text(''.join(json.dumps(w) + '\n' for w in works))
            amap = {'Southeast University, China': education('Southeast University', 'BD')}
            stats, usage = G.scan_cache(str(tmp / 'cache'), ['icra'], amap, set())
            c = stats[('icra', 2020)]
            self.assertEqual(c['papers'], 2)
            self.assertAlmostEqual(c['credit'], 1.5)
            self.assertEqual((c['solo'], c['front_matter']), (1, 1))
            self.assertAlmostEqual(usage['Southeast University, China'], 1.0)

            data = tmp / 'data'
            data.mkdir()
            (data / 'inst-area-year.csv').write_text(
                'institution_id,institution_name,area,year,pub_count,adjusted_count\nhttps://openalex.org/I1,A,robotics,2020,1,1\n')
            (data / 'institutions.json').write_text('{}')
            known = tmp / 'known.json'
            known.write_text(json.dumps({'robotics': ['https://openalex.org/I1', 'https://openalex.org/I999']}))
            flags = G.empty_flags()
            with mock.patch.object(G, 'KNOWN_JSON', str(known)), mock.patch.object(G, 'TRAPS_CSV', str(tmp / 'none.csv')):
                G.check_reference_lists(flags, str(data))
            self.assertTrue(any('I999' in f and 'I1,' not in f for f in flags['critical']))
            self.assertTrue(any('[traps]' in f for f in flags['critical']))


if __name__ == '__main__':
    unittest.main()
