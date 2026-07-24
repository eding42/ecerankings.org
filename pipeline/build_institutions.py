#!/usr/bin/env python3
"""Build institution metadata: name, country code, for all institutions in inst-area-year.csv.

Uses data/institutions.json (OpenAlex snapshot) as the authoritative source for country codes.
Falls back to affiliation-map.csv, then name-based geo-heuristics.
"""

import argparse, csv, json, os, sys

# Institution name → country keyword patterns (ordered: US first to avoid false matches)
HEURISTICS = [
    ("US", ["united states", " usa,", "california", "massachusetts", "illinois",
            "michigan", "texas", "florida", "ohio", "pennsylvania", "new york",
            "washington", "georgia", "carolina", "virginia", "wisconsin", "minnesota",
            "maryland", "indiana", "colorado", "arizona", "oregon", "missouri",
            "tennessee", "iowa", "kansas", "kentucky", "alabama", "connecticut",
            "nebraska", "utah", "nevada", "hawaii", "montana", "idaho", "maine",
            "vermont", "new hampshire", "rhode island", "delaware", "wyoming",
            "dakota", "purdue", "mit,", "gatech", "caltech", "cmu",
            "university of calif", "johns hopkins", "rice university",
            "duke university", "yale", "princeton", "columbia university",
            "nyu", "university of south", "ucla", "uc san", "uc santa",
            "uc irvine", "uc davis", "uc riverside", "uc berkeley",
            "texas a&m", "texas a", "penn state", "virginia tech", "ohio state",
            "michigan state", "iowa state", "north carolina state", "arizona state",
            "washington state", "oregon state", "oklahoma state", "kansas state",
            "louisiana state", "mississippi state", "utah state", "georgia state",
            "florida state", "colorado state", "boise state", "montana state"]),
    ("CN", ["beijing", "shanghai", "tsinghua", "peking", "zhejiang",
            "nanjing", "wuhan", "tianjin", "xi'an", "harbin", "shenzhen",
            ", china", "chinese academy", "fudan", "huazhong",
            "southeast university", "tongji", "dalian", "sichuan",
            "jilin", "shandong", "xiamen", "lanzhou", "hunan", "sun yat-sen"]),
    ("GB", ["united kingdom", ", uk", "london", "oxford", "cambridge",
            "imperial college", "manchester", "edinburgh", "bristol",
            "southampton", "sheffield", "birmingham", "nottingham",
            "leeds", "glasgow", "liverpool", "warwick", "durham",
            "university college london", "king's college"]),
    ("DE", ["germany", "deutschland", "berlin", "munich", "münchen",
            "stuttgart", "dresden", "aachen", "karlsruhe", "darmstadt",
            "hannover", "heidelberg", "freiburg", "rwth", "tum,",
            "tu dresden", "tu berlin", "tu darmstadt", "tu münchen"]),
    ("JP", ["japan", "tokyo", "kyoto", "osaka", "nagoya", "tohoku",
            "hokkaido", "keio", "waseda", "kyushu", "tsukuba",
            "tokyo institute", "university of tokyo"]),
    ("KR", ["korea", "seoul", "snu", "kaist", "postech", "yonsei",
             "sungkyunkwan", "hanyang", "gist", "dgist", "unist"]),
    ("CA", ["canada", "toronto", "vancouver", "montreal", "mcgill",
            "university of waterloo", "ubc", "alberta", "calgary",
            "mcmaster", "queen's", "ottawa", "western ontario", "dalhousie"]),
    ("FR", ["france", "paris", "lyon", "marseille", "toulouse",
            "grenoble", "sorbonne", "polytechnique", "inria", "cnrs"]),
    ("AU", ["australia", "sydney", "melbourne", "brisbane", "adelaide",
            "perth", "monash", "unsw", "anu", "queensland"]),
    ("IN", ["iit ", "iit-", "indian institute", "bombay,", "delhi,", "madras,",
            "kanpur", "kharagpur", "roorkee", "guwahati", "hyderabad,",
            "iisc", "bits pilani", "nit ", "national institute of technology"]),
    ("SG", ["singapore", "ntu", "nus"]),
    ("CH", ["switzerland", "zurich", "epfl", "eth", "lausanne", "geneva", "bern,", "basel"]),
    ("NL", ["netherlands", "delft", "amsterdam", "eindhoven", "utrecht", "leiden",
            "groningen", "wageningen"]),
    ("IT", ["italy,", "milano", "roma", "torino", "bologna,", "firenze",
            "napoli", "politecnico di milano", "politecnico di torino"]),
    ("ES", ["spain", "madrid", "barcelona", "valencia", "sevilla", "zaragoza", "catalunya"]),
    ("SE", ["sweden", "stockholm", "lund", "uppsala", "chalmers", "kth", "gothenburg", "linköping"]),
    ("TW", ["taiwan", "taipei", "hsinchu", "tainan", "nctu"]),
    ("BR", ["brazil", "brasil", "são paulo", "rio de janeiro", "campinas", "usp", "unicamp"]),
    ("IL", ["israel", "tel aviv", "haifa", "technion", "weizmann", "hebrew", "ben-gurion"]),
    ("BE", ["belgium", "leuven", "brussels", "ghent", "liège", "ku leuven", "uclouvain"]),
    ("AT", ["austria", "wien", "vienna", "graz", "tu wien", "tu graz", "johannes kepler"]),
    ("DK", ["denmark", "copenhagen", "aarhus", "aalborg", "dtu", "sdu"]),
    ("FI", ["finland", "helsinki", "tampere", "aalto", "oulu", "turku", "lut"]),
    ("NO", ["norway", "oslo", "trondheim", "ntnu", "bergen", "stavanger"]),
    ("HK", ["hong kong", "hkust", "hku", "cuhk", "cityu", "polyu"]),
    ("RU", ["russia", "moscow", "saint petersburg", "novosibirsk", "tomsk"]),
    ("IR", ["iran", "tehran", "sharif", "amirkabir", "isfahan"]),
    ("TR", ["turkey", "ankara", "istanbul", "boğaziçi", "bilkent", "koç"]),
]


