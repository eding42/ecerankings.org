#!/usr/bin/env python3
"""Re-fetch full bylines for works in cache_biosciences that hit OpenAlex's 100-author list limit.
"""

import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache_biosciences")
REQ_HEADERS = {"User-Agent": "BiologyRankingsBylinesFixer/1.0 (mailto:eding2019@gmail.com)"}


def refetch_work(work_id):
    short_id = work_id.split("/")[-1]
    url = f"https://api.openalex.org/works/{short_id}"
    req = urllib.request.Request(url, headers=REQ_HEADERS)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("authorships", [])
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(1.0 * (attempt + 1))
            else:
                print(f"  HTTPError {e.code} for {work_id}")
                return None
        except Exception as e:
            time.sleep(1.0 * (attempt + 1))
    return None


def main():
    jsonl_files = sorted(glob.glob(os.path.join(CACHE_DIR, "*", "*", "works.jsonl")))
    print(f"Scanning {len(jsonl_files)} files in {CACHE_DIR}...")

    total_capped = 0
    fixed_count = 0

    for fpath in jsonl_files:
        needs_write = False
        updated_lines = []
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                w = json.loads(line)
                auths = w.get("authorships", [])
                if len(auths) == 100:
                    total_capped += 1
                    wid = w["id"]
                    full_auths = refetch_work(wid)
                    if full_auths and len(full_auths) > 100:
                        w["authorships"] = full_auths
                        needs_write = True
                        fixed_count += 1
                        print(f"[{fixed_count}] Fixed {wid.split('/')[-1]}: 100 -> {len(full_auths)} authors ({w.get('title', '')[:50]})")
                    elif full_auths and len(full_auths) == 100:
                        # Genuinely exactly 100 authors
                        pass
                    time.sleep(0.05)
                updated_lines.append(json.dumps(w) + "\n")

        if needs_write:
            with open(fpath, "w", encoding="utf-8") as f:
                f.writelines(updated_lines)

    print(f"\nDone! Scanned {total_capped} capped works, successfully expanded bylines for {fixed_count} works.")


if __name__ == "__main__":
    main()
