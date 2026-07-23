"""Generalized multi-campus cluster misattribution fixer.

Approach:
1. Find groups of institutions sharing a common prefix (clusters)
2. For each cluster member, extract the distinguishing suffix keywords
3. Scan affiliation-map.csv for raw strings mentioning the prefix + a specific campus keyword
4. Fix any row mapped to the wrong campus member

Run: python3 .tmp/fix_campus_clusters.py
"""
import csv
import json
import re
from collections import defaultdict

# ── Cluster definitions ────────────────────────────────────────────
# Each cluster: (system_prefix, [(campus_keywords, expected_id, expected_name), ...])
# Keywords are ordered most-specific-first to avoid partial matches.
# "Common prefix" is the system prefix to match in raw_affiliation.

CLUSTERS = [
    ("University of California", [
        (["san diego", "ucsd", "la jolla", "calit2", "jacobs school of engineering"], "https://openalex.org/I36258959", "University of California San Diego"),
        (["santa barbara", "ucsb"], "https://openalex.org/I154570441", "University of California, Santa Barbara"),
        (["los angeles", "ucla"], "https://openalex.org/I161318765", "University of California, Los Angeles"),
        (["irvine", "uci"], "https://openalex.org/I204250578", "University of California, Irvine"),
        (["berkeley"], "https://openalex.org/I95457486", "University of California, Berkeley"),
        (["santa cruz", "ucsc"], "https://openalex.org/I185103710", "University of California, Santa Cruz"),
        (["davis"], "https://openalex.org/I84218800", "University of California, Davis"),
        (["riverside", "ucr"], "https://openalex.org/I103635307", "University of California, Riverside"),
        (["merced", "ucm"], "https://openalex.org/I156087764", "University of California, Merced"),
        (["san francisco", "ucsf"], "https://openalex.org/I180670191", "University of California, San Francisco"),
    ]),
    ("University of Texas", [
        (["austin", "utexas", "ut austin"], "https://openalex.org/I8618152", "University of Texas at Austin"),
        (["dallas", "utdallas", "ut dallas"], "https://openalex.org/I61561971", "University of Texas at Dallas"),
        (["arlington", "uta"], "https://openalex.org/I75885583", "University of Texas at Arlington"),
        (["san antonio", "utsa"], "https://openalex.org/I61619893", "University of Texas at San Antonio"),
        (["el paso", "utep"], "https://openalex.org/I95384979", "University of Texas at El Paso"),
        (["tyler"], "https://openalex.org/I100591422", "University of Texas at Tyler"),
        (["permi", "of the permian"], "https://openalex.org/I104919839", "University of Texas of the Permian Basin"),
        (["rio grande"], "https://openalex.org/I46121591", "University of Texas Rio Grande Valley"),
    ]),
    ("University of Illinois", [
        (["urbana", "champaign", "uiuc"], "https://openalex.org/I157725225", "University of Illinois Urbana-Champaign"),
        (["chicago", "uic"], "https://openalex.org/I39422238", "University of Illinois Chicago"),
        (["springfield", "uis"], "https://openalex.org/I79884896", "University of Illinois at Springfield"),
    ]),
    ("University of Maryland", [
        (["college park", "umd", "umcp"], "https://openalex.org/I66946132", "University of Maryland, College Park"),
        (["baltimore county", "umbc"], "https://openalex.org/I79272384", "University of Maryland, Baltimore County"),
        (["baltimore", "umb"], "https://openalex.org/I126744593", "University of Maryland, Baltimore"),
        (["eastern shore", "umes"], "https://openalex.org/I22407884", "University of Maryland Eastern Shore"),
    ]),
    ("University of Colorado", [
        (["boulder", "ucb", "cu boulder"], "https://openalex.org/I188538660", "University of Colorado Boulder"),
        (["denver", "ucdenver", "cu denver", "anschutz"], "https://openalex.org/I921990950", "University of Colorado Denver"),
        (["colorado springs", "uccs"], "https://openalex.org/I888729015", "University of Colorado Colorado Springs"),
    ]),
    ("University of Massachusetts", [
        (["amherst", "umass amherst"], "https://openalex.org/I24603500", "University of Massachusetts Amherst"),
        (["boston", "umb", "umass boston"], "https://openalex.org/I33434090", "University of Massachusetts Boston"),
        (["lowell", "umass lowell"], "https://openalex.org/I133738476", "University of Massachusetts Lowell"),
        (["dartmouth", "umassd"], "https://openalex.org/I100633361", "University of Massachusetts Dartmouth"),
        (["chan", "medical school", "worcester"], "https://openalex.org/I166722992", "University of Massachusetts Chan Medical School"),
    ]),
    ("University of Washington", [
        (["seattle", "uw", "university of washington$"], "https://openalex.org/I201448701", "University of Washington"),
        (["tacoma", "uwt"], "https://openalex.org/I4210150356", "University of Washington Tacoma"),
        (["bothell", "uwb"], "https://openalex.org/I4210138624", "University of Washington Bothell"),
    ]),
    ("University of Michigan", [
        (["ann arbor", "umich", "umichigan", "university of michigan$"], "https://openalex.org/I27837315", "University of Michigan"),
        (["dearborn", "umd"], "https://openalex.org/I4210130704", "University of Michigan–Dearborn"),
        (["flint", "umflint"], "https://openalex.org/I4210092198", "University of Michigan–Flint"),
    ]),
    ("University of Wisconsin", [
        (["madison", "uw madison", "uw-madison"], "https://openalex.org/I135310074", "University of Wisconsin–Madison"),
        (["milwaukee", "uwm", "uw-milwaukee"], "https://openalex.org/I43579087", "University of Wisconsin–Milwaukee"),
    ]),
    ("Texas A&M", [
        (["at qatar", "qatar"], "https://openalex.org/I58152225", "Texas A&M University at Qatar"),
        (["kingsville"], "https://openalex.org/I181414168", "Texas A&M University – Kingsville"),
        (["corpus christi", "tamucc"], "https://openalex.org/I128682931", "Texas A&M University–Corpus Christi"),
        (["commerce", "tamuc"], "https://openalex.org/I109557771", "Texas A&M University–Commerce"),
        (["international"], "https://openalex.org/I100653242", "Texas A&M International University"),
        # Default Texas A&M College Station
        (["college station", "tamu", "texas a&m university$"], "https://openalex.org/I91045830", "Texas A&M University"),
    ]),
    ("Indian Institute of Technology", [
        (["bombay", "iitb", "mumbai"], "https://openalex.org/I41316267", "Indian Institute of Technology Bombay"),
        (["delhi", "iitd"], "https://openalex.org/I73295861", "Indian Institute of Technology Delhi"),
        (["madras", "iitm", "chennai"], "https://openalex.org/I78784900", "Indian Institute of Technology Madras"),
        (["kanpur", "iitk"], "https://openalex.org/I12875819", "Indian Institute of Technology Kanpur"),
        (["kharagpur", "iitkgp"], "https://openalex.org/I30401643", "Indian Institute of Technology Kharagpur"),
        (["roorkee", "iitr"], "https://openalex.org/I45159170", "Indian Institute of Technology Roorkee"),
        (["guwahati", "iitg"], "https://openalex.org/I60986386", "Indian Institute of Technology Guwahati"),
        (["hyderabad", "iith"], "https://openalex.org/I96815566", "Indian Institute of Technology Hyderabad"),
        (["gandhinagar", "iitgn"], "https://openalex.org/I4210157303", "Indian Institute of Technology Gandhinagar"),
        (["bhu", "varanasi"], "https://openalex.org/I221098338", "Indian Institute of Technology BHU"),
        (["jodhpur", "iitj"], "https://openalex.org/I4210096097", "Indian Institute of Technology Jodhpur"),
        (["patna", "iitp"], "https://openalex.org/I4210138036", "Indian Institute of Technology Patna"),
        (["mandi", "iit mandi"], "https://openalex.org/I4210111082", "Indian Institute of Technology Mandi"),
        (["r opar", "ropar", "iitrpr"], "https://openalex.org/I125044677", "Indian Institute of Technology Ropar"),
        (["bhilai", "iitbhilai"], "https://openalex.org/I4210126525", "Indian Institute of Technology Bhilai"),
        (["goa", "iit goa"], "https://openalex.org/I4210122508", "Indian Institute of Technology Goa"),
        (["palakkad", "iitpkd"], "https://openalex.org/I4210118363", "Indian Institute of Technology Palakkad"),
        (["tirupati", "iittp"], "https://openalex.org/I4210116869", "Indian Institute of Technology Tirupati"),
        (["indore", "iiti"], "https://openalex.org/I4210137438", "Indian Institute of Technology Indore"),
        (["dhanbad", "ism"], "https://openalex.org/I203650698", "Indian Institute of Technology Dhanbad"),
    ]),
    ("Technische Universität", [
        (["münchen", "munchen", "tum", "garching"], "https://openalex.org/I186189362", "Technical University of Munich"),
        (["darmstadt", "tuda"], "https://openalex.org/I161976081", "Technische Universität Darmstadt"),
        (["dresden", "tud"], "https://openalex.org/I79636420", "Technische Universität Dresden"),
        (["berlin", "tub"], "https://openalex.org/I168164651", "Technische Universität Berlin"),
        (["wien", "vienna", "tuwien"], "https://openalex.org/I131987676", "TU Wien"),
        (["graz", "tugraz"], "https://openalex.org/I115475555", "Graz University of Technology"),
        (["hamburg", "tuhh"], "https://openalex.org/I138391447", "Hamburg University of Technology"),
        (["ilmenau", "tu ilmenau"], "https://openalex.org/I37042786", "Technische Universität Ilmenau"),
        (["chemnitz", "tuc"], "https://openalex.org/I170543206", "Technische Universität Chemnitz"),
        (["karlsruhe", "kit"], "https://openalex.org/I74572056", "Karlsruhe Institute of Technology"),
        (["braunschweig", "tu braunschweig"], "https://openalex.org/I38568133", "University of Braunschweig – Institute of Technology"),
        (["cottbus", "b-tu"], "https://openalex.org/I174935819", "Brandenburg University of Technology Cottbus-Senftenberg"),
        (["freiberg", "tu freiberg"], "https://openalex.org/I173577767", "TU Bergakademie Freiberg"),
        #("klaus", "https://openalex.org/I115475555", "Graz University of Technology"),  # partial - removed, too broad
    ]),
    ("Politecnico di", [
        (["milano", "milan"], "https://openalex.org/I123021657", "Politecnico di Milano"),
        (["torino", "turin"], "https://openalex.org/I177477856", "Politecnico di Torino"),
        (["bari"], "https://openalex.org/I214249186", "Politecnico di Bari"),
    ]),
    ("University of North Carolina", [
        (["chapel hill", "unc chapel hill", "unc$"], "https://openalex.org/I114027177", "University of North Carolina at Chapel Hill"),
        (["charlotte", "uncc"], "https://openalex.org/I102149020", "University of North Carolina at Charlotte"),
        (["greensboro", "uncg"], "https://openalex.org/I169335092", "University of North Carolina at Greensboro"),
        (["wilmington", "uncw"], "https://openalex.org/I153901656", "University of North Carolina Wilmington"),
    ]),
    ("University of Tennessee", [
        (["knoxville", "utk", "ut knoxville"], "https://openalex.org/I75027704", "University of Tennessee at Knoxville"),
        (["chattanooga", "utc"], "https://openalex.org/I177097968", "University of Tennessee at Chattanooga"),
        (["martin", "utm"], "https://openalex.org/I109963312", "University of Tennessee at Martin"),
        (["health science", "uthsc"], "https://openalex.org/I160606119", "University of Tennessee Health Science Center"),
    ]),
    ("Wuhan University", [
        (["wuhan university$", "whu"], "https://openalex.org/I37461747", "Wuhan University"),
        (["of technology", "wut"], "https://openalex.org/I196699116", "Wuhan University of Technology"),
        (["of science", "wust"], "https://openalex.org/I43922553", "Wuhan University of Science and Technology"),
    ]),
]