def guess_country(name):
    lower = name.lower()
    for cc, keywords in HEURISTICS:
        for kw in keywords:
            if kw in lower:
                return cc
    return ""


def main():
    parser = argparse.ArgumentParser(description="Build institution metadata lookup.")
    parser.add_argument("--affiliations", default="data/affiliation-map.csv")
    parser.add_argument("--input", default="site/data/inst-area-year.csv")
    parser.add_argument("--out", default="site/data/institutions.json")
    parser.add_argument("--oa-db", default="data/institutions.json")
    args = parser.parse_args()

    # Step 0: load OpenAlex institution DB as authoritative country source
    oa_country = {}
    try:
        with open(args.oa_db) as f:
            oa = json.load(f)
        for iid, info in oa["by_id"].items():
            cc = info.get("country_code", "")
            if cc:
                oa_country[iid] = cc.upper()
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        print(f"Warning: could not load {args.oa_db}; falling back to affiliation-map")

    # Step 1: collect all unique institution IDs from inst-area-year
    inst_ids = set()
    with open(args.input, newline="") as f:
        for row in csv.DictReader(f):
            inst_ids.add(row["institution_id"])

    # Step 2: collect names from affiliation-map (first match per id)
    inst_names = {}
    with open(args.affiliations, newline="") as f:
        for row in csv.DictReader(f):
            iid = row["institution_id"]
            if not iid or iid not in inst_ids or iid in inst_names:
                continue
            inst_names[iid] = row.get("institution_name", "")

    # Step 3: build final data with OA country as primary source
    inst_data = {}
    for iid in inst_ids:
        name = inst_names.get(iid, "")
        cc = oa_country.get(iid, "")
        if not name:
            # Fall back to inst-area-year name if not in aff-map
            cc = cc or guess_country(iid)
        inst_data[iid] = {"name": name, "country": cc}

    # Step 4: fill in missing names and countries from inst-area-year
    with open(args.input, newline="") as f:
        for row in csv.DictReader(f):
            iid = row["institution_id"]
            if iid not in inst_data:
                name = row["institution_name"]
                cc = oa_country.get(iid, "") or guess_country(name)
                inst_data[iid] = {"name": name, "country": cc}
            else:
                if not inst_data[iid]["name"]:
                    inst_data[iid]["name"] = row["institution_name"]
                if not inst_data[iid]["country"]:
                    inst_data[iid]["country"] = (
                        oa_country.get(iid, "") or guess_country(inst_data[iid]["name"] or row["institution_name"])
                    )

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(inst_data, f, separators=(",", ":"))

    # Count countries
    from collections import Counter
    ccounts = Counter(v["country"] for v in inst_data.values())
    missing = ccounts.get("", 0)

    print(f"{'Country':>6s}  Institutions")
    print("-" * 26)
    for cc, count in ccounts.most_common(20):
        print(f"  {cc if cc else '??':>6s}  {count:>5d}")

    print(f"\n  ...{len(ccounts)-20} more countries...")
    print(f"\nWrote {len(inst_data)} institutions to {args.out}")
    print(f"Missing country: {missing} institutions ({missing/len(inst_data)*100:.1f}%)")


if __name__ == "__main__":
    main()
