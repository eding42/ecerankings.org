#!/usr/bin/env python3
"""Semantic affiliation normalizer using sentence-transformers.

Replaces the heuristic string-matching normalizer with a transformer-based
semantic matcher. Embeds all institution names via sentence-transformers,
encodes each affiliation candidate, and finds the closest institution by
cosine similarity. GPU-accelerated via MPS (Mac) or CUDA if available.

Usage:
    /path/to/venv/bin/python pipeline/normalize_semantic.py --all-cached
    /path/to/venv/bin/python pipeline/normalize_semantic.py --venue iedm
    /path/to/venv/bin/python pipeline/normalize_semantic.py --all-cached --batch 2048 --workers 4
"""
import argparse
import csv
import html
import json
import os
import re
import sys
import time
import numpy as np
import torch
from sentence_transformers import SentenceTransformer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
MAP_CSV = os.path.join(REPO_ROOT, "data", "affiliation-map.csv")
INST_DB = os.path.join(REPO_ROOT, "data", "institutions.json")

MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_BATCH = 32768
AUTO_THRESHOLD = 0.85
MIN_THRESHOLD = 0.70

MAP_FIELDS = [
    "raw_affiliation", "status", "institution_id", "institution_name",
    "institution_type", "country_code", "lineage", "score", "matched_via", "candidate",
]

# ── candidate extraction (same as the local normalizer) ──

STOP_SEGMENTS = {
    "inc", "inc.", "ltd", "ltd.", "co", "co.", "corp", "corp.", "corporation",
    "llc", "l.l.c.", "gmbh", "plc", "pvt", "pvt.", "pte", "pte.", "sa", "s.a.",
    "nv", "n.v.", "bv", "b.v.", "ag", "kk", "k.k.", "srl", "s.r.l.", "spa",
    "s.p.a.", "ab", "oy", "as", "a/s", "limited", "company", "the",
}

COUNTRIES = {
    "usa", "u.s.a.", "us", "u.s.", "united states", "united states of america",
    "uk", "u.k.", "united kingdom", "england", "scotland", "wales", "china",
    "p.r. china", "pr china", "people's republic of china", "japan", "korea",
    "south korea", "republic of korea", "north korea", "france", "germany",
    "italy", "spain", "belgium", "netherlands", "the netherlands", "switzerland",
    "sweden", "norway", "denmark", "finland", "austria", "poland", "portugal",
    "ireland", "greece", "russia", "india", "singapore", "taiwan", "r.o.c.",
    "taiwan, r.o.c.", "hong kong", "macau", "australia", "new zealand", "canada",
    "mexico", "brazil", "israel", "turkey", "egypt", "south africa", "thailand",
    "vietnam", "malaysia", "indonesia", "philippines", "saudi arabia", "uae",
}

US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy",
}

POSTAL_RE = re.compile(r"^[\d][\d\s\-]*$|^[A-Z]{1,2}\d{1,2}[A-Z]?\s*\d?[A-Z]{0,2}$")
PAREN_RE = re.compile(r"\(([^)]*)\)")
CORP_SUFFIX_RE = re.compile(
    r"\b(inc|ltd|co|corp|corporation|llc|gmbh|plc|pvt|pte|s\.?a|n\.?v|b\.?v|ag|k\.?k|s\.?r\.?l|s\.?p\.?a|limited)\b\.?,?\s*$",
    re.I,
)
DEPT_RE = re.compile(
    r"\b(school|department|dept\.?|faculty|division|graduate institute|"
    r"laborator(y|ies)|lab\b|research group|group|centre|center|"
    r"state key lab|college of|institute of \w+ (engineering|technolog))",
    re.I,
)


def build_candidates(raw):
    """Split a raw affiliation string into searchable candidate names."""
    s = html.unescape(raw or "").strip()
    if not s:
        return []

    acronyms = []
    for p in PAREN_RE.findall(s):
        p = p.strip()
        if len(p) >= 2 and p.lower() not in STOP_SEGMENTS and not POSTAL_RE.match(p):
            acronyms.append(p)

    def usable(p):
        p = re.sub(r"\s+", " ", p).strip(" .;-")
        if not p or len(p) < 4:
            return None
        low = p.lower().strip(" .")
        if low in STOP_SEGMENTS or low in COUNTRIES or low in US_STATES:
            return None
        if POSTAL_RE.match(p):
            return None
        stripped = CORP_SUFFIX_RE.sub("", p).strip(" .,;-")
        if len(stripped) >= 4:
            p = stripped
        if p.lower() in STOP_SEGMENTS or len(p) < 4:
            return None
        return p

    depunct = PAREN_RE.sub(" ", s)
    whole, split = [], []
    for seg in depunct.split(","):
        u = usable(seg)
        if u:
            whole.append(u)
        for piece in re.split(r"\band\b|&", seg):
            v = usable(piece)
            if v and v.lower() != (u or "").lower():
                split.append(v)

    # Re-join adjacent segments: "University of California, Irvine, USA"
    joined = []
    for i in range(len(whole) - 1):
        joined.append(f"{whole[i]}, {whole[i + 1]}")
        if i + 2 < len(whole):
            joined.append(f"{whole[i]}, {whole[i + 1]}, {whole[i + 2]}")

    def rank(group):
        return sorted(group, key=lambda x: (bool(DEPT_RE.search(x)), -len(x)))

    seen = set()
    ordered = []
    for c in acronyms + rank(joined) + rank(whole) + rank(split):
        if c.lower() not in seen:
            seen.add(c.lower())
            ordered.append(c)
    return ordered[:8]


