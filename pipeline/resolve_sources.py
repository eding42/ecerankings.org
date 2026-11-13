#!/usr/bin/env python3
import urllib.request
import json
import time

venues = [
    ("nat-cell-bio", "Nature Cell Biology", "1465-7392"),
    ("embo-j", "The EMBO Journal", "0261-4189"),
    ("jcb", "Journal of Cell Biology", "0021-9525"),
    ("dev-cell", "Developmental Cell", "1534-5807"),
    ("mol-cell", "Molecular Cell", "1097-2765"),
    ("nsmb", "Nature Structural & Molecular Biology", "1545-9993"),
    ("nar", "Nucleic Acids Research", "0305-1048"),
    ("structure", "Structure", "0969-2126"),
    ("cell-metab", "Cell Metabolism", "1550-4131"),
    ("nat-metab", "Nature Metabolism", "2522-5812"),
    ("nat-genetics", "Nature Genetics", "1061-4036"),
    ("genome-res", "Genome Research", "1088-9051"),
    ("genome-bio", "Genome Biology", "1474-760X"),
    ("neuron", "Neuron", "0896-6273"),
    ("nat-neurosci", "Nature Neuroscience", "1097-6256"),
    ("immunity", "Immunity", "1074-7613"),
    ("nat-immunol", "Nature Immunology", "1529-2908"),
    ("sci-immunol", "Science Immunology", "2470-9468"),
    ("jem", "Journal of Experimental Medicine", "0022-1007"),
    ("cell-host-microbe", "Cell Host & Microbe", "1931-3128"),
    ("nat-microbiol", "Nature Microbiology", "2058-5276"),
    ("nat-ecol-evol", "Nature Ecology & Evolution", "2397-334X"),
    ("plant-cell", "The Plant Cell", "1040-4651"),
    ("nat-plants", "Nature Plants", "2055-0278"),
    ("bioinformatics", "Bioinformatics", "1367-4803"),
    ("plos-comp-bio", "PLOS Computational Biology", "1553-7358"),
    ("cell-systems", "Cell Systems", "2405-4712"),
    ("nat-biotech", "Nature Biotechnology", "1087-0156"),
    ("nat-biomed-eng", "Nature Biomedical Engineering", "2157-846X"),
    ("cancer-cell", "Cancer Cell", "1535-6108"),
    ("sci-transl-med", "Science Translational Medicine", "1946-6234"),
    ("jci", "The Journal of Clinical Investigation", "0021-9738")
]

req_headers = {"User-Agent": "ECERankingsHarvester/1.0 (mailto:eding2019@gmail.com)"}

results = {}
for key, name, issn in venues:
    url = f"https://api.openalex.org/sources?filter=issn:{issn}"
    try:
        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("results"):
                src = data["results"][0]
                oid = src["id"].split("/")[-1]
                results[key] = {
                    "key": key,
                    "display": src["display_name"],
                    "openalex_id": oid,
                    "issn_l": src.get("issn_l") or issn,
                    "works_count": src.get("works_count"),
                    "2yr_citedness": src.get("summary_stats", {}).get("2yr_mean_citedness")
                }
                print(f"OK: {key:18} -> {oid:12} | {src['display_name']}")
            else:
                # Try search by name
                search_url = f"https://api.openalex.org/sources?search={urllib.parse.quote(name)}"
                req2 = urllib.request.Request(search_url, headers=req_headers)
                with urllib.request.urlopen(req2) as resp2:
                    data2 = json.loads(resp2.read().decode("utf-8"))
                    if data2.get("results"):
                        src = data2["results"][0]
                        oid = src["id"].split("/")[-1]
                        results[key] = {
                            "key": key,
                            "display": src["display_name"],
                            "openalex_id": oid,
                            "issn_l": src.get("issn_l") or issn,
                            "works_count": src.get("works_count"),
                            "2yr_citedness": src.get("summary_stats", {}).get("2yr_mean_citedness")
                        }
                        print(f"OK (via search): {key:18} -> {oid:12} | {src['display_name']}")
                    else:
                        print(f"FAILED: {key} ({name})")
        time.sleep(0.1)
    except Exception as e:
        print(f"ERR {key}: {e}")

with open("data/core_bio_sources.json", "w") as f:
    json.dump(results, f, indent=2)
print("Saved to data/core_bio_sources.json. Total resolved:", len(results))
