#!/usr/bin/env python3
"""Recover paper-specific author affiliations for cached ML proceedings.

Reads an immutable Semantic Scholar cache and writes a separate ML cache. Only
exact DOI plus strong title matches to OpenAlex are allowed to replace paper
authorship evidence. Semantic Scholar author-profile affiliations are retained
separately and never treated as historical publication affiliations.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.openalex.org"
MAILTO = "eding2019@gmail.com"
VENUES = ("icml", "iclr", "neurips")
BATCH = 100
MAX_LIST_CALLS = 350
DEFAULT_MAX_LIST_CALLS = MAX_LIST_CALLS
DOI_PREFIX = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.I)
TITLE_NOISE = re.compile(r"[^a-z0-9]+")


class RefreshError(RuntimeError):
    pass


class ListBudgetExceeded(RefreshError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def norm_doi(value):
    if not value:
        return None
    return DOI_PREFIX.sub("", str(value).strip()).lower() or None


def norm_title(value):
    value = re.sub(r"<[^>]+>", " ", str(value or "").lower())
    return TITLE_NOISE.sub(" ", value).strip()


def title_score(left, right):
    a, b = norm_title(left), norm_title(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def clean_id(value):
    return str(value or "").rstrip("/").split("/")[-1]


def load_key(env_path):
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf8").splitlines():
        if line.startswith("OPENALEX_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'") or None
    return None


def read_cache(root):
    files = {}
    works = {}
    for venue in VENUES:
        for path in sorted((root / venue).glob("*/works.jsonl")):
            year = path.parent.name
            rows = []
            with path.open(encoding="utf8") as handle:
                for number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if not isinstance(row, dict) or not isinstance(row.get("authorships"), list):
                        raise RefreshError(f"Invalid work at {path}:{number}")
                    rows.append(row)
            files[(venue, year)] = (path, rows)
            for row in rows:
                doi = norm_doi(row.get("doi"))
                if doi:
                    works.setdefault(doi, []).append((venue, year, row))
    return files, works


def trim_openalex(work):
    authorships = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        insts = []
        for inst in authorship.get("institutions") or []:
            insts.append({k: inst.get(k) for k in ("id", "display_name", "country_code", "type", "lineage")})
        authorships.append({
            "author_id": author.get("id"),
            "author_name": author.get("display_name"),
            "institutions": insts,
            "raw_affiliations": list(authorship.get("raw_affiliation_strings") or []),
        })
    result = {
        "id": work.get("id"), "doi": work.get("doi"), "title": work.get("title"),
        "publication_year": work.get("publication_year"), "type": work.get("type"),
        "source": "openalex", "authorships": authorships,
    }
    for field in ("authors_count", "authorships_count", "is_authors_truncated"):
        if field in work:
            result[field] = work[field]
    return result


def richness(work):
    authors = work.get("authorships") or []
    return (len(authors), sum(len(a.get("institutions") or []) + len(a.get("raw_affiliations") or []) for a in authors))


def names(work):
    return [" ".join((a.get("author_name") or "").casefold().split()) for a in work.get("authorships") or []]


def conflict_flags(candidates):
    flags = []
    if len(candidates) < 2:
        return flags
    if len({norm_title(x.get("title")) for x in candidates}) > 1:
        flags.append("openalex_duplicate_doi_title_conflict")
    if len({tuple(names(x)) for x in candidates}) > 1:
        flags.append("openalex_duplicate_doi_byline_conflict")
    if len({x.get("publication_year") for x in candidates if x.get("publication_year") is not None}) > 1:
        flags.append("openalex_duplicate_doi_year_conflict")
    return flags


class OAClient:
    def __init__(self, key, max_list_calls):
        self.key = key
        self.max_list_calls = max_list_calls
        self.state = {"list_calls": 0, "singleton_calls": 0, "retries": 0}
        self.rate_limit_headers = {}

    def _get(self, path, params=None, list_call=False, attempts=4):
        params = dict(params or {})
        params["mailto"] = MAILTO
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params, safe=":,|*!")
        headers = {"User-Agent": "ecerankings-ml-affiliation-recovery/1.0", "Accept": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        for attempt in range(attempts):
            if list_call and self.state["list_calls"] >= self.max_list_calls:
                raise ListBudgetExceeded("OpenAlex list-call budget reached")
            if list_call:
                self.state["list_calls"] += 1
            else:
                self.state["singleton_calls"] += 1
            if attempt:
                self.state["retries"] += 1
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as response:
                    if not self.rate_limit_headers:
                        for header in ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset", "retry-after"):
                            if response.headers.get(header) is not None:
                                self.rate_limit_headers[header] = response.headers.get(header)
                    return json.loads(response.read())
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                    delay = (exc.headers or {}).get("Retry-After")
                    try:
                        time.sleep(min(90, max(1, float(delay))) if delay else 2 ** attempt)
                    except ValueError:
                        time.sleep(2 ** attempt)
                    continue
                if exc.code == 429:
                    raise RefreshError("OpenAlex rate limit or daily request budget exhausted") from None
                if exc.code < 500:
                    try:
                        detail = json.loads(exc.read(2048).decode("utf8", "replace")).get("message", "")
                    except Exception:
                        detail = ""
                    raise RefreshError(f"OpenAlex HTTP {exc.code}: {detail[:200]}") from None
                raise RefreshError(f"OpenAlex HTTP {exc.code}") from None
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                if attempt + 1 < attempts:
                    time.sleep(2 ** attempt)
                    continue
                raise RefreshError(f"OpenAlex network or response failure: {type(exc).__name__}") from None
        raise RefreshError("OpenAlex retries exhausted")

    def batch(self, dois):
        cursor = "*"
        seen_cursors = set()
        found = []
        expected = None
        while cursor:
            if cursor in seen_cursors:
                raise RefreshError("OpenAlex returned a repeated cursor")
            seen_cursors.add(cursor)
            params = {
                "filter": "doi:" + "|".join(dois),
                "select": "id,doi,title,publication_year,type,authorships",
                "per-page": str(BATCH), "cursor": cursor,
            }
            payload = self._get("/works", params, list_call=True)
            meta = payload.get("meta") or {}
            if meta.get("count") is not None:
                if expected is not None and expected != meta["count"]:
                    raise RefreshError("OpenAlex advertised batch count changed during pagination")
                expected = meta["count"]
            results = payload.get("results") or []
            found.extend(results)
            nxt = meta.get("next_cursor")
            if results and not nxt and expected is not None and len(found) != expected:
                raise RefreshError("OpenAlex omitted continuation cursor before advertised count")
            if not results and nxt:
                raise RefreshError("OpenAlex returned an empty page with continuation cursor")
            cursor = nxt
        if expected is not None and len(found) != expected:
            raise RefreshError(f"OpenAlex batch pagination count mismatch: got {len(found)} expected {expected}")
        return found

    def singleton(self, work_id):
        if not work_id:
            raise RefreshError("Cannot hydrate truncated byline without a work ID")
        return self._get("/works/" + urllib.parse.quote(work_id, safe=""))


def hydrate(work, client):
    auths = work.get("authorships") or []
    count = work.get("authors_count", work.get("authorships_count"))
    needs = (work.get("is_authors_truncated") is True or
             (count is not None and len(auths) < count) or len(auths) >= 100)
    if not needs:
        return work, False
    work_id = clean_id(work.get("id"))
    full = client.singleton(work_id)
    if clean_id(full.get("id")) != work_id:
        raise RefreshError(f"Singleton hydration work ID mismatch for {work_id}")
    if norm_doi(work.get("doi")) != norm_doi(full.get("doi")):
        raise RefreshError(f"Singleton hydration DOI mismatch for {work_id}")
    full_authors = full.get("authorships") or []
    full_count = full.get("authors_count", full.get("authorships_count"))
    if full.get("is_authors_truncated") is True or (full_count is not None and len(full_authors) < full_count):
        raise RefreshError(f"Singleton hydration still has a truncated byline for {work_id}")
    if len(full_authors) < len(auths):
        raise RefreshError(f"Singleton hydration returned a shorter byline for {work_id}")
    return full, True


def candidate_sets(raw_results):
    by_doi = defaultdict(list)
    for raw in raw_results:
        doi = norm_doi(raw.get("doi"))
        if doi:
            by_doi[doi].append(raw)
    return by_doi


def add_profile_evidence(work):
    result = json.loads(json.dumps(work))
    for author in result.get("authorships") or []:
        author["institutions"] = []
        profile = author.pop("raw_affiliations", None) or author.pop("profile_affiliations", None) or []
        # A prior run's separated evidence remains separated and is not overwritten.
        if profile and not author.get("profile_affiliations"):
            author["profile_affiliations"] = profile
        if author.get("profile_affiliations"):
            author["profile_affiliation_scope"] = "Semantic Scholar author profile; not verified at publication"
        author.setdefault("raw_affiliations", [])
    return result


def profile_authorship_snapshot(work):
    """Keep source profile evidence separate when bylines cannot be aligned safely."""
    snapshot = []
    for author in work.get("authorships") or []:
        profile = author.get("profile_affiliations") or author.get("raw_affiliations") or []
        if profile:
            snapshot.append({
                "author_id": author.get("author_id"),
                "author_name": author.get("author_name"),
                "profile_affiliations": list(profile),
                "profile_affiliation_scope": "Semantic Scholar author profile; not verified at publication",
            })
    return snapshot


def profile_string_count(work):
    attached = sum(len(a.get("profile_affiliations") or []) for a in work.get("authorships") or [])
    snapshots = sum(len(a.get("profile_affiliations") or [])
                    for a in work.get("semanticscholar_profile_authorships") or [])
    return attached + snapshots


def audit_staged_cache(baseline, output, manifest, list_calls, max_list_calls,
                       expected_unique_dois=None, rate_limit_headers=None, execution=None):
    """Validate a completed staged cache and write the parent integration manifest."""
    if list_calls > max_list_calls:
        raise RefreshError("OpenAlex list-call budget exceeded during staged-cache audit")
    baseline_files, baseline_by_doi = read_cache(baseline)
    files = []
    counts = Counter()
    matched_dois = set()
    for (venue, year), (source_path, old_rows) in sorted(baseline_files.items()):
        target = output / venue / year / "works.jsonl"
        if not target.is_file():
            raise RefreshError(f"Staged output missing {venue}/{year}")
        new_rows = []
        with target.open(encoding="utf8") as handle:
            for line in handle:
                if line.strip():
                    new_rows.append(json.loads(line))
        if len(new_rows) != len(old_rows):
            raise RefreshError(f"Staged work count differs for {venue}/{year}")
        record = Counter()
        authors = covered = 0
        for old, new in zip(old_rows, new_rows):
            if new.get("publication_year") != old.get("publication_year"):
                raise RefreshError(f"Staged publication year changed for {venue}/{year}")
            old_profile_strings = sum(
                len(a.get("profile_affiliations") or a.get("raw_affiliations") or [])
                for a in old.get("authorships") or [])
            if profile_string_count(new) != old_profile_strings:
                raise RefreshError(f"Staged Semantic Scholar profile evidence was lost for {venue}/{year}")
            doi = norm_doi(old.get("doi"))
            if new.get("backfilled_from") == "openalex":
                if not doi or norm_doi(new.get("doi")) != doi or title_score(old.get("title"), new.get("title")) < 0.88:
                    raise RefreshError(f"Staged OpenAlex identity validation failed for {venue}/{year}")
                if new.get("publication_year") != old.get("publication_year"):
                    raise RefreshError(f"Staged OpenAlex publication year mismatch for {venue}/{year}")
                if not new.get("id") or not isinstance(new.get("authorships"), list):
                    raise RefreshError(f"Staged OpenAlex work lacks ID or byline for {venue}/{year}")
                author_count = new.get("authors_count", new.get("authorships_count"))
                if new.get("is_authors_truncated") is True or (author_count is not None and len(new["authorships"]) < author_count):
                    raise RefreshError(f"Staged OpenAlex byline remains truncated for {venue}/{year}")
                record["works_backfilled"] += 1
                matched_dois.add(doi)
                counts["authors_in_backfilled_works"] += len(new.get("authorships") or [])
                record["full_byline_authors"] += len(new.get("authorships") or [])
                record["profile_affiliations_retained"] += sum(bool(a.get("profile_affiliations")) for a in new.get("authorships") or [])
                record["profile_authorships_preserved_separately"] += len(new.get("semanticscholar_profile_authorships") or [])
                record["authors_hydrated"] += bool(new.get("authors_hydrated"))
            else:
                if doi:
                    record["historical_affiliations_empty"] += 1
                else:
                    record["missing_doi_unresolved"] += 1
                if new.get("source") == "semanticscholar":
                    for author in new.get("authorships") or []:
                        if author.get("institutions") or author.get("raw_affiliations"):
                            raise RefreshError(f"Unverified Semantic Scholar profile affiliation in historical fields for {venue}/{year}")
                        if author.get("profile_affiliations"):
                            record["profile_affiliation_authors_retained"] += 1
            for author in new.get("authorships") or []:
                authors += 1
                covered += bool(author.get("institutions") or author.get("raw_affiliations"))
        output_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        counts.update(record)
        file_entry = {
            "venue": venue, "year": int(year), "works": len(new_rows),
            "input_sha256": source_hash, "sha256": output_hash,
            "works_backfilled": record["works_backfilled"],
            "matched_doi_records": record["works_backfilled"],
            "matched_unique_dois": len({norm_doi(n.get("doi")) for o, n in zip(old_rows, new_rows) if n.get("backfilled_from") == "openalex"}),
            "full_byline_authors_in_backfilled_works": record["full_byline_authors"],
            "authors_hydrated": record["authors_hydrated"],
            "profile_affiliations_retained": record["profile_affiliations_retained"],
            "profile_authorships_preserved_separately": record["profile_authorships_preserved_separately"],
            "profile_affiliation_authors_retained": record["profile_affiliation_authors_retained"],
            "missing_doi_unresolved": record["missing_doi_unresolved"],
            "historical_affiliations_empty": record["historical_affiliations_empty"],
            "remaining_gaps": record["missing_doi_unresolved"] + record["historical_affiliations_empty"],
            "author_slots": authors, "slots_with_affiliation_signal": covered,
        }
        files.append(file_entry)
    counts["baseline_works"] = sum(len(rows) for _, rows in baseline_files.values())
    counts["unique_doi"] = len(baseline_by_doi)
    counts["unique_doi_matched"] = len(matched_dois)
    counts["unique_doi_unmatched"] = max(0, len(baseline_by_doi) - len(matched_dois))
    profile_strings = 0
    for path in output.glob("*/*/works.jsonl"):
        with path.open(encoding="utf8") as handle:
            for line in handle:
                if line.strip():
                    profile_strings += profile_string_count(json.loads(line))
    counts["profile_affiliations_withheld_from_historical_credit"] = profile_strings
    counts["list_calls"] = list_calls
    counts["singleton_calls"] = sum(row["authors_hydrated"] for row in files)
    counts["remaining_list_call_allowance"] = max(0, max_list_calls - list_calls)
    counts["doi_lookup_complete"] = 1
    report = {
        "generated_at": utc_now(), "checked_at": utc_now(), "provider": "OpenAlex",
        "baseline": str(baseline), "output": str(output), "complete": True,
        "matching": "exact normalized DOI plus normalized title exact match or SequenceMatcher similarity >= 0.88",
        "source_doi_title_recovery_coverage": {"baseline_unique_doi": len(baseline_by_doi),
            "matched_unique_doi": len(matched_dois), "unmatched_unique_doi": max(0, len(baseline_by_doi) - len(matched_dois)),
            "missing_doi_works": counts["missing_doi_unresolved"],
            "backfilled_work_records": counts["works_backfilled"]},
        "batch_size": BATCH, "requested_max_list_calls": max_list_calls,
        "rate_limit_headers_first_response": rate_limit_headers or {},
        "counts": dict(counts),
        "source_semantics": "Only paper-level OpenAlex authorships populate historical raw_affiliations/institutions. Semantic Scholar author-profile affiliations remain separate and are never credited as publication affiliations.",
        "proceedings_scope": "Semantic Scholar venue/year membership is retained as the baseline set; the refresh does not verify complete publisher proceedings archives.",
        "api_execution": execution or {"list_calls": list_calls, "list_call_budget": max_list_calls},
        "files": files,
        "results": [{"venue": row["venue"], "year": row["year"], "status": "complete",
                     "sha256": row["sha256"], "path": str(output / row["venue"] / str(row["year"]) / "works.jsonl"),
                     "works": row["works"], "matched_doi_records": row["matched_doi_records"],
                     "full_byline_authors": row["full_byline_authors_in_backfilled_works"],
                     "remaining_gaps": row["remaining_gaps"]} for row in files],
    }
    atomic_write_json(manifest, report)
    return report


def retain_profile_on_backfill(baseline, fresh):
    old_authors = baseline.get("authorships") or []
    new_authors = fresh.get("authorships") or []
    if len(old_authors) != len(new_authors):
        return fresh, 0
    if not all(names(baseline)) or names(baseline) != names(fresh):
        return fresh, 0
    count = 0
    for old, new in zip(old_authors, new_authors):
        profile = old.get("profile_affiliations") or old.get("raw_affiliations") or []
        if profile:
            new["profile_affiliations"] = list(profile)
            new["profile_affiliation_scope"] = "Semantic Scholar author profile; not verified at publication"
            count += 1
    return fresh, count


def work_to_openalex(raw, client):
    raw, was_hydrated = hydrate(raw, client)
    work = trim_openalex(raw)
    if was_hydrated:
        work["authors_hydrated"] = True
    return work


def atomic_write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf8") as handle:
            json.dump(obj, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def atomic_write_lines(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as handle:
            for row in rows:
                data = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf8")
                handle.write(data)
                digest.update(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return digest.hexdigest()


def run(baseline, output, manifest, key, max_list_calls=DEFAULT_MAX_LIST_CALLS):
    if max_list_calls < 0 or max_list_calls > MAX_LIST_CALLS:
        raise RefreshError(f"OpenAlex list-call budget must be between 0 and {MAX_LIST_CALLS}")
    if output.exists():
        raise RefreshError(f"Output already exists: {output}")
    files, works_by_doi = read_cache(baseline)
    output.mkdir(parents=True)
    counts = Counter()
    by_doi = {d: rows for d, rows in works_by_doi.items()}
    client = OAClient(key, max_list_calls)
    batches = [list(by_doi)[i:i + BATCH] for i in range(0, len(by_doi), BATCH)]
    matched = {}
    errors = []
    for batch_index, batch in enumerate(batches, 1):
        counts["batch_count"] += 1
        try:
            results = client.batch(batch)
        except RefreshError as exc:
            errors.append(str(exc))
            break
        results_by_doi = candidate_sets(results)
        for doi in batch:
            exact = results_by_doi.get(doi, [])
            if not exact:
                # A successful, complete batch with no result is distinct from a request failure.
                counts["doi_no_openalex_record"] += 1
                continue
            viable = []
            for raw in exact:
                if norm_doi(raw.get("doi")) != doi:
                    continue
                scores = [title_score(raw.get("title"), baseline_row.get("title")) for _, _, baseline_row in by_doi[doi]]
                score = max(scores, default=0.0)
                if score >= 0.88:
                    viable.append((raw, score))
            if not viable:
                counts["doi_title_identity_rejected"] += 1
                continue
            candidates = [x[0] for x in viable]
            flags = conflict_flags(candidates)
            # Prefer completeness first; if tied use normalized title score then stable work ID.
            viable.sort(key=lambda x: (richness(x[0]), x[1], clean_id(x[0].get("id"))), reverse=True)
            best_raw, best_score = viable[0]
            try:
                fresh = work_to_openalex(best_raw, client)
            except RefreshError as exc:
                errors.append(f"{doi}: {exc}")
                counts["doi_hydration_failed"] += 1
                continue
            if norm_doi(fresh.get("doi")) != doi:
                errors.append(f"{doi}: selected OpenAlex DOI mismatch")
                counts["doi_hydration_failed"] += 1
                continue
            fresh["backfilled_from"] = "openalex"
            fresh["backfill_title_similarity"] = round(best_score, 4)
            if flags:
                fresh["backfill_conflicts"] = flags
            matched[doi] = fresh
            counts["doi_matched"] += 1
            counts["matched_openalex_records"] += 1
            if fresh.get("authors_hydrated"):
                counts["authorship_singleton_hydrated"] += 1
            counts["match_full_byline"] += len(fresh.get("authorships") or [])
        if batch_index % 10 == 0 or batch_index == len(batches):
            print(f"ML batches {batch_index}/{len(batches)}; list calls {client.state['list_calls']}; matched DOI {counts['doi_matched']}", flush=True)

    # If the run stopped before all batches, do not claim missing records for unqueried DOI.
    complete_lookup = counts["batch_count"] == len(batches) and not errors
    file_manifest = []
    for (venue, year), (source_path, rows) in sorted(files.items()):
        out_rows = []
        file_count = Counter()
        for baseline_row in rows:
            doi = norm_doi(baseline_row.get("doi"))
            fresh = matched.get(doi) if doi else None
            if fresh and title_score(baseline_row.get("title"), fresh.get("title")) < 0.88:
                fresh = None
            if fresh and fresh.get("publication_year") != baseline_row.get("publication_year"):
                counts["doi_year_identity_rejected"] += 1
                fresh = None
            if fresh:
                merged = json.loads(json.dumps(fresh))
                merged, retained_profile = retain_profile_on_backfill(baseline_row, merged)
                file_count["works_backfilled"] += 1
                file_count["profile_affiliations_retained"] += retained_profile
                if not retained_profile:
                    profile_snapshot = profile_authorship_snapshot(baseline_row)
                    if profile_snapshot:
                        merged["semanticscholar_profile_authorships"] = profile_snapshot
                        file_count["profile_authorships_preserved_separately"] += len(profile_snapshot)
            else:
                merged = add_profile_evidence(baseline_row)
                if not doi:
                    file_count["missing_doi_unresolved"] += 1
                else:
                    file_count["historical_affiliations_empty"] += 1
            out_rows.append(merged)
        target = output / venue / year / "works.jsonl"
        digest = atomic_write_lines(target, out_rows)
        file_manifest.append({
            "venue": venue, "year": int(year), "works": len(out_rows),
            "input_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "works_backfilled": file_count["works_backfilled"],
            "matched_doi_records": file_count["works_backfilled"],
            "full_byline_authors_in_backfilled_works": sum(len(w.get("authorships") or []) for w in out_rows if w.get("backfilled_from") == "openalex"),
            "profile_affiliations_retained": file_count["profile_affiliations_retained"],
            "missing_doi_unresolved": file_count["missing_doi_unresolved"],
            "historical_affiliations_empty": file_count["historical_affiliations_empty"],
            "remaining_gaps": file_count["missing_doi_unresolved"] + file_count["historical_affiliations_empty"],
            "sha256": digest,
        })
        counts.update(file_count)
    counts["baseline_works"] = sum(len(rows) for _, rows in files.values())
    counts["unique_doi"] = len(by_doi)
    counts["doi_lookup_complete"] = int(complete_lookup)
    counts["list_calls"] = client.state["list_calls"]
    counts["singleton_calls"] = client.state["singleton_calls"]
    counts["retries"] = client.state["retries"]
    counts["remaining_list_call_allowance"] = max(0, max_list_calls - client.state["list_calls"])
    profile_strings = 0
    for path in output.glob("*/*/works.jsonl"):
        with path.open(encoding="utf8") as handle:
            for line in handle:
                if line.strip():
                    profile_strings += sum(len(a.get("profile_affiliations") or [])
                                           for a in json.loads(line).get("authorships") or [])
    counts["profile_affiliations_withheld_from_historical_credit"] = profile_strings
    report = {
            "generated_at": utc_now(), "checked_at": utc_now(), "provider": "OpenAlex", "baseline": str(baseline),
        "output": str(output), "matching": "exact normalized DOI plus title similarity >= 0.88",
        "batch_size": BATCH, "requested_max_list_calls": max_list_calls,
        "rate_limit_headers_first_response": client.rate_limit_headers,
        "source_semantics": "Only paper-level OpenAlex authorships populate historical raw_affiliations/institutions. Semantic Scholar author-profile affiliations remain separate and are never credited as publication affiliations.",
        "proceedings_scope": "Semantic Scholar venue/year membership is retained as the baseline set; the refresh does not verify complete publisher proceedings archives.",
        "complete": complete_lookup, "counts": dict(counts), "errors": errors,
        "files": file_manifest,
        "results": [{"venue": row["venue"], "year": row["year"], "status": "complete" if complete_lookup else "incomplete",
                     "sha256": row["sha256"], "path": str(output / row["venue"] / str(row["year"]) / "works.jsonl"),
                     "works": row["works"], "matched_doi_records": row["matched_doi_records"],
                     "full_byline_authors": row["full_byline_authors_in_backfilled_works"],
                     "remaining_gaps": row["remaining_gaps"]} for row in file_manifest],
    }
    atomic_write_json(manifest, report)
    if not complete_lookup:
        raise RefreshError("OpenAlex lookup did not complete; partial staged cache and incomplete manifest retained")
    execution = {
        "batches": counts["batch_count"],
        "list_attempts": client.state["list_calls"],
        "list_attempt_limit": max_list_calls,
        "list_attempts_remaining": max(0, max_list_calls - client.state["list_calls"]),
        "singleton_calls": client.state["singleton_calls"],
        "retries": client.state["retries"],
        "doi_title_candidates": counts["doi_matched"],
        "doi_no_openalex_record": counts["doi_no_openalex_record"],
        "doi_title_identity_rejected": counts["doi_title_identity_rejected"],
        "doi_year_identity_rejected_rows": counts["doi_year_identity_rejected"],
        "request_errors": errors,
    }
    return audit_staged_cache(
        baseline, output, manifest, client.state["list_calls"], max_list_calls,
        rate_limit_headers=client.rate_limit_headers, execution=execution,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=ROOT / ".tmp/refresh-2026-10-28/ml-baseline/cache")
    parser.add_argument("--output", type=Path, default=ROOT / ".tmp/refresh-2026-10-28/ml/cache")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/refresh/ml-works-2026-10-28.json")
    parser.add_argument("--max-list-calls", type=int, default=DEFAULT_MAX_LIST_CALLS)
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    args = parser.parse_args(argv)
    try:
        report = run(args.baseline, args.output, args.manifest, load_key(args.env), args.max_list_calls)
    except RefreshError as exc:
        print(f"ML refresh incomplete: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"complete": report["complete"], "counts": report["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