# ── load / save ──

def load_inst_db():
    if not os.path.exists(INST_DB):
        print(f"Missing {INST_DB}. Build it first with .tmp/build_inst_db.py", file=sys.stderr)
        sys.exit(1)
    with open(INST_DB) as f:
        return json.load(f)


def load_map():
    rows = {}
    if os.path.exists(MAP_CSV):
        with open(MAP_CSV, newline="") as f:
            for r in csv.DictReader(f):
                rows[r["raw_affiliation"]] = r
    return rows


def save_map(rows):
    os.makedirs(os.path.dirname(MAP_CSV), exist_ok=True)
    with open(MAP_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MAP_FIELDS)
        w.writeheader()
        for raw in sorted(rows):
            row = {k: rows[raw].get(k, "") for k in MAP_FIELDS}
            w.writerow(row)


# ── collect ──

def find_cached_years(venue_key):
    venue_dir = os.path.join(CACHE_DIR, venue_key)
    if not os.path.isdir(venue_dir):
        return []
    return sorted(
        int(e) for e in os.listdir(venue_dir)
        if e.isdigit() and os.path.exists(os.path.join(venue_dir, e, "works.jsonl"))
    )


def collect_raw_affiliations(venue_key, year=None):
    strings = {}
    for y in find_cached_years(venue_key):
        if year is not None and y != year:
            continue
        path = os.path.join(CACHE_DIR, venue_key, str(y), "works.jsonl")
        with open(path) as f:
            for line in f:
                w = json.loads(line)
                for a in w.get("authorships", []):
                    for s in a.get("raw_affiliations", []) or []:
                        strings[s] = strings.get(s, 0) + 1
    return strings


# ── semantic resolver ──

def build_inst_index(db, model, device):
    """Build embedding index: one embedding per institution variant name.

    Also marks each variant text as *ambiguous* when the identical text
    belongs to 2+ institutions (acronym collisions like "MIT"/"KTH"/"CNRS",
    or shared alternative names). An exact hit on such a variant carries no
    information about WHICH owner is meant, so resolve_batch never
    auto-accepts a match won through one (bug class found 2026-07-24: MIT ->
    Manukau Institute of Technology, KTH -> Khyber Teaching Hospital, ...).
    """
    texts = []
    variant_to_inst = {}  # index_in_texts -> inst_id
    name_used = {}         # inst_id -> resolved display_name
    owners_by_text = {}    # variant text -> set of inst_ids

    for inst_id, inst in db["by_id"].items():
        display = inst["display_name"]
        if not display:
            continue
        variants = {display}
        for alt in (inst.get("alternatives") or []):
            if alt and alt.strip():
                variants.add(alt.strip())
        for acr in (inst.get("acronyms") or []):
            if acr and acr.strip():
                variants.add(acr.strip())

        for v in variants:
            v = v.lower().strip()
            if len(v) < 3:
                continue
            texts.append(v)
            variant_to_inst[len(texts) - 1] = inst_id
            owners_by_text.setdefault(v, set()).add(inst_id)
            if inst_id not in name_used:
                name_used[inst_id] = display

    ambiguous = [len(owners_by_text[texts[i]]) > 1 for i in range(len(texts))]
    n_amb = sum(1 for t, o in owners_by_text.items() if len(o) > 1)
    print(f"Encoding {len(texts)} institution name variants on {device} "
          f"({n_amb} ambiguous variant texts shared by 2+ institutions)...")
    t0 = time.time()
    inst_batch = 512 if device in ("mps", "cuda") else 64
    embeddings = model.encode(texts, normalize_embeddings=True,
                               batch_size=inst_batch, show_progress_bar=True,
                               device=device)
    print(f"  done in {time.time() - t0:.1f}s — matrix shape {embeddings.shape}")
    return (torch.tensor(embeddings, dtype=torch.float32, device=device),
            [variant_to_inst[i] for i in range(len(texts))],
            name_used,
            ambiguous)


