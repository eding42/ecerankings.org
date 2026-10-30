#!/usr/bin/env python3
"""Compare aggregate identities, names, counts, credits, and default-area scores.

Row order may differ from older builds. Names and integer counts must match
exactly; each credit and geometric-mean score must meet the absolute tolerance.
"""
import argparse
import collections
import csv
import json
import math
from pathlib import Path

TABLES = {
    'inst-area-year.csv': ('institution_id', 'area', 'year'),
    'inst-venue-year.csv': ('institution_id', 'area', 'venue', 'year'),
    'author-info.csv': ('author_id', 'area', 'year', 'institution_id'),
}


def compare_table(reference, candidate, key_fields, tolerance):
    expected = {}
    with reference.open(newline='') as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames
        for row in reader:
            key = tuple(row[field] for field in key_fields)
            if key in expected:
                raise ValueError(f'Duplicate reference key in {reference.name}: {key}')
            expected[key] = tuple(row[field] for field in columns if field not in key_fields)
    remaining = set(expected)
    values = [field for field in columns if field not in key_fields]
    report = {'reference_rows': len(expected), 'candidate_rows': 0,
              'missing_keys': 0, 'extra_or_duplicate_keys': 0,
              'field_mismatches': collections.Counter(), 'max_credit_difference': 0.0}
    with candidate.open(newline='') as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise ValueError(f'Column mismatch: {candidate.name}')
        for row in reader:
            report['candidate_rows'] += 1
            key = tuple(row[field] for field in key_fields)
            if key not in remaining:
                report['extra_or_duplicate_keys'] += 1
                continue
            remaining.remove(key)
            for field, baseline in zip(values, expected[key]):
                if field == 'adjusted_count':
                    actual, baseline = float(row[field]), float(baseline)
                    if not math.isfinite(actual) or not math.isfinite(baseline):
                        report['field_mismatches'][field] += 1
                        continue
                    delta = abs(actual - baseline)
                    report['max_credit_difference'] = max(report['max_credit_difference'], delta)
                    if delta > tolerance:
                        report['field_mismatches'][field] += 1
                elif row[field] != baseline:
                    report['field_mismatches'][field] += 1
    report['missing_keys'] = len(remaining)
    report['passed'] = not (remaining or report['extra_or_duplicate_keys'] or report['field_mismatches'])
    return report


def ranking_scores(directory, registry, from_year=None, to_year=None):
    areas = [key for key, area in registry['areas'].items() if area.get('default_on')]
    if not areas:
        raise ValueError('No default-on areas')
    totals = collections.defaultdict(lambda: collections.defaultdict(float))
    with (directory / 'inst-area-year.csv').open(newline='') as handle:
        for row in csv.DictReader(handle):
            year = int(row['year'])
            if ((from_year is not None and year < from_year)
                    or (to_year is not None and year > to_year) or row['area'] not in areas):
                continue
            totals[row['institution_id']][row['area']] += float(row['adjusted_count'])
    return {iid: math.expm1(sum(math.log1p(counts[area]) for area in areas) / len(areas))
            for iid, counts in totals.items()}


def compare(reference, candidate, registry, tolerance=1e-4):
    tables = {name: compare_table(reference / name, candidate / name, keys, tolerance)
              for name, keys in TABLES.items()}
    scores = []
    # Whole-corpus and recent windows include zero-count default-on areas.
    for lower, upper in [(None, None), (2016, 2025), (2021, 2025), (2026, 2026)]:
        baseline = ranking_scores(reference, registry, lower, upper)
        actual = ranking_scores(candidate, registry, lower, upper)
        delta = max((abs(actual[iid] - value) for iid, value in baseline.items() if iid in actual), default=0)
        scores.append({'from': lower, 'to': upper, 'max_score_difference': delta,
                       'passed': baseline.keys() == actual.keys() and delta <= tolerance})
    return {'passed': all(v['passed'] for v in tables.values()) and all(v['passed'] for v in scores),
            'tolerance': tolerance, 'tables': tables, 'ranking_scores': scores}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--registry', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'data/areas.json')
    parser.add_argument('--tolerance', type=float, default=1e-4)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if not math.isfinite(args.tolerance) or args.tolerance < 0:
        parser.error('--tolerance must be finite and nonnegative')
    result = compare(args.reference, args.candidate, json.loads(args.registry.read_text()), args.tolerance)
    payload = json.dumps(result, indent=2) + '\n'
    if args.report:
        args.report.write_text(payload)
    print(payload, end='')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
