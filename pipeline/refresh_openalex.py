#!/usr/bin/env python3
"""Safely refresh OpenAlex journal works into an isolated cache.

Each venue/year is published only after pagination, counts, author completeness,
and the staged file have been validated. Interrupted years resume from a local
checkpoint. API keys are sent only in the Authorization header.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
if __package__:
    from .workkey import norm_doi
else:
    from workkey import norm_doi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, "data", "areas.json")
AUDIT = os.path.join(ROOT, "data", "refresh", "journals-2026-10-28.json")
ENV = os.path.join(ROOT, ".env")
API = "https://api.openalex.org"
PER_PAGE = 200
HYDRATION_WORKERS = 4


class RefreshError(RuntimeError):
    pass


class RequestBudget(RefreshError):
    pass


class PermanentRemoteError(RefreshError):
    pass


class NetworkUnavailable(RefreshError):
    pass


@contextmanager
def exclusive_run_lock(out_cache, manifest_path):
    """Reject concurrent writers sharing either the cache or its manifest."""
    paths = {os.path.join(os.path.realpath(out_cache), '.refresh.lock'),
             os.path.realpath(manifest_path) + '.lock'}
    with ExitStack() as stack:
        for path in sorted(paths):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            handle = stack.enter_context(open(path, 'a+'))
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RefreshError('Another journal refresh owns this cache or manifest') from None
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()) + '\n')
            handle.flush()
        yield


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_env():
    env = {}
    if os.path.isfile(ENV):
        with open(ENV, encoding="utf8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("\"'")
    return env


def get_registry():
    with open(REGISTRY, encoding="utf8") as f:
        return json.load(f)


def journals(registry):
    return [(ak, v) for ak, a in registry["areas"].items() for v in a["venues"] if v.get("kind") == "journal"]


def atomic_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def clean_id(value):
    return (value or "").rstrip("/").split("/")[-1]


def trim_work(w):
    auths = []
    for a in w.get("authorships") or []:
        author = a.get("author") or {}
        insts = []
        for i in a.get("institutions") or []:
            insts.append({k: i.get(k) for k in ("id", "display_name", "country_code", "type", "lineage")})
        auths.append({
            "author_id": author.get("id"), "author_name": author.get("display_name"),
            "institutions": insts,
            "raw_affiliations": list(a.get("raw_affiliation_strings") or []),
        })
    out = {"id": w.get("id"), "doi": w.get("doi"), "title": w.get("title"),
           "publication_year": w.get("publication_year"), "type": w.get("type"),
           "source": "openalex", "authorships": auths}
    for field in ("authors_count", "authorships_count", "is_authors_truncated"):
        if field in w:
            out[field] = w[field]
    return out


def _doi_key(doi):
    return norm_doi(doi) or ""


def identity(w):
    return "doi:" + _doi_key(w.get("doi")) if _doi_key(w.get("doi")) else "id:" + clean_id(w.get("id"))


def completeness(w):
    return (len(w.get("authorships") or []),
            sum(len(a.get("institutions") or []) + len(a.get("raw_affiliations") or []) for a in w.get("authorships") or []),
            bool(w.get("title")))


def deduplicate(works):
    chosen = {}
    for w in works:
        key = identity(w)
        old = chosen.get(key)
        # Same DOI can resolve to merged/different OpenAlex ids. Prefer the
        # record with the richest author affiliation payload; lexical id breaks ties.
        rank = (completeness(w), clean_id(w.get("id")))
        if old is None or rank > (completeness(old), clean_id(old.get("id"))):
            chosen[key] = w
    return sorted(chosen.values(), key=lambda w: (identity(w), clean_id(w.get("id"))))


def make_client(api_key, max_requests, max_list_requests=None):
    state = {"requests": 0, "max": max_requests, "list_calls": 0,
             "max_list": max_list_requests, "singleton_calls": 0, "retries": 0}
    state_lock = threading.Lock()

    def get(path, params, retries=4):
        q = dict(params)
        url = API + path + "?" + urllib.parse.urlencode(q, safe=":,|*!")
        headers = {"User-Agent": "ecerankings-journal-refresh/1.0", "Accept": "application/json"}
        if api_key:
            headers["Authorization"] = "Bearer " + api_key
        for n in range(retries):
            with state_lock:
                if state["requests"] >= state["max"]:
                    raise RequestBudget("request budget reached")
                if path == "/works" and state["max_list"] is not None and state["list_calls"] >= state["max_list"]:
                    raise RequestBudget("list-call budget reached")
                state["requests"] += 1
                if path == "/works":
                    state["list_calls"] += 1
                else:
                    state["singleton_calls"] += 1
                if n:
                    state["retries"] += 1
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and n + 1 < retries:
                    retry_after = (e.headers or {}).get("Retry-After")
                    try:
                        delay = min(90, max(1, float(retry_after))) if retry_after else 2 ** n
                    except ValueError:
                        delay = 2 ** n
                    time.sleep(delay)
                    continue
                if e.code == 429:
                    raise RequestBudget("OpenAlex rate limit or daily request budget exhausted") from None
                if e.code < 500:
                    try:
                        body = e.read(2048).decode("utf8", "replace")
                        detail = json.loads(body).get("message", "")
                    except Exception:
                        detail = ""
                    # Never include request URLs or headers: authentication is header-only.
                    raise PermanentRemoteError(f"OpenAlex HTTP {e.code} for {path}: {detail[:240]}") from None
                raise RefreshError(f"OpenAlex HTTP {e.code} for {path}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if n + 1 < retries:
                    time.sleep(2 ** n)
                    continue
                reason = type(getattr(e, 'reason', e)).__name__
                raise NetworkUnavailable(f"OpenAlex network failure: {type(e).__name__}/{reason}; check network permissions before retrying") from None
        raise RefreshError("OpenAlex retries exhausted")
    return get, state


def source_ids_for_year(venue, year):
    entry = venue.get("years", {}).get(str(year))
    return venue.get("openalex_ids", []), entry


def source_filter(ids, year):
    return "primary_location.source.id:" + "|".join(ids) + f",publication_year:{year},type:!paratext"


def hydrate_one(w, get, journal, year):
    trunc = w.get("is_authors_truncated") is True
    count = w.get("authors_count", w.get("authorships_count"))
    current_len = len(w.get("authorships") or [])
    if not trunc and count is not None and current_len < count:
        trunc = True
    # The works schema can omit counts and truncation flags. A full 100-entry
    # byline is therefore hydrated conservatively as well.
    if current_len >= 100:
        trunc = True
    if trunc:
        work_id = clean_id(w.get("id"))
        if not work_id:
            raise RefreshError(f"truncated authorship with missing work id ({journal}/{year})")
        full = get("/works/" + urllib.parse.quote(work_id, safe=""), {})
        if clean_id(full.get("id")) != work_id:
            raise RefreshError(f"singleton hydration returned a different work for {work_id}")
        if _doi_key(w.get("doi")) != _doi_key(full.get("doi")):
            raise RefreshError(f"singleton hydration DOI mismatch for {work_id}")
        full_authorships = full.get("authorships") or []
        full_count = full.get("authors_count", full.get("authorships_count"))
        if full.get("is_authors_truncated") is True or (full_count is not None and len(full_authorships) < full_count):
            raise RefreshError(f"author affiliations remain truncated for {work_id}")
        if len(full_authorships) < current_len:
            raise RefreshError(f"singleton hydration returned a shorter byline for {work_id}")
        w = full
    trimmed = trim_work(w)
    if trunc:
        trimmed["authors_hydrated"] = True
    return trimmed


def hydrate_truncated(works, get, journal, year):
    # Preserve input order while overlapping bounded singleton lookups.
    with ThreadPoolExecutor(max_workers=HYDRATION_WORKERS) as pool:
        return list(pool.map(lambda work: hydrate_one(work, get, journal, year), works))


def rehydrate_published_file(path, get, journal, year):
    """Repair records that an earlier list-only refresh may have capped at 100."""
    with open(path, encoding="utf8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    hydrated = []
    changed = 0
    for row in rows:
        auths = row.get("authorships") or []
        count = row.get("authors_count", row.get("authorships_count"))
        needs = (row.get("authors_hydrated") is not True and
                 (row.get("is_authors_truncated") is True or
                  (count is not None and len(auths) < count) or len(auths) >= 100))
        if not needs:
            hydrated.append(row)
            continue
        work_id = clean_id(row.get("id"))
        full = get("/works/" + urllib.parse.quote(work_id, safe=""), {})
        if clean_id(full.get("id")) != work_id:
            raise RefreshError(f"singleton hydration returned a different work for {work_id}")
        if _doi_key(row.get("doi")) != _doi_key(full.get("doi")):
            raise RefreshError(f"singleton hydration DOI mismatch for {work_id}")
        fa = full.get("authorships") or []
        fc = full.get("authors_count", full.get("authorships_count"))
        if full.get("is_authors_truncated") is True or (fc is not None and len(fa) < fc) or len(fa) < len(auths):
            raise RefreshError(f"author affiliations remain incomplete for {work_id}")
        replacement = trim_work(full)
        replacement["authors_hydrated"] = True
        if row.get("provenance") is not None:
            replacement["provenance"] = row["provenance"]
        hydrated.append(replacement)
        changed += 1
    if changed:
        payload = b"".join((json.dumps(w, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf8") for w in hydrated)
        atomic_bytes(path, payload)
    return {"hydrated_count": changed, "work_ids": [clean_id(w.get("id")) for w in hydrated if w.get("authors_hydrated")]}


def read_stage(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_stage(path, values):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf8") as f:
        for val in values:
            f.write(json.dumps(val, ensure_ascii=False, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())


def harvest_year(key, venue, year, out_cache, manifest, get, state):
    ids, entry = source_ids_for_year(venue, year)
    if not ids:
        return {"venue": key, "year": year, "status": "skipped_no_openalex_source"}
    if entry and entry.get("source") not in ("openalex", "crossref"):
        return {"venue": key, "year": year, "status": "skipped_registered_other_source", "registered_source": entry.get("source")}
    filt = source_filter(ids, year)
    # OpenAlex's works endpoint rejects authors_count in `select`; requesting
    # the default work object retains authorship truncation metadata when sent.
    qparams = {"filter": filt, "per-page": PER_PAGE, "cursor": "*"}
    dest = os.path.join(out_cache, key, str(year), "works.jsonl")
    stage = dest + ".partial"
    cp = dest + ".checkpoint.json"
    request_sig = hashlib.sha256(json.dumps({"endpoint": "/works", **qparams}, sort_keys=True).encode()).hexdigest()
    checkpoint = {}
    if os.path.exists(cp):
        with open(cp, encoding="utf8") as f:
            checkpoint = json.load(f)
        if checkpoint.get("request_sha256") != request_sig:
            raise RefreshError(f"checkpoint query mismatch for {key}/{year}")
    if os.path.exists(dest) and (manifest.get("years", {}).get(key, {}).get(str(year), {}).get("status") == "complete"):
        return manifest["years"][key][str(year)]
    cursor = checkpoint.get("next_cursor", "*")
    seen = set(checkpoint.get("cursors", []))
    total_raw = int(checkpoint.get("api_results", 0))
    api_count = checkpoint.get("api_count")
    pages = int(checkpoint.get("pages", 0))
    restart_count = int(checkpoint.get("restart_count", 0))
    if os.path.exists(stage):
        # The page append precedes checkpoint replacement. If interrupted in
        # that small gap, discard bytes beyond the last committed offset.
        if "stage_bytes" in checkpoint:
            committed = int(checkpoint["stage_bytes"])
        else:
            committed = 0
            with open(stage, "rb") as f:
                for _ in range(total_raw):
                    line = f.readline()
                    if not line:
                        raise RefreshError(f"staged file is shorter than checkpoint for {key}/{year}")
                    committed += len(line)
        with open(stage, "r+b") as f:
            f.truncate(committed)
    manual_probe = bool(entry and entry.get("source") == "crossref")
    def restart_query(reason):
        nonlocal restart_count
        if restart_count >= 2:
            raise RefreshError(f"{reason}; whole-year restart limit reached for {key}/{year}")
        if os.path.exists(stage): os.unlink(stage)
        restart_count += 1
        atomic_json(cp, {"request_sha256": request_sig, "next_cursor": "*", "cursors": [],
                         "api_results": 0, "api_count": None, "pages": 0,
                         "stage_bytes": 0, "restart_count": restart_count, "updated_at": now()})
        return harvest_year(key, venue, year, out_cache, manifest, get, state)
    if manual_probe:
        # Keep the Crossref cache as the authority if the current OpenAlex source
        # unexpectedly has no works; query still detects whether a complement exists.
        pass
    while cursor:
        if cursor in seen:
            raise RefreshError(f"repeated cursor for {key}/{year}")
        seen.add(cursor)
        params = dict(qparams, cursor=cursor)
        data = get("/works", params)
        meta = data.get("meta") or {}
        this_count = meta.get("count")
        if this_count is None:
            raise RefreshError(f"missing API count for {key}/{year}")
        if api_count is None:
            api_count = this_count
        elif this_count != api_count:
            return restart_query(f"API result count changed during pagination ({api_count} -> {this_count})")
        results = data.get("results")
        if not isinstance(results, list) or len(results) > PER_PAGE:
            raise RefreshError(f"invalid result page for {key}/{year}")
        trimmed = hydrate_truncated(results, get, key, year)
        append_stage(stage, trimmed)
        total_raw += len(results)
        pages += 1
        nxt = meta.get("next_cursor")
        if nxt and nxt in seen:
            raise RefreshError(f"repeated next_cursor for {key}/{year}")
        if total_raw > api_count:
            return restart_query(f"pagination exceeded reported count ({total_raw} > {api_count})")
        cursor = nxt
        stage_bytes = os.path.getsize(stage)
        atomic_json(cp, {"request_sha256": request_sig, "next_cursor": cursor, "cursors": sorted(seen),
                         "api_results": total_raw, "api_count": api_count, "pages": pages,
                         "stage_bytes": stage_bytes, "restart_count": restart_count, "updated_at": now()})
        if cursor:
            time.sleep(.03)
    if total_raw != api_count:
        return restart_query(f"incomplete pages: retrieved {total_raw}, API reported {api_count}")
    raw_works = read_stage(stage)
    if len(raw_works) != total_raw:
        raise RefreshError(f'Staged row count differs from the committed page count for {key}/{year}')
    deduped = deduplicate(raw_works)
    # Crossref years: an observed zero from OpenAlex is a valid reason to keep
    # the existing Crossref data in place; the staged empty file is not published.
    if manual_probe and not deduped:
        record = {"venue": key, "year": year, "status": "skipped_crossref_preserved_openalex_zero",
                  "api_results": total_raw, "unique_works": 0, "query": qparams,
                  "checked_at": now(), "request_attempts": state["requests"],
                  "list_call_attempts": state.get("list_calls", state["requests"]),
                  "singleton_attempts": state.get("singleton_calls", 0), "retries": state.get("retries", 0)}
        for p in (stage, cp):
            if os.path.exists(p): os.unlink(p)
        manifest.setdefault("years", {}).setdefault(key, {})[str(year)] = record
        return record
    excluded = {_doi_key(d) for d in venue.get("exclude_dois", [])}
    deduped = [w for w in deduped if _doi_key(w.get("doi")) not in excluded]
    for w in deduped:
        w["provenance"] = {"checked_at": now(), "query": {"filter": filt, "source_ids": ids, "publication_year": year}}
    data_bytes = b"".join((json.dumps(w, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf8") for w in deduped)
    atomic_bytes(dest, data_bytes)
    checksum = hashlib.sha256(data_bytes).hexdigest()
    record = {"venue": key, "year": year, "status": "complete", "registered_source": entry.get("source") if entry else "openalex_ids",
              "source_ids": ids, "query": qparams, "api_results": total_raw, "api_reported_count": api_count,
              "unique_works": len(deduped), "deduplicated_or_excluded": total_raw - len(deduped),
              "pages": pages, "sha256": checksum, "path": os.path.relpath(dest, out_cache),
              "checked_at": now(), "request_attempts": state["requests"],
              "list_call_attempts": state.get("list_calls", state["requests"]),
              "singleton_attempts": state.get("singleton_calls", 0), "retries": state.get("retries", 0),
              "availability_note": "2026 is year-to-date; source availability does not establish publisher completeness." if year == 2026 else "OpenAlex indexed works; publisher completeness not guaranteed."}
    for p in (stage, cp):
        if os.path.exists(p): os.unlink(p)
    manifest.setdefault("years", {}).setdefault(key, {})[str(year)] = record
    return record


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--venue", action="append", help="repeatable venue key; default is all registered journals")
    p.add_argument("--year-range", nargs=2, type=int, default=(2016, 2026), metavar=("START", "END"))
    p.add_argument("--out-cache", default=".tmp/refresh-2026-10-28/journals/cache")
    p.add_argument("--manifest", default="data/refresh/journal-works-2026-10-28.json")
    p.add_argument("--max-requests", type=int, default=10000,
                   help="overall attempt ceiling, including free singleton lookups")
    p.add_argument("--max-list-requests", type=int, help="separate ceiling for paid /works list attempts")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--refresh", action="store_true", help="required to perform network requests and publish staged results")
    args = p.parse_args(argv)
    if args.max_requests < 1:
        p.error("--max-requests must be positive")
    if args.max_list_requests is not None and args.max_list_requests < 1:
        p.error("--max-list-requests must be positive")
    lo, hi = args.year_range
    if lo > hi:
        p.error("invalid year range")
    reg = get_registry()
    allj = journals(reg)
    by_key = {v["key"]: (ak, v) for ak, v in allj}
    selected = args.venue or list(by_key)
    unknown = sorted(set(selected) - set(by_key))
    if unknown:
        p.error("unknown journal key(s): " + ", ".join(unknown))
    plan = []
    for key in selected:
        _, v = by_key[key]
        sources = v.get("openalex_ids", [])
        min_year = min((r.get("first_publication_year") for x in json.load(open(AUDIT, encoding="utf8")).get("venues", []) if x.get("key") == key for r in x.get("source_records", []) if isinstance(r.get("first_publication_year"), int)), default=lo)
        for yr in range(max(lo, min_year), hi + 1):
            plan.append((key, v, yr))
    if args.dry_run:
        print(json.dumps({"venues": len(selected), "venue_years": len(plan), "out_cache": args.out_cache,
                          "max_requests": args.max_requests, "first_years_skipped_by_source_metadata": True}, indent=2))
        return 0
    if not args.refresh:
        p.error("network refresh requires explicit --refresh")
    api_key = os.environ.get("OPENALEX_API_KEY") or load_env().get("OPENALEX_API_KEY")
    if not api_key:
        p.error("OPENALEX_API_KEY not found in .env")
    manifest_path = args.manifest if os.path.isabs(args.manifest) else os.path.join(ROOT, args.manifest)
    with exclusive_run_lock(args.out_cache, manifest_path):
        return execute_refresh(args, plan, api_key, manifest_path)


def execute_refresh(args, plan, api_key, manifest_path):
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf8") as f: manifest = json.load(f)
    else:
        manifest = {"checked_at": now(), "source": "OpenAlex API /works", "scope": "Registered journals; 2016-2026 inclusive, clipped to source foundation year.", "years": {}}
    # Completed outputs are trusted only when their current bytes match the
    # recorded digest. Mark damaged/missing files for a clean staged refresh.
    for key, venue, year in plan:
        rec = manifest.get("years", {}).get(key, {}).get(str(year), {})
        if rec.get("status") != "complete":
            continue
        dest = os.path.join(args.out_cache, key, str(year), "works.jsonl")
        actual = None
        if os.path.isfile(dest):
            with open(dest, "rb") as f:
                actual = hashlib.sha256(f.read()).hexdigest()
        if actual != rec.get("sha256"):
            rec.update({"status": "integrity_error", "actual_sha256": actual,
                        "integrity_checked_at": now()})
            manifest.setdefault("years", {}).setdefault(key, {})[str(year)] = rec
    get, state = make_client(api_key, args.max_requests, args.max_list_requests)
    # A process can be stopped between venue/year scopes. Per-scope attempt
    # counters are high-water totals, so preserve the greatest completed value
    # and enforce the user-specified budgets across resumed invocations.
    for field, counter in (("request_attempts", "requests"), ("list_call_attempts", "list_calls"),
                           ("singleton_attempts", "singleton_calls"), ("retries", "retries")):
        high_water = max((int(rec.get(field, 0)) for years in manifest.get("years", {}).values()
                          for rec in years.values()), default=0)
        state[counter] = max(int(manifest.get(field, 0) or 0), high_water)
    errors = []
    for key, venue, year in plan:
        try:
            rec = harvest_year(key, venue, year, args.out_cache, manifest, get, state)
            manifest.setdefault("years", {}).setdefault(key, {})[str(year)] = rec
            atomic_json(manifest_path, manifest)
            if rec.get("status") in ("complete",):
                print(f"{key}/{year}: {rec['api_results']} API results, {rec['unique_works']} unique")
            else:
                print(f"{key}/{year}: {rec['status']}")
        except Exception as e:
            errors.append({"venue": key, "year": year, "error": str(e), "checked_at": now()})
            manifest.setdefault("errors", []).append(errors[-1])
            manifest.update({"request_attempts": state["requests"], "list_call_attempts": state.get("list_calls", state["requests"]),
                             "singleton_attempts": state.get("singleton_calls", 0), "retries": state.get("retries", 0)})
            atomic_json(manifest_path, manifest)
            print(f"{key}/{year}: ERROR {e}", file=sys.stderr)
            if isinstance(e, (RequestBudget, PermanentRemoteError, NetworkUnavailable)):
                break
    manifest.update({"request_attempts": state["requests"], "list_call_attempts": state.get("list_calls", state["requests"]),
                     "singleton_attempts": state.get("singleton_calls", 0), "retries": state.get("retries", 0)})
    statuses = { (key, year): manifest.get("years", {}).get(key, {}).get(str(year), {}).get("status", "unattempted")
                 for key, _, year in plan }
    manifest["unresolved_scopes"] = [
        {"venue": key, "year": year, "status": statuses[(key, year)]}
        for key, _, year in plan if statuses[(key, year)] != "complete"
    ]
    unresolved_keys = {(x["venue"], str(x["year"])) for x in manifest["unresolved_scopes"]}
    latest_errors = {}
    for error in manifest.get("errors", []):
        latest_errors[(error.get("venue"), str(error.get("year")))] = error
    manifest["unresolved_errors"] = [latest_errors[k] for k in sorted(unresolved_keys) if k in latest_errors]
    manifest["updated_at"] = now()
    atomic_json(manifest_path, manifest)
    print(f"Finished with {state['requests']} request calls; errors={len(errors)}; manifest={manifest_path}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