def resolve_batch(raw_strings, inst_embeddings, inst_ids, name_used, model,
                  auto_threshold, min_threshold, variant_ambiguous=None):
    """Resolve a batch of raw affiliation strings. Returns list of map rows.

    A match is only eligible for status=auto when it is *safe*: the winning
    institution variant is owned by a single institution AND the candidate
    substring is not a generic department/school phrase (DEPT_RE). Unsafe
    wins (ambiguous acronyms, department-name cosine matches) are capped at
    status=review so a human/LLM adjudicates instead of silently
    misattributing (see fix_acronym_collisions.py / fix_name_mismatches.py
    for the historical cleanup of exactly these two bug classes).
    """
    # Step 1: extract candidates for every string
    all_candidates = []      # flat list of candidate texts
    string_boundaries = []    # (start, end) in all_candidates for each raw string
    for raw in raw_strings:
        cands = build_candidates(raw)
        if not cands:
            cands = [raw]  # fallback: use raw string
        string_boundaries.append((len(all_candidates), len(all_candidates) + len(cands)))
        all_candidates.extend(cands)

    if not all_candidates:
        return []
    # Step 2: encode all candidates at once (batch on GPU)
    cand_batch = 512 if inst_embeddings.device.type in ("mps", "cuda") else 64
    cand_embs = model.encode(all_candidates, normalize_embeddings=True,
                              batch_size=cand_batch, show_progress_bar=False,
                              device=inst_embeddings.device)

    cand_embs = torch.tensor(cand_embs, dtype=torch.float32, device=inst_embeddings.device)

    # Step 3: compute all similarities at once (candidate × institution)
    # Split into chunks to avoid OOM on the (N_cands, N_insts) matrix
    chunk = 4096
    results = []
    for ci in range(0, cand_embs.shape[0], chunk):
        c_end = min(ci + chunk, cand_embs.shape[0])
        batch = cand_embs[ci:c_end]
        sims = torch.mm(batch, inst_embeddings.T)  # (chunk, N_insts)
        best_vals, best_idxs = torch.max(sims, dim=1)

        for j in range(batch.shape[0]):
            score = best_vals[j].item()
            v_idx = best_idxs[j].item()
            inst_id = inst_ids[v_idx]
            candidate = all_candidates[ci + j]
            unsafe = bool(variant_ambiguous and variant_ambiguous[v_idx]) or \
                bool(DEPT_RE.search(candidate))
            results.append((score, inst_id, candidate, unsafe))

    # Step 4: for each raw string, pick the best candidate match.
    # Prefer the best SAFE match for auto-acceptance; an unsafe overall best
    # (ambiguous variant / department phrase) can never exceed status=review.
    rows = []
    for i, raw in enumerate(raw_strings):
        start, end = string_boundaries[i]
        best = (0.0, None, None, True)
        best_safe = (0.0, None, None, False)
        for j in range(start, end):
            score, inst_id, candidate, unsafe = results[j]
            if score > best[0]:
                best = (score, inst_id, candidate, unsafe)
            if not unsafe and score > best_safe[0]:
                best_safe = (score, inst_id, candidate, unsafe)

        if best_safe[1] and best_safe[0] >= auto_threshold:
            score, inst_id, candidate, _ = best_safe
            status = "auto"
        else:
            score, inst_id, candidate, unsafe = best
            if inst_id and score >= min_threshold:
                status = "review"
            else:
                status = "unmatched"
                inst_id = None

        row = {
            "raw_affiliation": raw,
            "status": status,
            "institution_id": inst_id or "",
            "institution_name": name_used.get(inst_id, "") if inst_id else "",
            "institution_type": "",
            "country_code": "",
            "lineage": "",
            "score": f"{score:.3f}",
            "matched_via": candidate or "",
            "candidate": candidate or "",
        }
        rows.append(row)

    return rows


def enrich_rows(rows, db):
    """Fill institution_type, country_code, lineage from the local DB."""
    for row in rows:
        inst_id = row["institution_id"]
        if inst_id and row["status"] in ("auto", "review"):
            inst = db["by_id"].get(inst_id)
            if inst:
                row["institution_type"] = inst.get("type") or ""
                row["country_code"] = inst.get("country_code") or ""
                row["lineage"] = "|".join(inst.get("lineage", []) or [])
            else:
                # No DB record — still matched by name, can't classify type.
                row["institution_type"] = ""
        else:
            row["institution_id"] = ""
    return rows


# ── main ──

