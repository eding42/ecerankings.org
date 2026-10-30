#!/usr/bin/env python3
"""Harvest historical conference proceedings for Tier A venues from Crossref and hydrate via OpenAlex.

Covers 2006-2015 for:
- isca
- micro
- hpca
- asplos
- rtss
- rtas
- emsoft
- iccad
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import unicodedata

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
MAILTO = "eding2019@gmail.com"

PROCEEDINGS_CONFIG = {
    'isca': {
        2006: {'ct': '33rd International Symposium on Computer Architecture (ISCA\'06)', 'prefix': '10.1109/isca.2006'},
        2007: {'ct': 'Proceedings of the 34th annual international symposium on Computer architecture', 'prefix': '10.1145/1250662'},
        2008: {'ct': '2008 International Symposium on Computer Architecture', 'prefix': '10.1109/isca.2008'},
        2009: {'ct': 'Proceedings of the 36th annual international symposium on Computer architecture', 'prefix': '10.1145/1555754'},
        2010: {'ct': 'Proceedings of the 37th annual international symposium on Computer architecture', 'prefix': '10.1145/1815961'},
        2011: {'ct': 'Proceedings of the 38th annual international symposium on Computer architecture', 'prefix': '10.1145/2000064'},
        2012: {'ct': '2012 39th Annual International Symposium on Computer Architecture (ISCA)', 'prefix': '10.1109/isca.2012'},
        2013: {'ct': 'Proceedings of the 40th Annual International Symposium on Computer Architecture', 'prefix': '10.1145/2485922'},
        2014: {'ct': '2014 ACM/IEEE 41st International Symposium on Computer Architecture (ISCA)', 'prefix': '10.1109/isca.2014'},
        2015: {'ct': 'Proceedings of the 42nd Annual International Symposium on Computer Architecture', 'prefix': '10.1145/2749469'},
    },
    'micro': {
        2006: {'ct': '39th Annual IEEE/ACM International Symposium on Microarchitecture (MICRO 2006)', 'prefix': '10.1109/micro.2006'},
        2007: {'ct': '40th Annual IEEE/ACM International Symposium on Microarchitecture (MICRO 2007)', 'prefix': '10.1109/micro.2007'},
        2008: {'ct': '2008 41st IEEE/ACM International Symposium on Microarchitecture', 'prefix': '10.1109/micro.2008'},
        2009: {'ct': 'Proceedings of the 42nd Annual IEEE/ACM International Symposium on Microarchitecture', 'prefix': '10.1145/1669112'},
        2010: {'ct': '2010 43rd Annual IEEE/ACM International Symposium on Microarchitecture', 'prefix': '10.1109/micro.2010'},
        2011: {'ct': 'Proceedings of the 44th Annual IEEE/ACM International Symposium on Microarchitecture', 'prefix': '10.1145/2155620'},
        2012: {'ct': '2012 45th Annual IEEE/ACM International Symposium on Microarchitecture', 'prefix': '10.1109/micro.2012'},
        2013: {'ct': 'Proceedings of the 46th Annual IEEE/ACM International Symposium on Microarchitecture', 'prefix': '10.1145/2540708'},
        2014: {'ct': '2014 47th Annual IEEE/ACM International Symposium on Microarchitecture', 'prefix': '10.1109/micro.2014'},
        2015: {'ct': 'Proceedings of the 48th International Symposium on Microarchitecture', 'prefix': '10.1145/2830772'},
    },
    'hpca': {
        2006: {'ct': 'The Twelfth International Symposium on High-Performance Computer Architecture, 2006.', 'prefix': '10.1109/hpca.2006'},
        2007: {'ct': '2007 IEEE 13th International Symposium on High Performance Computer Architecture', 'prefix': '10.1109/hpca.2007'},
        2008: {'ct': '2008 IEEE 14th International Symposium on High Performance Computer Architecture', 'prefix': '10.1109/hpca.2008'},
        2009: {'ct': '2009 IEEE 15th International Symposium on High Performance Computer Architecture', 'prefix': '10.1109/hpca.2009'},
        2010: {'ct': 'HPCA - 16 2010 The Sixteenth International Symposium on High-Performance Computer Architecture', 'prefix': '10.1109/hpca.2010'},
        2011: {'ct': '2011 IEEE 17th International Symposium on High Performance Computer Architecture', 'prefix': '10.1109/hpca.2011'},
        2012: {'ct': 'IEEE International Symposium on High-Performance Comp Architecture', 'prefix': '10.1109/hpca.2012'},
        2013: {'ct': '2013 IEEE 19th International Symposium on High Performance Computer Architecture (HPCA)', 'prefix': '10.1109/hpca.2013'},
        2014: {'ct': '2014 IEEE 20th International Symposium on High Performance Computer Architecture (HPCA)', 'prefix': '10.1109/hpca.2014'},
        2015: {'ct': '2015 IEEE 21st International Symposium on High Performance Computer Architecture (HPCA)', 'prefix': '10.1109/hpca.2015'},
    },
    'asplos': {
        2006: {'ct': 'Proceedings of the 12th international conference on Architectural support for programming languages and operating systems', 'prefix': '10.1145/1168857'},
        2008: {'ct': 'Proceedings of the 13th international conference on Architectural support for programming languages and operating systems', 'prefix': '10.1145/1346281'},
        2009: {'ct': 'Proceedings of the 14th international conference on Architectural support for programming languages and operating systems', 'prefix': '10.1145/1508244'},
        2010: {'ct': 'Proceedings of the fifteenth International Conference on Architectural support for programming languages and operating systems', 'prefix': '10.1145/1736020'},
        2011: {'ct': 'Proceedings of the sixteenth international conference on Architectural support for programming languages and operating systems', 'prefix': '10.1145/1950365'},
        2012: {'ct': 'Proceedings of the seventeenth international conference on Architectural support for programming languages and operating systems', 'prefix': '10.1145/2150976'},
        2013: {'ct': 'Proceedings of the eighteenth international conference on Architectural support for programming languages and operating systems', 'prefix': '10.1145/2451116'},
        2014: {'ct': 'Proceedings of the 19th international conference on Architectural support for programming languages and operating systems', 'prefix': '10.1145/2541940'},
        2015: {'ct': 'Proceedings of the Twentieth International Conference on Architectural Support for Programming Languages and Operating Systems', 'prefix': '10.1145/2694344'},
    },
    'rtss': {
        2006: {'ct': '2006 27th IEEE International Real-Time Systems Symposium (RTSS\'06)', 'prefix': '10.1109/rtss.2006'},
        2007: {'ct': '28th IEEE International Real-Time Systems Symposium (RTSS 2007)', 'prefix': '10.1109/rtss.2007'},
        2008: {'ct': '2008 Real-Time Systems Symposium', 'prefix': '10.1109/rtss.2008'},
        2009: {'ct': '2009 30th IEEE Real-Time Systems Symposium', 'prefix': '10.1109/rtss.2009'},
        2010: {'ct': '2010 31st IEEE Real-Time Systems Symposium', 'prefix': '10.1109/rtss.2010'},
        2011: {'ct': '2011 IEEE 32nd Real-Time Systems Symposium', 'prefix': '10.1109/rtss.2011'},
        2012: {'ct': '2012 IEEE 33rd Real-Time Systems Symposium', 'prefix': '10.1109/rtss.2012'},
        2013: {'ct': '2013 IEEE 34th Real-Time Systems Symposium', 'prefix': '10.1109/rtss.2013'},
        2014: {'ct': '2014 IEEE Real-Time Systems Symposium', 'prefix': '10.1109/rtss.2014'},
        2015: {'ct': '2015 IEEE Real-Time Systems Symposium', 'prefix': '10.1109/rtss.2015'},
    },
    'rtas': {
        2006: {'ct': '12th IEEE Real-Time and Embedded Technology and Applications Symposium (RTAS\'06)', 'prefix': '10.1109/rtas.2006'},
        2007: {'ct': '13th IEEE Real Time and Embedded Technology and Applications Symposium (RTAS\'07)', 'prefix': '10.1109/rtas.2007'},
        2008: {'ct': '2008 IEEE Real-Time and Embedded Technology and Applications Symposium', 'prefix': '10.1109/rtas.2008'},
        2009: {'ct': '2009 15th IEEE Real-Time and Embedded Technology and Applications Symposium', 'prefix': '10.1109/rtas.2009'},
        2010: {'ct': '2010 16th IEEE Real-Time and Embedded Technology and Applications Symposium', 'prefix': '10.1109/rtas.2010'},
        2011: {'ct': '2011 17th IEEE Real-Time and Embedded Technology and Applications Symposium', 'prefix': '10.1109/rtas.2011'},
        2012: {'ct': '2012 IEEE 18th Real Time and Embedded Technology and Applications Symposium', 'prefix': '10.1109/rtas.2012'},
        2013: {'ct': '2013 IEEE 19th Real-Time and Embedded Technology and Applications Symposium (RTAS)', 'prefix': '10.1109/rtas.2013'},
        2014: {'ct': '2014 IEEE 19th Real-Time and Embedded Technology and Applications Symposium (RTAS)', 'prefix': '10.1109/rtas.2014'},
        2015: {'ct': '21st IEEE Real-Time and Embedded Technology and Applications Symposium', 'prefix': '10.1109/rtas.2015'},
    },
    'emsoft': {
        2006: {'ct': 'Proceedings of the 6th ACM & IEEE international conference on Embedded software  - EMSOFT \'06', 'prefix': '10.1145/1176887'},
        2007: {'ct': 'Proceedings of the 7th ACM & IEEE international conference on Embedded software  - EMSOFT \'07', 'prefix': '10.1145/1289927'},
        2008: {'ct': 'Proceedings of the 8th ACM international conference on Embedded software', 'prefix': '10.1145/1450058'},
        2009: {'ct': 'Proceedings of the seventh ACM international conference on Embedded software', 'prefix': '10.1145/1629335'},
        2010: {'ct': 'Proceedings of the tenth ACM international conference on Embedded software', 'prefix': '10.1145/1879021'},
        2011: {'ct': 'Proceedings of the ninth ACM international conference on Embedded software', 'prefix': '10.1145/2038642'},
        2012: {'ct': 'Proceedings of the tenth ACM international conference on Embedded software', 'prefix': '10.1145/2380356'},
        2013: {'ct': '2013 Proceedings of the International Conference on Embedded Software (EMSOFT)', 'prefix': '10.1109/emsoft.2013'},
        2014: {'ct': 'Proceedings of the 14th International Conference on Embedded Software', 'prefix': '10.1145/2656045'},
        2015: {'ct': '2015 International Conference on Embedded Software (EMSOFT)', 'prefix': '10.1109/emsoft.2015'},
    },
    'iccad': {
        2006: {'ct': '2006 IEEE/ACM International Conference on Computer Aided Design', 'prefix': '10.1109/iccad.2006'},
        2007: {'ct': '2007 IEEE/ACM International Conference on Computer-Aided Design', 'prefix': '10.1109/iccad.2007'},
        2008: {'ct': '2008 IEEE/ACM International Conference on Computer-Aided Design', 'prefix': '10.1109/iccad.2008'},
        2009: {'ct': 'Proceedings of the 2009 International Conference on Computer-Aided Design', 'prefix': '10.1145/1687399'},
        2010: {'ct': '2010 IEEE/ACM International Conference on Computer-Aided Design (ICCAD)', 'prefix': '10.1109/iccad.2010'},
        2011: {'ct': '2011 IEEE/ACM International Conference on Computer-Aided Design (ICCAD)', 'prefix': '10.1109/iccad.2011'},
        2012: {'ct': 'Proceedings of the International Conference on Computer-Aided Design', 'prefix': '10.1145/2429384'},
        2013: {'ct': '2013 IEEE/ACM International Conference on Computer-Aided Design (ICCAD)', 'prefix': '10.1109/iccad.2013'},
        2014: {'ct': '2014 IEEE/ACM International Conference on Computer-Aided Design (ICCAD)', 'prefix': '10.1109/iccad.2014'},
        2015: {'ct': '2015 IEEE/ACM International Conference on Computer-Aided Design (ICCAD)', 'prefix': '10.1109/iccad.2015'},
    }
}


def author_slug(given, family):
    name = f"{given or ''} {family or ''}".strip()
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return slug or "unknown"


def clean_text(s):
    return html.unescape(s or "").strip()


def api_get_crossref(params, retries=5):
    params = dict(params)
    params["mailto"] = MAILTO
    qs = urllib.parse.urlencode(params)
    url = f"https://api.crossref.org/works?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": f"ecerankings-prep (mailto:{MAILTO})"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt + 0.5)


def api_get_openalex(params, retries=5):
    params = dict(params)
    params["mailto"] = MAILTO
    qs = urllib.parse.urlencode(params, safe=":,|*!")
    url = f"https://api.openalex.org/works?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": f"ecerankings-prep (mailto:{MAILTO})"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt + 0.5)


def fetch_edition_crossref(container_title, prefix, year):
    prefix_base = prefix.split("/")[0]
    works = []
    seen_dois = set()
    offset = 0
    rows = 200
    while offset <= 400:
        params = {
            "query.container-title": container_title,
            "filter": f"prefix:{prefix_base},type:proceedings-article",
            "rows": rows,
            "offset": offset,
        }
        data = api_get_crossref(params)
        items = data.get("message", {}).get("items", [])
        new_matches = 0
        for it in items:
            doi = (it.get("DOI") or "").lower()
            if not doi.startswith(prefix.lower()):
                continue
            if doi in seen_dois:
                continue
            seen_dois.add(doi)
            new_matches += 1
            authorships = []
            for a in it.get("author", []):
                raw = [clean_text(aff.get("name")) for aff in a.get("affiliation", []) if aff.get("name")]
                given = a.get("given") or ""
                family = a.get("family") or ""
                full_name = clean_text(f"{given} {family}".strip())
                slug = author_slug(given, family)
                authorships.append({
                    "author_id": f"crossref:name:{slug}",
                    "author_name": full_name or None,
                    "institutions": [],
                    "raw_affiliations": raw,
                })
            titles = it.get("title") or []
            title = clean_text(titles[0]) if titles else None
            issued = (it.get("issued") or {}).get("date-parts") or [[None]]
            issued_year = issued[0][0] if issued and issued[0] else None
            works.append({
                "id": None,
                "doi": f"https://doi.org/{doi}",
                "title": title,
                "publication_year": year,
                "crossref_issued_year": issued_year,
                "type": it.get("type"),
                "source": "crossref",
                "authorships": authorships,
            })
        offset += len(items)
        if not items or len(items) < rows or new_matches == 0:
            break
        time.sleep(0.3)
    return works


def hydrate_with_openalex(works):
    dois = [w["doi"].replace("https://doi.org/", "").lower() for w in works if w.get("doi")]
    by_doi = {w["doi"].replace("https://doi.org/", "").lower(): w for w in works if w.get("doi")}
    for i in range(0, len(dois), 50):
        chunk = dois[i:i+50]
        filt = "doi:" + "|".join(chunk)
        data = api_get_openalex({
            "filter": filt,
            "select": "id,doi,authorships",
            "per-page": 50,
        })
        for r in data.get("results", []):
            d = (r.get("doi") or "").replace("https://doi.org/", "").lower()
            target = by_doi.get(d)
            if not target:
                continue
            target["id"] = r.get("id")
            oa_authorships = []
            for a in r.get("authorships", []):
                insts = [{
                    "id": inst.get("id"),
                    "display_name": inst.get("display_name"),
                    "country_code": inst.get("country_code"),
                    "type": inst.get("type"),
                    "lineage": inst.get("lineage"),
                } for inst in a.get("institutions", [])]
                oa_authorships.append({
                    "author_id": a.get("author", {}).get("id"),
                    "author_name": a.get("author", {}).get("display_name"),
                    "institutions": insts,
                    "raw_affiliations": a.get("raw_affiliation_strings") or [],
                })
            if oa_authorships:
                target["authorships"] = oa_authorships
        time.sleep(0.1)


def harvest_all(venue_filter=None):
    for venue_key, years_cfg in sorted(PROCEEDINGS_CONFIG.items()):
        if venue_filter and venue_key != venue_filter:
            continue
        for year, cfg in sorted(years_cfg.items()):
            year_dir = os.path.join(CACHE_DIR, venue_key, str(year))
            out_file = os.path.join(year_dir, "works.jsonl")
            checkpoint = os.path.join(year_dir, ".checkpoint")
            if os.path.exists(out_file) and os.path.getsize(out_file) > 100:
                print(f"  [{venue_key}/{year}] Cache exists, skipping.")
                continue
            print(f"[{venue_key}/{year}] Fetching from Crossref (ct={cfg['ct'][:35]}... pref={cfg['prefix']})...", flush=True)
            works = fetch_edition_crossref(cfg["ct"], cfg["prefix"], year)
            print(f"  [{venue_key}/{year}] Fetched {len(works)} works from Crossref. Hydrating via OpenAlex...", flush=True)
            hydrate_with_openalex(works)
            os.makedirs(year_dir, exist_ok=True)
            with open(out_file, "w") as fh:
                for w in works:
                    fh.write(json.dumps(w) + "\n")
            with open(checkpoint, "w") as fh:
                json.dump({"done": True, "count": len(works)}, fh)
            hydrated_count = sum(1 for w in works if any(a.get("institutions") for a in w.get("authorships", [])))
            print(f"  [{venue_key}/{year}] Saved {len(works)} works ({hydrated_count} hydrated with institutions) to {out_file}", flush=True)
            time.sleep(0.3)


if __name__ == "__main__":
    vfilter = sys.argv[1] if len(sys.argv) > 1 else None
    harvest_all(vfilter)
