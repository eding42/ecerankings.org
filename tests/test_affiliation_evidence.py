import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))

import affiliation_evidence as E
import fix_country_mismatches as F


def inst(iid, name, cc, kind='education', alternatives=()):
    return {'id': f'https://openalex.org/{iid}', 'display_name': name, 'country_code': cc, 'type': kind,
            'lineage': [f'https://openalex.org/{iid}'], 'alternatives': list(alternatives)}


BY_ID = {i['id']: i for i in [
    inst('I1', 'Southeast University', 'BD'), inst('I2', 'Southeast University', 'CN'),
    inst('I3', 'UCL Australia', 'AU', alternatives=['University College London']),
    inst('I4', 'University College London', 'GB'),
    inst('I5', 'University of Technology', 'RU'),
    inst('I6', 'University of Technology Sydney', 'AU'), inst('I7', 'Curtin University of Technology', 'AU'),
    inst('I8', 'Kanagawa University', 'JP'), inst('I9', 'Southeast University', 'CN', kind='company'),
]}
INDEX = E.build_name_index(BY_ID)


def row(iid, status='auto', via=''):
    i = BY_ID[f'https://openalex.org/{iid}']
    return {'status': status, 'institution_id': i['id'], 'institution_name': i['display_name'],
            'institution_type': i['type'], 'country_code': i['country_code'], 'lineage': i['id'], 'matched_via': via}


class GuardTests(unittest.TestCase):
    def test_same_name_in_the_named_country_replaces_the_match(self):
        r = E.guard_row('Southeast University,Nanjing,China', row('I1', via='Southeast University'), BY_ID, INDEX)
        self.assertEqual((r['status'], r['institution_id'], r['country_code']), ('auto', 'https://openalex.org/I2', 'CN'))

    def test_alternative_names_count_as_the_same_name(self):
        r = E.guard_row('EEE, University College London, London, UK', row('I3', via='University College London'), BY_ID, INDEX)
        self.assertEqual(r['institution_name'], 'University College London')
        self.assertEqual(r['country_code'], 'GB')

    def test_contradiction_without_a_single_alternative_goes_to_review(self):
        r = E.guard_row('University of Technology,Sydney,Australia', row('I5', via='University of Technology'), BY_ID, INDEX)
        self.assertEqual((r['status'], r['institution_name']), ('review', 'University of Technology'))

    def test_company_string_goes_to_review(self):
        r = E.guard_row('Sony Semiconductor Solutions Corporation,Kanagawa,Japan', row('I8', via='Kanagawa'), BY_ID, INDEX)
        self.assertEqual(r['status'], 'review')

    def test_consistent_and_non_auto_rows_are_untouched(self):
        ok = row('I2', via='Southeast University')
        self.assertEqual(E.guard_row('Southeast University, Nanjing, China', dict(ok), BY_ID, INDEX), ok)
        manual = row('I1', status='manual')
        self.assertEqual(E.guard_row('Southeast University, China', dict(manual), BY_ID, INDEX), manual)

    def test_proposals_split_into_mechanical_company_and_unresolved(self):
        rows = [{**row('I1', via='Southeast University'), 'raw_affiliation': 'Southeast University,Nanjing,China'},
                {**row('I5', via='University of Technology'), 'raw_affiliation': 'University of Technology,Sydney,Australia'},
                {**row('I8', via='Kanagawa'), 'raw_affiliation': 'NTT Corporation, Kanagawa, Japan'},
                {**row('I2', via='Southeast University'), 'raw_affiliation': 'Southeast University, China'},
                {**row('I1', status='review'), 'raw_affiliation': 'Southeast University, China.'},
                {**row('I1', status='manual'), 'raw_affiliation': 'SEU, Southeast University, China'},
                {**row('I2'), 'country_code': 'BD', 'raw_affiliation': 'Stale row country, Southeast University, China'}]
        corrections, companies, unresolved = F.propose(rows, BY_ID)
        self.assertEqual([(d['decision'], d['institution_id']) for d in corrections], [('corrected', 'I2')])
        self.assertEqual([d['decision'] for d in companies], ['noneducation'])
        self.assertEqual([(u[0], u[3]) for u in unresolved if u[4] != "evidence"],
                         [('University of Technology,Sydney,Australia', ''),
                          ('SEU, Southeast University, China', 'Southeast University (CN)')])
        self.assertTrue(all(d['evidence'] and d['decided_by'] for d in corrections + companies))


    def test_country_less_rows_follow_a_dominant_namesake(self):
        rows = [{**row('I1', via='Southeast University'), 'raw_affiliation': f'Lab {n}, Southeast University, China'}
                for n in range(5)]
        rows.append({**row('I1', via='Southeast University'), 'raw_affiliation': 'School of Automation, Southeast University'})
        rows.append({**row('I8', via='Kanagawa University'), 'raw_affiliation': 'Kanagawa University'})
        _, _, unresolved = F.propose(rows, BY_ID)
        self.assertEqual([(u[0], u[2]) for u in unresolved], [('School of Automation, Southeast University', set())])
        self.assertIn('Southeast University (CN), which 5 of 5', unresolved[0][3])


    def test_strings_with_no_academic_evidence_are_flagged(self):
        us = inst('I10', 'San Francisco State University', 'US', alternatives=['SFSU'])
        by = {**BY_ID, us['id']: us}
        index = E.build_name_index(by)
        self.assertFalse(E.academic_evidence('Tactical Computing Laboratories, San Francisco, CA, USA', us))
        self.assertTrue(E.academic_evidence('Dept. of EE, SFSU, USA', us))
        self.assertTrue(E.academic_evidence('Scuola Superiore Sant&#x2019;Anna, Pisa, Italy', us))
        r = E.guard_row('Tactical Computing Laboratories, San Francisco, CA, USA',
                        {**row('I1'), 'institution_id': us['id'], 'institution_name': us['display_name'],
                         'country_code': 'US', 'matched_via': 'San Francisco'}, by, index)
        self.assertEqual(r['status'], 'review')
        rows = [{**row('I1'), 'institution_id': us['id'], 'institution_name': us['display_name'], 'country_code': 'US',
                 'raw_affiliation': 'Tactical Computing Laboratories, San Francisco, CA, USA'}]
        _, _, unresolved = F.propose(rows, by)
        self.assertEqual([(u[0], u[4]) for u in unresolved], [(rows[0]['raw_affiliation'], 'evidence')])


if __name__ == '__main__':
    unittest.main()