def main():
    parser = argparse.ArgumentParser(description="Semantic affiliation normalizer (sentence-transformers)")
    parser.add_argument("--venue", action="append", default=[], help="Venue key (repeatable)")
    parser.add_argument("--all-cached", action="store_true", help="Every venue with cached works")
    parser.add_argument("--year", type=int, default=None, help="Restrict to one year")
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH,
                        help=f"Number of raw strings to resolve per batch (default {DEFAULT_BATCH})")
    parser.add_argument("--report-only", action="store_true", help="Don't resolve; just report map coverage")
    parser.add_argument("--verbose", action="store_true", help="Print each resolution")
    args = parser.parse_args()

    # ── venues ──
    venues = args.venue
    if args.all_cached:
        if os.path.isdir(CACHE_DIR):
            venues = sorted(d for d in os.listdir(CACHE_DIR) if os.path.isdir(os.path.join(CACHE_DIR, d)))
    if not venues:
        print("Specify --venue <key> or --all-cached", file=sys.stderr)
        sys.exit(1)

    # ── device ──
    device = "cpu"
    if torch.backends.mps.is_available():
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"
    print(f"Device: {device}")

    # ── model ──
    print(f"Loading model '{MODEL_NAME}' ...")
    model = SentenceTransformer(MODEL_NAME, device=device)

    # ── institution DB ──
    print(f"Loading institution DB from {INST_DB} ...")
    db = load_inst_db()
    inst_embeddings, inst_ids, name_used, variant_ambiguous = build_inst_index(db, model, device)

    # ── collect raw affiliation strings ──
    print("Collecting distinct affiliation strings from cache ...")
    all_strings = {}
    for v in venues:
        for s, n in collect_raw_affiliations(v, args.year).items():
            all_strings[s] = all_strings.get(s, 0) + n
    total_occurrences = sum(all_strings.values())
    print(f"  {len(all_strings)} distinct strings, {total_occurrences} total occurrences")

    # ── load existing map ──
    mapping = load_map()
    todo = [(s, c) for s, c in all_strings.items() if s not in mapping]
    print(f"  {len(mapping)} already mapped, {len(todo)} to resolve")

    if args.report_only:
        todo = []
    if not todo:
        print("Nothing to do.")
        return

    # ── resolve in batches ──
    batch_size = args.batch
    print(f"Resolving {len(todo)} strings in batches of {batch_size} ...")
    resolved = 0
    t_start = time.time()

    # Sort by descending frequency so the most common strings resolve first
    todo.sort(key=lambda x: -x[1])
    todo_keys = [(k, c) for k, c in todo]  # keep order for reporting

    for bi in range(0, len(todo_keys), batch_size):
        be = min(bi + batch_size, len(todo_keys))
        batch_strings = [k for k, c in todo_keys[bi:be]]

        rows = resolve_batch(batch_strings, inst_embeddings, inst_ids, name_used,
                             model, AUTO_THRESHOLD, MIN_THRESHOLD,
                             variant_ambiguous=variant_ambiguous)
        rows = enrich_rows(rows, db)

        for row in rows:
            mapping[row["raw_affiliation"]] = row

        resolved += len(batch_strings)
        elapsed = time.time() - t_start
        rate = resolved / max(elapsed, 0.01)
        eta = (len(todo_keys) - resolved) / max(rate, 0.01)
        print(f"  resolved {resolved}/{len(todo_keys)} ({rate:.0f}/s) — ETA {eta:.0f}s ...")
        save_map(mapping)

    save_map(mapping)
    print(f"\nMap written to {MAP_CSV} ({time.time() - t_start:.1f}s total)")

    # ── coverage report ──
    by_status = {}
    weighted = {}
    edu_strings = 0
    edu_occurrences = 0
    for s, count in all_strings.items():
        row = mapping.get(s)
        st = row["status"] if row else "unmapped"
        by_status[st] = by_status.get(st, 0) + 1
        weighted[st] = weighted.get(st, 0) + count
        if row and row["status"] in ("auto", "manual") and row.get("institution_type") == "education":
            edu_strings += 1
            edu_occurrences += count

    print(f"{'status':<12}{'distinct':>10}{'occurrences':>14}{'% of occurrences':>18}")
    for st in ("auto", "manual", "review", "unmatched", "unmapped"):
        if st in by_status:
            print(f"{st:<12}{by_status[st]:>10}{weighted[st]:>14}{100 * weighted[st] / max(total_occurrences, 1):>17.1f}%")
    print(f"\nCredited (auto+manual, type=education): {edu_strings} distinct, "
          f"{edu_occurrences} occurrences ({100 * edu_occurrences / max(total_occurrences, 1):.1f}%)")
    if by_status.get("review"):
        print(f"\n{by_status['review']} string(s) need human review (score {MIN_THRESHOLD}-{AUTO_THRESHOLD}). "
              f"Edit {os.path.relpath(MAP_CSV, REPO_ROOT)} and set status=manual.")


if __name__ == "__main__":
    main()