# ── Load data ──────────────────────────────────────────────────────

with open('data/affiliation-map.csv') as f:
    rows = list(csv.DictReader(f))
    fieldnames = csv.DictReader(open('data/affiliation-map.csv')).fieldnames

# ── Fix ────────────────────────────────────────────────────────────

WRONG_TYPES = {"https://openalex.org/I180670191", "https://openalex.org/I4210166787",
               "https://openalex.org/I118691135", "https://openalex.org/I4210152479"}

fixed_count = 0
skip_unfixable = 0

for r in rows:
    raw = r['raw_affiliation']
    lower = raw.lower()
    current_id = r.get('institution_id', '')
    if not current_id:
        continue

    def kw_match(keywords, text):
        """Match keywords against text, supporting $ for end-of-string anchors."""
        for kw in keywords:
            if kw.endswith('$'):
                # Exact end-of-string match (with punctuation tolerance)
                pattern = re.escape(kw[:-1]) + r'[\s,;.:!?]*$'
                if re.search(pattern, text, re.IGNORECASE):
                    return True
            else:
                if kw in text:
                    return True
        return False

    for prefix, campuses in CLUSTERS:
        if prefix.lower() not in lower:
            continue

        # Find which campus this raw string matches
        matched_campus = None
        for keywords, expected_id, expected_name in campuses:
            if kw_match(keywords, lower):
                matched_campus = (expected_id, expected_name)
                break

        if matched_campus and current_id != matched_campus[0]:
            # Only fix if current is a commonly-known wrong default
            # or if the current doesn't match any campus in this cluster
            current_in_cluster = any(current_id == c[1] for c in campuses)
            if not current_in_cluster or current_id in WRONG_TYPES:
                old_name = r.get('institution_name', '')
                r['institution_id'] = matched_campus[0]
                r['institution_name'] = matched_campus[1]
                r['status'] = 'manual'
                if not r.get('country_code'):
                    from_country = matched_campus[0]
                    r['country_code'] = 'US' if 'openalex.org/I' in from_country else ''
                if not r.get('institution_type'):
                    r['institution_type'] = 'education'
                fixed_count += 1
                if fixed_count <= 10:
                    print(f"FIX: {raw[:70]}")
                    print(f"     {old_name} -> {matched_campus[1]}")
        break  # one cluster per raw string

print(f"\nFixed: {fixed_count}")

if fixed_count > 0:
    with open('data/affiliation-map.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print("Written to data/affiliation-map.csv")
else:
    print("No changes needed.")
