#!/usr/bin/env python3
"""Build and package the static Earth, Planetary, and Space Sciences ranking website.

Takes aggregated institutional counts from pipeline/aggregate.py and produces
the static site payloads for site/earth-space/.

Usage:
    python3 pipeline/package_earth_space_site.py
"""

import csv
import json
import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

AREAS_EARTH_SPACE = os.path.join(REPO_ROOT, "data", "areas_earth_space.json")
AGGREGATES_DIR = os.path.join(REPO_ROOT, ".tmp", "earth_space_aggregates")
SITE_INTEGRATED = os.path.join(REPO_ROOT, "site", "earth-space")


def package_site(target_dir):
    site_data_dir = os.path.join(target_dir, "data")
    os.makedirs(site_data_dir, exist_ok=True)

    with open(AREAS_EARTH_SPACE) as f:
        registry = json.load(f)

    # 1. Copy areas registry
    shutil.copy2(AREAS_EARTH_SPACE, os.path.join(site_data_dir, "areas.json"))

    # 2. Package institutions.json from inst-area-year.csv
    inst_csv_path = os.path.join(AGGREGATES_DIR, "inst-area-year.csv")
    institutions = {}
    area_records = {k: [] for k in registry["areas"]}

    with open(inst_csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            iid = row["institution_id"]
            name = row["institution_name"]
            area = row["area"]
            year = int(row["year"])
            pub_count = int(row["pub_count"])
            adj_count = float(row["adjusted_count"])

            if iid not in institutions:
                institutions[iid] = {
                    "name": name,
                    "country": "",
                    "type": "education"
                }

            if area in area_records:
                area_records[area].append({
                    "i": iid,
                    "n": name,
                    "y": year,
                    "p": pub_count,
                    "a": adj_count
                })

    # Enrich country codes and institution types from base institutions and cached works
    inst_json_path = os.path.join(REPO_ROOT, "site", "data", "institutions.json")
    if os.path.exists(inst_json_path):
        try:
            with open(inst_json_path) as f:
                base_insts = json.load(f)
            for iid in institutions:
                if iid in base_insts:
                    institutions[iid]["country"] = base_insts[iid].get("country", "")
                    institutions[iid]["type"] = base_insts[iid].get("type", "education")
        except Exception:
            pass

    missing = {iid for iid, data in institutions.items() if not data.get("country")}
    if missing:
        cache_dir = os.path.join(REPO_ROOT, "cache")
        for area in registry["areas"].values():
            for venue in area["venues"]:
                vkey = venue["key"]
                vdir = os.path.join(cache_dir, vkey)
                if not os.path.isdir(vdir):
                    continue
                for yr in sorted(os.listdir(vdir)):
                    wf = os.path.join(vdir, yr, "works.jsonl")
                    if not os.path.isfile(wf):
                        continue
                    with open(wf) as f:
                        for line in f:
                            w = json.loads(line)
                            for a in w.get("authorships", []):
                                for inst in a.get("institutions", []):
                                    iid = inst.get("id")
                                    if iid in missing:
                                        cc = inst.get("country_code")
                                        itype = inst.get("type")
                                        if cc:
                                            institutions[iid]["country"] = cc
                                            missing.remove(iid)
                                        if itype:
                                            institutions[iid]["type"] = itype
                                    if not missing:
                                        break
                                if not missing:
                                    break
                            if not missing:
                                break
                    if not missing:
                        break
                if not missing:
                    break

    out_inst_file = os.path.join(site_data_dir, "institutions.json")
    with open(out_inst_file, "w") as f:
        json.dump(institutions, f, separators=(",", ":"))
    print(f"[{target_dir}] Wrote {len(institutions)} institutions (missing country: {len(missing)}) to {out_inst_file}")

    # 3. Write {area}.json files
    for area_key, records in area_records.items():
        out_area_file = os.path.join(site_data_dir, f"{area_key}.json")
        with open(out_area_file, "w") as f:
            json.dump(records, f, separators=(",", ":"))
        print(f"[{target_dir}] Wrote {len(records)} records for area '{area_key}'")

    # 4. Write per-venue {area}/{venue}.json files
    venue_csv_path = os.path.join(AGGREGATES_DIR, "inst-venue-year.csv")
    if os.path.exists(venue_csv_path):
        venue_records = {}
        with open(venue_csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                area = row["area"]
                venue = row["venue"]
                key = (area, venue)
                if key not in venue_records:
                    venue_records[key] = []
                venue_records[key].append({
                    "i": row["institution_id"],
                    "n": row["institution_name"],
                    "y": int(row["year"]),
                    "p": int(row["pub_count"]),
                    "a": float(row["adjusted_count"])
                })

        for (area, venue), rows in venue_records.items():
            area_dir = os.path.join(site_data_dir, area)
            os.makedirs(area_dir, exist_ok=True)
            v_path = os.path.join(area_dir, f"{venue}.json")
            with open(v_path, "w") as f:
                json.dump(rows, f, separators=(",", ":"))

    # 5. Manifest
    manifest = {
        "schema_version": 1,
        "latest_complete_year": 2025,
        "earliest_year": 2005,
        "default_start_year": 2016,
        "default_end_year": 2025,
        "generated_at": "2026-11-12",
        "description": "EarthSpaceRankings: Astronomy, Planetary Science, Geosciences & Climate Dynamics"
    }
    with open(os.path.join(site_data_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # 6. Copy static assets from site/
    static_files = [
        "styles.css", "main.js", "rank.js", "rank-history.js", "rank-history.css",
        "comparison.js", "comparison.css", "year-strip.js", "year-strip.css",
        "coverage.js", "favicon.svg"
    ]
    for sf in static_files:
        src = os.path.join(REPO_ROOT, "site", sf)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(target_dir, sf))

    # 7. Write index.html with appropriate title and sister site navigation
    is_integrated = (target_dir == SITE_INTEGRATED)
    parent_prefix = "../" if is_integrated else "./"
    bio_prefix = "../biology/" if is_integrated else "https://bio.ecerankings.org/"
    ece_prefix = "../" if is_integrated else "https://ecerankings.org/"

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>EarthSpaceRankings: Astronomy, Planetary Science, Geosciences &amp; Climate</title>
  <meta name="description" content="Institutions ranked by peer-reviewed research papers in Astronomy &amp; Astrophysics, Planetary Science, Geosciences, and Cryosphere &amp; Climate Dynamics.">
  <meta name="color-scheme" content="light dark">
  <meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#141619" media="(prefers-color-scheme: dark)">
  <link rel="icon" href="favicon.svg" type="image/svg+xml">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="EarthSpaceRankings">
  <meta property="og:title" content="EarthSpaceRankings: Astronomy, Planetary Science, Geosciences &amp; Climate">
  <meta property="og:description" content="Institutions ranked by peer-reviewed research papers in Astronomy &amp; Astrophysics, Planetary Science, Geosciences, and Cryosphere &amp; Climate Dynamics.">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="stylesheet" href="styles.css?v=geo1">
  <link rel="stylesheet" href="rank-history.css?v=geo1">
  <link rel="stylesheet" href="comparison.css?v=geo1">
  <link rel="stylesheet" href="year-strip.css?v=geo1">
  <script type="module" src="main.js?v=geo1"></script>
</head>
<body>
  <a class="skip" href="#rankings">Skip to rankings</a>

  <header class="site-header">
    <div class="wrap">
      <div class="site-branding">
        <a href="{ece_prefix}" class="site-brand-tab">ECERankings</a>
        <a href="{bio_prefix}" class="site-brand-tab">BiologyRankings</a>
        <p class="site-title"><a href="./">EarthSpaceRankings</a></p>
      </div>
      <nav aria-label="Site">
        <a class="eding-project-link" href="https://eding.dev/">Eding</a>
        <a href="./" aria-current="page">Rankings</a>
        <a href="methodology.html">Methodology</a>
        <a href="coverage.html">Data coverage</a>
        <a href="https://github.com/eding42/ecerankings.org">Source</a>
      </nav>
    </div>
  </header>

  <main class="wrap">
    <h1>Earth, Planetary &amp; Space Sciences Rankings</h1>
    <p class="lede">Institutions ranked by papers in selective astronomy, planetary and earth-science journals.</p>
    <p class="stamp" id="data-stamp"></p>

    <form class="filters" id="filters" aria-label="Ranking filters">
      <div class="field field-region">
        <label for="region">Region</label>
        <select id="region" disabled></select>
      </div>
      <div class="field field-type">
        <label for="inst-type">Institution type</label>
        <select id="inst-type" disabled>
          <option value="all">All institutions</option>
          <option value="education">Universities</option>
          <option value="research">Research labs &amp; centers</option>
          <option value="facility">Observatories &amp; facilities</option>
          <option value="government">Government agencies</option>
          <option value="nonprofit">Non-profit institutes</option>
        </select>
      </div>
      <div class="field">
        <label for="year-from">From</label>
        <select id="year-from" disabled></select>
      </div>
      <div class="field">
        <label for="year-to">To</label>
        <select id="year-to" disabled></select>
      </div>
      <div class="field field-grow">
        <label for="search">Find institution</label>
        <input id="search" type="search" autocomplete="off" spellcheck="false" enterkeyhint="search" placeholder="Name or abbreviation…">
      </div>
      <div class="field field-actions">
        <button type="button" id="export" disabled>Download CSV</button>
      </div>
    </form>

    <div id="year-strip" class="ys-main" hidden></div>

    <div class="layout">
      <aside class="areas" aria-labelledby="areas-heading">
        <details id="areas-panel" open>
          <summary><h2 id="areas-heading">Research areas <span id="area-count" class="muted"></span></h2></summary>
          <p class="area-actions">
            Select:
            <button type="button" class="link" data-select="defaults">defaults</button> ·
            <button type="button" class="link" data-select="all">all</button> ·
            <button type="button" class="link" data-select="none">none</button>
          </p>
          <div id="area-groups"><p class="muted">Loading areas…</p></div>
          <button type="button" id="areas-done" class="areas-done">Done</button>
        </details>
      </aside>

      <section class="results" id="rankings" aria-labelledby="results-heading">
        <h2 id="results-heading" class="visually-hidden">Rankings</h2>
        <div class="view-switch" role="group" aria-label="View">
          <button type="button" id="view-rankings" aria-pressed="true" aria-controls="ranking-view">Rankings</button>
          <button type="button" id="view-compare" aria-pressed="false" aria-controls="comparison-view">Compare <span id="comparison-count"></span></button>
        </div>
        <div id="comparison-tray" class="compare-tray" aria-live="polite"></div>
        <p id="status" class="status" role="status">Loading data…</p>
        <div id="error" class="error" role="alert" hidden></div>
        <div id="comparison-view" class="compare-panel" aria-label="Compare institutions" hidden></div>
        <div id="ranking-view">
        <div class="table-scroll">
          <table class="ranking" id="ranking-table">
            <caption class="visually-hidden">Institutions ranked by geometric-mean score across the selected areas.</caption>
            <thead>
              <tr>
                <th scope="col" class="num rank">#</th>
                <th scope="col">Institution</th>
                <th scope="col" class="num"><abbr title="Geometric mean of (1 + adjusted count) across the selected areas, minus one">Score</abbr></th>
                <th scope="col" class="num opt"><abbr title="Adjusted count: each paper worth 1, split evenly among its authors">Adj. count</abbr></th>
                <th scope="col" class="num opt"><abbr title="Distinct papers with at least one author at this institution">Papers</abbr></th>
                <th scope="col" class="num opt trend-cell"><abbr title="Rank in each year of the selected range, and places moved from the first year to the last">Trend</abbr></th>
              </tr>
            </thead>
            <tbody id="ranking-body"></tbody>
          </table>
        </div>
        <p class="pager" id="pager" hidden>
          <button type="button" id="show-more"></button>
          <button type="button" id="show-all" class="link"></button>
        </p>
        </div>
      </section>
    </div>
  </main>

  <footer class="site-footer">
    <div class="wrap">
      <p>Data from <a href="https://openalex.org/">OpenAlex</a></p>
      <noscript><p>The ranking table needs JavaScript.</p></noscript>
    </div>
  </footer>
</body>
</html>
"""
    with open(os.path.join(target_dir, "index.html"), "w") as f:
        f.write(index_html)
    print(f"[{target_dir}] Built index.html successfully.")


def main():
    print("Packaging Earth & Space static site...")
    package_site(SITE_INTEGRATED)
    print("Packaging complete!")


if __name__ == "__main__":
    main()
