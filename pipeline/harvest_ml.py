#!/usr/bin/env python3
"""Harvest ML proceedings (ICLR, ICML, NeurIPS) from publisher membership lists.

Usage:
    python3 pipeline/harvest_ml.py --venue iclr --year 2025 --stage all
    python3 pipeline/harvest_ml.py --venue iclr --year 2025 --stage discover
    python3 pipeline/harvest_ml.py --venue iclr --year 2025 --stage all --offline
    python3 pipeline/harvest_ml.py --venue iclr --year 2025 --stage reconcile-openreview

Replaces the Semantic Scholar venue-tag path (harvest_s2.py + refresh_ml.py),
which had two separable defects -- see data/reports/ml-fix-plan-2026-10-29.md:

  1. Membership. S2's venue tag is not the accepted-paper list: ICLR 2025 had
     1,772 S2 rows against 3,703 official proceedings entries. Here the
     publisher list (proceedings.iclr.cc, PMLR, proceedings.neurips.cc, or
     OpenReview once authenticated) is the only thing that admits a paper.
  2. Affiliations. S2 author-profile strings say where someone is now, not
     where they were on this paper. Only paper-specific evidence is credited:
     the OpenAlex work-author join for the paper's publisher DOI or its arXiv
     twin. S2 contributes identifiers (arXiv ID) and nothing else.

Why arXiv twins: ICLR and PMLR deposit no DOIs, and OpenAlex attributes these
papers to arXiv rather than to the conference. 785 of the 788 "DOIs" in the old
ICLR 2025 cache were already 10.48550/arXiv.* DataCite DOIs. NeurIPS has
publisher DOIs (Curran, 10.52202/...), but OpenAlex carries no affiliations for
the 2024 ones sampled, so the arXiv twin is the fallback there too. The
publisher row stays canonical: an arXiv record never becomes a second corpus
item and never sets the byline. The publisher byline defines N for the 1/N
split; OpenAlex affiliations are copied only onto authors who align by name.

Stages (each idempotent and resumable; everything is written under
--stage-root, never cache/):

  membership  publisher list -> <venue>/<year>/membership.jsonl (all tracks)
  discover    paper -> arXiv DOI / OpenAlex work via the legacy local S2 cache,
              S2 bulk search, OpenAlex OR-batched title search, then the arXiv
              API (S2 per-title match only with --s2-match). Append-only
              discovery.jsonl.
  enrich      OpenAlex by DOI, 100 per call (refresh_ml.OAClient). Append-only
              openalex.jsonl; a failed request is retried, never a negative.
  pdf         final publisher PDF -> first-page text (kept) -> per-author
              affiliations via pdf_affiliations.py. 4 parallel downloads; the
              PDF itself is deleted unless the paper needs review. Stored text
              is re-extracted whenever EXTRACTOR_VERSION changes, so extractor
              fixes never need a re-download.
  build       canonical works.jsonl (included tracks) + excluded-tracks.jsonl.
              Per author slot: the final publisher PDF first (user decision
              2026-10-30: the version of record, and an image check found
              OpenAlex wrong in 38 of 45 disagreements), then OpenAlex where
              the PDF has nothing; --prefer-openalex restores the fix plan's
              original order. Every slot where the two disagree is recorded.
  gates       coverage gates -> state.json and the refresh manifest. status is
              "complete" only when every gate passes, so prepare_refresh.py
              cannot pick up a failing edition.

HTTP: per-host minimum interval, Retry-After honoured, exponential backoff, raw
bodies cached under <stage-root>/raw so a re-run (or --offline) makes no
requests. An OpenReview 403 challenge is fatal, never an empty result.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refresh_ml  # noqa: E402
import s2_discovery  # noqa: E402
from refresh_ml import (OAClient, RefreshError, atomic_write_json,  # noqa: E402
                        atomic_write_lines, candidate_sets, hydrate, load_key,
                        title_score, trim_openalex, utc_now)
from workkey import norm_doi, norm_title, work_key  # noqa: E402
from harvest_crossref import author_slug  # noqa: E402
import pdf_affiliations  # noqa: E402
import pdf_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MAILTO = "eding2019@gmail.com"
USER_AGENT = f"ecerankings-harvest-ml/1.0 (mailto:{MAILTO})"
DEFAULT_STAGE_ROOT = ROOT / ".tmp" / "ml-harvest"
DEFAULT_MANIFEST = ROOT / "data" / "refresh" / "ml-harvest-2026-10-29.json"
STAGES = ("membership", "discover", "enrich", "pdf", "build", "gates")
ARXIV_PREFIX = "10.48550/arxiv."
AFFILIATION_SOURCES = {"openalex-publisher-doi", "openalex-arxiv-doi", "openalex-title-match", "publisher-pdf",
                       "publisher-pdf-image"}
# Minimum extractor accuracy (author slots, high-confidence sample, judged
# against the page image) for the pdf_verification gate.
PDF_TEXT_ACCURACY_MIN = 0.98
# Extraction confidence levels whose per-author values are credited. Only
# "high" was validated (96% agreement with OpenAlex on 300 ICLR 2025 papers;
# the extractor was right in 38 of 45 disagreements checked against page
# images); "partial" papers go to the review queue instead.
PDF_ACCEPT = {"high"}
PDF_WORKERS = 4

# S2 hits only supply an identifier, but a wrong identifier would import the
# wrong paper's affiliations, so the bar is higher than OpenAlex's 0.88 title
# threshold. OpenAlex candidates are then re-checked against the publisher row.
S2_TITLE_MIN = 0.95
S2_BYLINE_MIN = 0.8
OA_TITLE_MIN = 0.88
ALIGN_MIN = 0.9

GATES = {
    "membership_unexplained_diff_max": 0.01,
    "author_slot_affiliation_min": 0.90,
    "institution_resolution_min": 0.95,
}

PMLR_ICML_VOLUMES = {2013: 28, 2014: 32, 2015: 37, 2016: 48, 2017: 70, 2018: 80,
                     2019: 97, 2020: 119, 2021: 139, 2022: 162, 2023: 202,
                     2024: 235, 2025: 267}

# Edition registry. `expected` anchors are official counts for the included
# track set, each with its source; a count alone never passes the membership
# gate -- every row must also carry a publisher membership ID.
EDITIONS = {
    ("iclr", 2025): {
        "adapter": "proceedings_listing",
        "url": "https://proceedings.iclr.cc/paper_files/paper/2025",
        "include_tracks": ["Conference"],
        "s2_venue": "ICLR",
        "openreview_venueid": "ICLR.cc/2025/Conference",
        "expected": [
            {"count": 3703, "scope": "included", "source": "https://proceedings.iclr.cc/paper_files/paper/2025"},
            {"count": 3704, "scope": "included", "source": "https://media.iclr.cc/Conferences/ICLR2025/ICLR2025_Fact_Sheet.pdf",
             "note": "Reconciled 2026-10-30: authenticated OpenReview lists 3,703 accepted notes, matching the book paper-for-paper (7 retitled at camera-ready). No accepted record accounts for the 3,704th; treat as a post-fact-sheet change."},
        ],
    },
    ("iclr", 2024): {
        "adapter": "proceedings_listing",
        "url": "https://proceedings.iclr.cc/paper_files/paper/2024",
        "include_tracks": ["Conference"],
        "s2_venue": "ICLR",
        "openreview_venueid": "ICLR.cc/2024/Conference",
        "expected": [],
    },
    ("neurips", 2025): {
        "adapter": "proceedings_listing",
        "url": "https://proceedings.neurips.cc/paper_files/paper/2025/vol38-main-conference",
        # User decision 2026-10-29: Conference + Datasets & Benchmarks;
        # Position Paper and Creative AI tracks excluded.
        "include_tracks": ["Conference", "Datasets_and_Benchmarks_Track"],
        "s2_venue": "NeurIPS",
        "crossref_doi": {"prefix": "10.52202", "container_title": "Advances in Neural Information Processing Systems 38"},
        "expected": [
            {"count": 5290, "scope": "track:Conference", "source": "https://media.neurips.cc/Conferences/NeurIPS2025/press/NeurIPS2025-Fact_Sheet.pdf"},
            {"count": 5823, "scope": "all", "source": "https://proceedings.neurips.cc/paper_files/paper/2025/vol38-main-conference"},
        ],
    },
}
for _year, _volume in PMLR_ICML_VOLUMES.items():
    EDITIONS[("icml", _year)] = {
        "adapter": "pmlr_bib",
        "url": f"https://proceedings.mlr.press/v{_volume}/assets/bib/bibliography.bib",
        "volume": _volume,
        "include_tracks": ["Conference"],
        "s2_venue": "ICML",
        "expected": ([{"count": 3260, "scope": "included",
                       "source": "https://media.icml.cc/Conferences/ICML2025/ICML2025_Fact_Sheet.pdf",
                       "note": "Main-track accepts; PMLR v267 lists 3,330 entries with no track label. Reconcile before gating."}]
                     if _year == 2025 else []),
    }
# ICLR 2017-2023 have no adapter yet: proceedings.iclr.cc starts at 2024 and
# OpenReview rejects anonymous API calls with a 403 challenge (2026-10-29).
# Add them with adapter "openreview" once an authenticated probe confirms the
# per-year venue IDs.


class HarvestError(RuntimeError):
    pass


class ChallengeError(HarvestError):
    """A bot challenge. Never treated as an empty result."""


# --------------------------------------------------------------------------
# HTTP

class Fetcher:
    """Polite GET/POST with a raw-body disk cache keyed by method+URL+body."""

    INTERVALS = {
        "proceedings.iclr.cc": 1.0, "proceedings.neurips.cc": 1.0,
        "proceedings.mlr.press": 1.0, "api.semanticscholar.org": 1.1,
        "api.crossref.org": 0.3, "api2.openreview.net": 1.0, "api.openreview.net": 1.0,
        "api.openalex.org": 0.1,
        # arXiv's API terms ask for one request every three seconds.
        "export.arxiv.org": 3.0,
    }
    MAX_INTERVAL = 10.0

    def __init__(self, raw_dir, offline=False, attempts=6):
        self.raw_dir = Path(raw_dir)
        self.offline = offline
        self.attempts = attempts
        self.last = {}
        self.intervals = dict(self.INTERVALS)
        self.stats = Counter()
        self.last_headers = {}

    def _cache_path(self, method, url, data):
        digest = hashlib.sha256(f"{method} {url}\n".encode() + (data or b"")).hexdigest()
        host = urllib.parse.urlsplit(url).netloc
        return self.raw_dir / host / digest

    def _wait(self, host):
        interval = self.intervals.get(host, 1.0)
        delta = time.monotonic() - self.last.get(host, 0.0)
        if delta < interval:
            time.sleep(interval - delta)
        self.last[host] = time.monotonic()

    def get(self, url, *, data=None, headers=None, cache=True, ok_statuses=(200,)):
        """Return (status, body). Statuses in ok_statuses are cached and returned."""
        method = "POST" if data is not None else "GET"
        host = urllib.parse.urlsplit(url).netloc
        path = self._cache_path(method, url, data)
        if cache and path.with_suffix(".json").exists():
            meta = json.loads(path.with_suffix(".json").read_text())
            self.stats[f"{host}:cache_hits"] += 1
            return meta["status"], path.with_suffix(".body").read_bytes()
        if self.offline:
            raise HarvestError(f"--offline and no cached response for {url}")
        hdrs = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        hdrs.update(headers or {})
        for attempt in range(self.attempts):
            self._wait(host)
            self.stats[f"{host}:requests"] += 1
            if attempt:
                self.stats[f"{host}:retries"] += 1
            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
            status, body, retry_after = None, b"", None
            try:
                with urllib.request.urlopen(req, timeout=90) as response:
                    status, body = response.status, response.read()
                    self.last_headers[host] = dict(response.headers.items())
            except urllib.error.HTTPError as exc:
                status, body = exc.code, exc.read() or b""
                retry_after = (exc.headers or {}).get("Retry-After")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt + 1 < self.attempts:
                    time.sleep(min(60, 2 ** attempt))
                    continue
                raise HarvestError(f"Network failure for {url}: {type(exc).__name__}") from None
            if status in ok_statuses:
                if cache:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.with_suffix(".body").write_bytes(body)
                    path.with_suffix(".json").write_text(json.dumps({"url": url, "method": method, "status": status, "fetched_at": utc_now()}))
                return status, body
            if status == 403 and b"challenge" in body.lower():
                raise ChallengeError(f"Bot challenge from {host} (HTTP 403); authenticate or use another source")
            if status in (429, 500, 502, 503, 504) and attempt + 1 < self.attempts:
                if status == 429:
                    self.intervals[host] = min(self.MAX_INTERVAL, self.intervals.get(host, 1.0) * 1.5)
                try:
                    delay = float(retry_after) if retry_after else 2 ** attempt
                except ValueError:
                    delay = 2 ** attempt
                time.sleep(min(60, max(1, delay)))
                continue
            raise HarvestError(f"HTTP {status} for {url}: {body[:200]!r}")
        raise HarvestError(f"Retries exhausted for {url}")

    def get_json(self, url, **kwargs):
        if url.startswith(s2_discovery.BASE):
            client = getattr(self, '_s2_client', None)
            if client is None:
                client = self._s2_client = s2_discovery.Client(
                    self.raw_dir / 's2', offline=self.offline, attempts=self.attempts)
            parsed = urllib.parse.urlsplit(url)
            params = dict(urllib.parse.parse_qsl(parsed.query))
            headers = kwargs.get('headers') or {}
            if headers.get('x-api-key'):
                client.api_key = headers['x-api-key']
            try:
                return client.request(parsed.path.removeprefix('/graph/v1/'), params,
                                      ok_statuses=kwargs.get('ok_statuses', (200,)))
            except s2_discovery.S2Error as exc:
                raise HarvestError(str(exc)) from exc
        status, body = self.get(url, **kwargs)
        return status, (json.loads(body) if body else None)


# --------------------------------------------------------------------------
# Names and identity

_FOLD = str.maketrans({"ø": "o", "ł": "l", "đ": "d", "ß": "ss", "æ": "ae", "œ": "oe", "ı": "i", "þ": "th"})
_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def name_tokens(name):
    text = unicodedata.normalize("NFKD", html.unescape(str(name or "")).casefold().translate(_FOLD))
    text = "".join(c for c in text if not unicodedata.combining(c)).replace("'", "").replace("’", "")
    return [t for t in re.findall(r"[a-z0-9]+", text) if t not in _SUFFIXES]


def names_match(left, right):
    a, b = name_tokens(left), name_tokens(right)
    if not a or not b:
        return False
    if a[-1] == b[-1] and a[0][0] == b[0][0]:
        return True
    if set(a) == set(b):
        return True
    # OpenReview handles typed without spaces ("BinChen" vs "Bin Chen").
    if "".join(a) in ("".join(b), "".join(reversed(b))):
        return True
    # Family-name-first order on one side ("Zhang Wei" vs "Wei Zhang").
    return a[-1] == b[0] and a[0][0] == b[-1][0]


def align_bylines(publisher, candidate):
    """Order-preserving alignment (LCS under names_match). Returns [(i, j)]."""
    n, m = len(publisher), len(candidate)
    if not n or not m or n * m > 250_000:
        return []
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if names_match(publisher[i], candidate[j]):
                table[i][j] = table[i + 1][j + 1] + 1
            else:
                table[i][j] = max(table[i + 1][j], table[i][j + 1])
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if names_match(publisher[i], candidate[j]) and table[i][j] == table[i + 1][j + 1] + 1:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def byline_overlap(publisher, candidate):
    if not publisher:
        return 0.0
    return sum(any(names_match(p, c) for c in candidate) for p in publisher) / len(publisher)


def arxiv_doi(arxiv_id):
    arxiv_id = re.sub(r"v\d+$", "", str(arxiv_id or "").strip().lower())
    return ARXIV_PREFIX + arxiv_id if arxiv_id else None


def is_arxiv(doi):
    return bool(doi) and doi.startswith(ARXIV_PREFIX)


def year_plausible(doi, oa_year, edition):
    if oa_year is None:
        return False
    if is_arxiv(doi):
        # Preprints precede the edition; a camera-ready may be posted after.
        return edition - 2 <= oa_year <= edition + 1
    return edition - 1 <= oa_year <= edition + 1


def sha256_file(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def append_jsonl(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()


# --------------------------------------------------------------------------
# Membership adapters

class ListingParser(HTMLParser):
    """proceedings.iclr.cc / proceedings.neurips.cc year or book listing.

    <li data-track=...><a title="paper title" href=".../hash/<h>-Abstract-<Track>.html">
    Title</a><span class="paper-authors">A, B, C</span></li>
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries = []
        self._cur = None
        self._field = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li":
            self._cur = {"href": None, "title": "", "authors": ""}
        elif self._cur is not None and tag == "a" and attrs.get("title") == "paper title":
            self._cur["href"] = attrs.get("href")
            self._field = "title"
        elif self._cur is not None and tag == "span" and "paper-authors" in (attrs.get("class") or ""):
            self._field = "authors"

    def handle_endtag(self, tag):
        if tag in ("a", "span"):
            self._field = None
        elif tag == "li" and self._cur is not None:
            if self._cur["href"]:
                self.entries.append(self._cur)
            self._cur = None

    def handle_data(self, data):
        if self._cur is not None and self._field:
            self._cur[self._field] += data


def split_listing_authors(text):
    # Listings double-escape apostrophes ("D&amp;#x27;Oro"); the parser undoes
    # one level, html.unescape the other.
    parts = [html.unescape(p).strip() for p in html.unescape(text).split(",")]
    authors = []
    for part in parts:
        if not part:
            continue
        if authors and part.casefold().rstrip(".") in {"jr", "sr", "ii", "iii", "iv"}:
            authors[-1] = f"{authors[-1]}, {part}"
        else:
            authors.append(part)
    return authors


def parse_listing(body, base_url, venue, year):
    parser = ListingParser()
    parser.feed(body)
    rows = []
    for entry in parser.entries:
        href = entry["href"]
        match = re.search(r"/hash/([0-9a-f]+)-Abstract-([A-Za-z_]+)\.html$", href)
        if not match:
            continue
        digest, track = match.groups()
        url = urllib.parse.urljoin(base_url, href)
        rows.append({
            "paper_key": f"{venue}:{year}:{digest}",
            "membership_id": digest,
            "membership_url": url,
            "pdf_url": url.replace("/hash/", "/file/").replace("-Abstract-", "-Paper-").replace(".html", ".pdf"),
            "track": track,
            "title": " ".join(html.unescape(entry["title"]).split()),
            "authors": split_listing_authors(entry["authors"]),
            "publisher_doi": None,
        })
    return rows


_LATEX_ACCENTS = {'"': "\u0308", "'": "\u0301", "`": "\u0300", "^": "\u0302", "~": "\u0303",
                  "=": "\u0304", ".": "\u0307", "u": "\u0306", "v": "\u030c", "H": "\u030b", "c": "\u0327", "k": "\u0328"}
_LATEX_LETTERS = {"o": "ø", "O": "Ø", "l": "ł", "L": "Ł", "ss": "ß", "ae": "æ", "AE": "Æ", "oe": "œ", "aa": "å", "AA": "Å"}


def latex_to_text(value):
    # Dotless i/j first so "\\'{\\i}" becomes "\\'{i}" for the accent rule.
    text = re.sub(r"\\([ij])(?![A-Za-z])", r"\1", value)
    text = re.sub(r"\\([\"'`^~=.uvHck])\s*\{?\s*([A-Za-z])\s*\}?",
                  lambda m: m.group(2) + _LATEX_ACCENTS[m.group(1)], text)
    text = re.sub(r"\\(ss|ae|AE|oe|aa|AA|o|O|l|L)(?![A-Za-z])\s*", lambda m: _LATEX_LETTERS[m.group(1)], text)
    text = text.replace("{", "").replace("}", "").replace("\\&", "&").replace("~", " ")
    return unicodedata.normalize("NFC", " ".join(text.split()))


def parse_bibtex(text):
    """Minimal brace-aware BibTeX reader -> [{'_type', '_key', field: raw value}]."""
    entries, i, n = [], 0, len(text)
    while True:
        i = text.find("@", i)
        if i < 0:
            break
        brace = text.find("{", i)
        if brace < 0:
            break
        etype = text[i + 1:brace].strip().lower()
        comma = text.find(",", brace)
        key = text[brace + 1:comma].strip()
        entry = {"_type": etype, "_key": key}
        j = comma + 1
        while j < n:
            while j < n and text[j] in " \t\r\n,":
                j += 1
            if j >= n or text[j] == "}":
                j += 1
                break
            eq = text.find("=", j)
            name = text[j:eq].strip().lower()
            j = eq + 1
            while text[j] in " \t\r\n":
                j += 1
            if text[j] == "{":
                depth, start = 0, j + 1
                while j < n:
                    if text[j] == "{":
                        depth += 1
                    elif text[j] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                entry[name] = text[start:j]
                j += 1
            elif text[j] == '"':
                end = text.find('"', j + 1)
                entry[name] = text[j + 1:end]
                j = end + 1
            else:
                m = re.match(r"[^,}\s]+", text[j:])
                entry[name] = m.group(0)
                j += m.end()
        entries.append(entry)
        i = j
    return entries


def split_bib_authors(value):
    depth, cur, parts = 0, "", []
    tokens = re.split(r"(\{|\}|\s+and\s+)", value)
    for tok in tokens:
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth -= 1
        if depth == 0 and re.fullmatch(r"\s+and\s+", tok or ""):
            parts.append(cur)
            cur = ""
        else:
            cur += tok or ""
    parts.append(cur)
    names = []
    for part in parts:
        part = latex_to_text(part)
        if "," in part:
            last, first = part.split(",", 1)
            part = f"{first.strip()} {last.strip()}"
        if part.strip():
            names.append(" ".join(part.split()))
    return names


def parse_pmlr(text, venue, year, volume):
    entries = parse_bibtex(text)
    procs = [e for e in entries if e["_type"] == "proceedings"]
    if not procs or "international conference on machine learning" not in latex_to_text(procs[0].get("booktitle", "")).casefold():
        raise HarvestError(f"PMLR v{volume} is not an ICML proceedings volume")
    rows = []
    for e in entries:
        if e["_type"] != "inproceedings":
            continue
        slug = e["_key"].removeprefix(f"pmlr-v{volume}-")
        rows.append({
            "paper_key": f"{venue}:{year}:{slug}",
            "membership_id": e["_key"],
            "membership_url": e.get("url") or f"https://proceedings.mlr.press/v{volume}/{slug}.html",
            "pdf_url": e.get("pdf"),
            "track": "Conference",
            "title": latex_to_text(e.get("title", "")),
            "authors": split_bib_authors(e.get("author", "")),
            "publisher_doi": norm_doi(e.get("doi")),
        })
    return rows


def crossref_dois(fetcher, prefix, container_title):
    """norm_title -> DOI for one Curran-style proceedings container."""
    found, cursor = {}, "*"
    while cursor:
        params = {"filter": f"prefix:{prefix},container-title:{container_title}", "rows": 500,
                  "cursor": cursor, "select": "DOI,title", "mailto": MAILTO}
        _, payload = fetcher.get_json("https://api.crossref.org/works?" + urllib.parse.urlencode(params, safe=":,*"))
        items = payload["message"].get("items") or []
        for item in items:
            title = (item.get("title") or [""])[0]
            found.setdefault(norm_title(html.unescape(title)), norm_doi(item.get("DOI")))
        cursor = payload["message"].get("next-cursor") if items else None
    return found


def openreview_token(env_path):
    """OPENREVIEW_TOKEN, or a login with OPENREVIEW_USERNAME/OPENREVIEW_PASSWORD, from .env."""
    values = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf8").splitlines():
            if "=" in line and line.startswith("OPENREVIEW_"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip("\"'")
    values.update({k: v for k, v in os.environ.items() if k.startswith("OPENREVIEW_")})
    if values.get("OPENREVIEW_TOKEN"):
        return values["OPENREVIEW_TOKEN"]
    if values.get("OPENREVIEW_USERNAME") and values.get("OPENREVIEW_PASSWORD"):
        return {"id": values["OPENREVIEW_USERNAME"], "password": values["OPENREVIEW_PASSWORD"]}
    return None


def openreview_notes(fetcher, venueid, env_path, api="https://api2.openreview.net"):
    """Accepted notes for an API v2 venue id. Needs an authenticated session."""
    cred = openreview_token(env_path)
    if cred is None:
        raise HarvestError("OpenReview needs OPENREVIEW_TOKEN or OPENREVIEW_USERNAME/PASSWORD in .env")
    if isinstance(cred, dict):
        # Never cached: the response is a session token.
        _, body = fetcher.get(api + "/login", data=json.dumps(cred).encode(),
                              headers={"Content-Type": "application/json"}, cache=False)
        token = json.loads(body)["token"]
    else:
        token = cred
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    notes, offset = [], 0
    while True:
        params = urllib.parse.urlencode({"content.venueid": venueid, "limit": 1000, "offset": offset})
        _, payload = fetcher.get_json(f"{api}/notes?{params}", headers=headers)
        batch = payload.get("notes") or []
        notes.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000
    rows = []
    for note in notes:
        content = note.get("content") or {}
        val = lambda k: (content.get(k) or {}).get("value") if isinstance(content.get(k), dict) else content.get(k)  # noqa: E731
        rows.append({"openreview_id": note.get("id"), "title": val("title"),
                     "authors": val("authors") or [], "venue": val("venue")})
    return rows


# --------------------------------------------------------------------------
# Stage context

class Edition:
    def __init__(self, venue, year, stage_root, fetcher, env_path):
        if (venue, year) not in EDITIONS:
            raise HarvestError(f"No edition config for {venue} {year} (see EDITIONS)")
        self.venue, self.year = venue, year
        self.config = EDITIONS[(venue, year)]
        self.dir = Path(stage_root) / venue / str(year)
        self.cache_dir = Path(stage_root) / "cache" / venue / str(year)
        self.fetcher = fetcher
        self.env_path = env_path
        self.state_path = self.dir / "state.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.pdf_dir = Path(stage_root) / "pdf" / venue / str(year)
        self.prefer_pdf = True

    @property
    def membership_path(self):
        return self.dir / "membership.jsonl"

    @property
    def discovery_path(self):
        return self.dir / "discovery.jsonl"

    @property
    def openalex_path(self):
        return self.dir / "openalex.jsonl"

    @property
    def pdf_fetch_path(self):
        return self.dir / "pdf-fetch.jsonl"

    @property
    def pdf_extract_path(self):
        return self.dir / "pdf-extract.jsonl"

    @property
    def pdf_verify_path(self):
        return self.dir / "pdf-verify.jsonl"

    @property
    def pdf_text_dir(self):
        return self.dir / "pdf-text"

    @property
    def works_path(self):
        return self.cache_dir / "works.jsonl"

    def included(self):
        tracks = set(self.config["include_tracks"])
        return [m for m in read_jsonl(self.membership_path) if m["track"] in tracks]

    def save_state(self):
        atomic_write_json(self.state_path, self.state)

    def stage_inputs(self, stage):
        if stage == "membership":
            return hashlib.sha256(json.dumps(self.config, sort_keys=True).encode()).hexdigest()
        if stage == "discover":
            return sha256_file(self.membership_path)
        if stage == "enrich":
            return f"{sha256_file(self.membership_path)}:{sha256_file(self.discovery_path)}"
        if stage == "pdf":
            return f"{sha256_file(self.membership_path)}:extractor-v{pdf_affiliations.EXTRACTOR_VERSION}"
        if stage == "build":
            return ":".join(str(sha256_file(p)) for p in (self.membership_path, self.discovery_path, self.openalex_path,
                                                         self.pdf_extract_path, self.pdf_verify_path)) + f":prefer_pdf={self.prefer_pdf}"
        return sha256_file(self.works_path)

    def is_done(self, stage):
        entry = self.state.get(stage) or {}
        return bool(entry.get("done")) and entry.get("input_sha256") == self.stage_inputs(stage)

    def mark(self, stage, done, counts):
        self.state[stage] = {"done": done, "input_sha256": self.stage_inputs(stage),
                             "finished_at": utc_now(), "counts": dict(counts)}
        self.save_state()


# --------------------------------------------------------------------------
# Stages

def stage_membership(ed):
    cfg = ed.config
    if cfg["adapter"] == "proceedings_listing":
        _, body = ed.fetcher.get(cfg["url"])
        rows = parse_listing(body.decode("utf8"), cfg["url"], ed.venue, ed.year)
    elif cfg["adapter"] == "pmlr_bib":
        _, body = ed.fetcher.get(cfg["url"])
        rows = parse_pmlr(body.decode("utf8"), ed.venue, ed.year, cfg["volume"])
    else:
        raise HarvestError(f"Unknown adapter {cfg['adapter']}")
    if cfg.get("crossref_doi"):
        dois = crossref_dois(ed.fetcher, cfg["crossref_doi"]["prefix"], cfg["crossref_doi"]["container_title"])
        for row in rows:
            row["publisher_doi"] = row["publisher_doi"] or dois.get(norm_title(row["title"]))
    counts = Counter()
    seen, out = set(), []
    by_identity = Counter((norm_title(r["title"]), tuple(r["authors"])) for r in rows)
    for row in rows:
        if row["membership_id"] in seen:
            counts["duplicate_membership_id_dropped"] += 1
            continue
        seen.add(row["membership_id"])
        if by_identity[(norm_title(row["title"]), tuple(row["authors"]))] > 1:
            row["duplicate_suspect"] = True
            counts["duplicate_suspect"] += 1
        if not row["authors"]:
            counts["empty_byline"] += 1
        counts[f"track:{row['track']}"] += 1
        counts["publisher_doi"] += bool(row["publisher_doi"])
        out.append(row)
    counts["rows"] = len(out)
    counts["included"] = sum(r["track"] in set(cfg["include_tracks"]) for r in out)
    if not out:
        raise HarvestError(f"{ed.venue} {ed.year}: publisher listing parsed to zero rows")
    atomic_write_lines(ed.membership_path, out)
    ed.mark("membership", True, counts)
    return counts


def legacy_index(venue, year):
    """Identifiers from the committed S2-derived cache. Local, no requests."""
    path = ROOT / "cache" / venue / str(year) / "works.jsonl"
    index = {}
    if not path.exists() or path.read_bytes()[:40].startswith(b"version https://git-lfs"):
        return index
    for row in read_jsonl(path):
        doi = norm_doi(row.get("doi"))
        if is_arxiv(doi):
            names = [a.get("author_name") for a in row.get("authorships") or []]
            index.setdefault(norm_title(row.get("title")), []).append({"doi": doi, "title": row.get("title"), "authors": names})
    return index


def s2_headers(env_path):
    key = s2_discovery.load_api_key(env_path)
    return {"x-api-key": key} if key else {}


def s2_bulk_index(ed):
    venue = ed.config.get("s2_venue")
    index, token = {}, None
    if not venue:
        return index
    headers = s2_headers(ed.env_path)
    while True:
        params = {"query": "*", "venue": venue, "year": ed.year, "fields": "title,externalIds,authors,year"}
        if token:
            params["token"] = token
        _, payload = ed.fetcher.get_json("https://api.semanticscholar.org/graph/v1/paper/search/bulk?" + urllib.parse.urlencode(params), headers=headers)
        for paper in payload.get("data") or []:
            doi = arxiv_doi((paper.get("externalIds") or {}).get("ArXiv"))
            if doi:
                index.setdefault(norm_title(paper.get("title")), []).append(
                    {"doi": doi, "title": paper.get("title"), "authors": [a.get("name") for a in paper.get("authors") or []],
                     "s2_paper_id": paper.get("paperId")})
        token = payload.get("token")
        if not token:
            break
    return index


def accept_identifier(member, cand):
    score = title_score(member["title"], cand["title"])
    overlap = byline_overlap(member["authors"], cand["authors"])
    return score >= S2_TITLE_MIN and overlap >= S2_BYLINE_MIN, score, overlap


def lookup_index(member, index):
    for cand in index.get(norm_title(member["title"]), []):
        ok, score, overlap = accept_identifier(member, cand)
        if ok:
            return cand, score, overlap
    return None


def clean_query_title(title):
    # Commas separate OpenAlex filters and quotes delimit arXiv phrases, so
    # queries carry alphanumeric words only; matching uses the real title.
    return " ".join(re.sub(r"[^\w]+", " ", html.unescape(title or "")).split())


def openalex_title_search(ed, batch, key):
    """One OR-batched title.search call -> {paper_key: [trimmed candidates]}."""
    terms = "|".join(clean_query_title(m["title"]) for m in batch)
    params = {"filter": "title.search:" + terms, "select": "id,doi,title,publication_year,type,authorships",
              "per-page": "100", "mailto": MAILTO}
    headers = {"Authorization": "Bearer " + key} if key else {}
    _, payload = ed.fetcher.get_json("https://api.openalex.org/works?" + urllib.parse.urlencode(params, safe=":|"),
                                     headers=headers)
    if (payload.get("meta") or {}).get("count", 0) > 100 and len(batch) > 1:
        half = len(batch) // 2
        return {**openalex_title_search(ed, batch[:half], key), **openalex_title_search(ed, batch[half:], key)}
    results = [trim_openalex(w) for w in payload.get("results") or []]
    hits = {}
    for member in batch:
        for work in results:
            cand = {"title": work["title"], "authors": [a["author_name"] for a in work["authorships"]]}
            ok, _, _ = accept_identifier(member, cand)
            if ok:
                hits.setdefault(member["paper_key"], []).append(work)
    return hits


_ATOM = "{http://www.w3.org/2005/Atom}"


def arxiv_title_search(ed, batch):
    """One OR-batched arXiv API query -> {paper_key: candidate}."""
    import xml.etree.ElementTree as ET
    query = " OR ".join(f'ti:"{clean_query_title(m["title"])}"' for m in batch)
    params = {"search_query": query, "start": 0, "max_results": 5 * len(batch)}
    _, body = ed.fetcher.get("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params))
    papers = []
    for entry in ET.fromstring(body).iter(_ATOM + "entry"):
        ident = (entry.findtext(_ATOM + "id") or "").rsplit("/abs/", 1)[-1]
        papers.append({"doi": arxiv_doi(ident), "title": " ".join((entry.findtext(_ATOM + "title") or "").split()),
                       "authors": [a.findtext(_ATOM + "name") for a in entry.iter(_ATOM + "author")]})
    hits = {}
    for member in batch:
        for cand in papers:
            ok, score, overlap = accept_identifier(member, cand)
            if ok and cand["doi"]:
                hits[member["paper_key"]] = (cand, score, overlap)
                break
    return hits


def stage_discover(ed, key=None, max_search_calls=400, s2_match=False, max_match_calls=None, batch_size=10):
    """Find each publisher paper's arXiv twin / OpenAlex work.

    Sources run cheapest first; a paper stops at its first accepted hit. Only
    a final verdict is appended to discovery.jsonl -- a miss in one source is
    not a negative while later sources remain, and a request error is never a
    negative (the paper stays pending and a re-run retries it).
    """
    members = ed.included()
    done = {r["paper_key"]: r for r in read_jsonl(ed.discovery_path)}
    oa_done = {r["key"] for r in read_jsonl(ed.openalex_path)}
    counts = Counter()
    pending = [m for m in members if m["paper_key"] not in done]
    counts["already_resolved"] = len(members) - len(pending)

    def record(member, source, cand=None, score=None, overlap=None, status="ok", reason=None, **extra):
        row = {"paper_key": member["paper_key"], "status": status, "source": source, "at": utc_now(), **extra}
        if cand:
            row.update(arxiv_doi=cand.get("doi"), s2_paper_id=cand.get("s2_paper_id"),
                       matched_title=cand["title"], title_score=round(score, 4), byline_overlap=round(overlap, 4))
        if reason:
            row["reason"] = reason
        append_jsonl(ed.discovery_path, row)
        done[member["paper_key"]] = row
        counts[f"{status}:{source}"] += 1

    for source, builder in (("legacy-s2-cache", lambda: legacy_index(ed.venue, ed.year)),
                            ("s2-bulk", lambda: s2_bulk_index(ed))):
        if not pending:
            break
        index = builder()
        still = []
        for member in pending:
            hit = lookup_index(member, index)
            if hit:
                record(member, source, *hit)
            else:
                still.append(member)
        pending = still

    # OpenAlex title search returns the works themselves, so accepted hits go
    # straight into openalex.jsonl; enrich has nothing left to do for them.
    oa_misses, calls = [], 0
    tried = {r["paper_key"] for r in read_jsonl(ed.dir / "title-search-misses.jsonl")}
    queue = [m for m in pending if m["paper_key"] not in tried]
    oa_misses = [m for m in pending if m["paper_key"] in tried]
    for start in range(0, len(queue), batch_size):
        batch = queue[start:start + batch_size]
        if calls >= max_search_calls:
            counts["openalex_title_deferred_by_cap"] += len(queue) - start
            break
        calls += 1
        try:
            hits = openalex_title_search(ed, batch, key)
        except HarvestError as exc:
            counts["openalex_title_errors"] += 1
            print(f"  OpenAlex title search error: {exc}", file=sys.stderr)
            continue
        for member in batch:
            works = hits.get(member["paper_key"])
            if works:
                oa_key = "title:" + member["paper_key"]
                if oa_key not in oa_done:
                    append_jsonl(ed.openalex_path, {"key": oa_key, "status": "ok", "candidates": works, "at": utc_now()})
                    oa_done.add(oa_key)
                arxiv = next((norm_doi(w["doi"]) for w in works if is_arxiv(norm_doi(w["doi"]))), None)
                record(member, "openalex-title", openalex_key=oa_key, openalex_ids=[w["id"] for w in works],
                       arxiv_doi=arxiv)
            else:
                append_jsonl(ed.dir / "title-search-misses.jsonl", {"paper_key": member["paper_key"], "at": utc_now()})
                oa_misses.append(member)
        if calls % 25 == 0:
            remaining = ed.fetcher.last_headers.get("api.openalex.org", {}).get("X-RateLimit-Remaining-USD")
            print(f"  [{ed.venue}/{ed.year}] OpenAlex title search {calls} calls; budget remaining ${remaining}", flush=True)
    counts["openalex_title_calls"] = calls
    pending = [m for m in oa_misses if m["paper_key"] not in done]

    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        try:
            hits = arxiv_title_search(ed, batch)
        except HarvestError as exc:
            counts["arxiv_api_errors"] += 1
            print(f"  arXiv API error: {exc}", file=sys.stderr)
            continue
        for member in batch:
            if member["paper_key"] in hits:
                record(member, "arxiv-api", *hits[member["paper_key"]])
            elif not s2_match:
                record(member, "arxiv-api", status="none", reason="no identity-checked match in OpenAlex title search or arXiv")
    pending = [m for m in pending if m["paper_key"] not in done]

    if s2_match:
        headers = s2_headers(ed.env_path)
        calls = errors = 0
        for number, member in enumerate(pending, 1):
            if max_match_calls is not None and calls >= max_match_calls:
                counts["match_deferred_by_cap"] = len(pending) - number + 1
                break
            url = ("https://api.semanticscholar.org/graph/v1/paper/search/match?" +
                   urllib.parse.urlencode({"query": member["title"], "fields": "title,externalIds,authors,year"}))
            calls += 1
            try:
                status, payload = ed.fetcher.get_json(url, headers=headers, ok_statuses=(200, 404))
            except HarvestError as exc:
                errors += 1
                counts["match_request_errors"] += 1
                if errors >= 25:
                    print(f"  stopping S2 match after {errors} request errors: {exc}", file=sys.stderr)
                    break
                continue
            papers = ((payload or {}).get("data") or []) if status == 200 else []
            hit = None
            for paper in papers:
                cand = {"doi": arxiv_doi((paper.get("externalIds") or {}).get("ArXiv")), "title": paper.get("title"),
                        "authors": [a.get("name") for a in paper.get("authors") or []], "s2_paper_id": paper.get("paperId")}
                ok, score, overlap = accept_identifier(member, cand)
                if ok and cand["doi"]:
                    hit = (cand, score, overlap)
                    break
            if hit:
                record(member, "s2-match", *hit)
            else:
                record(member, "s2-match", status="none",
                       reason="no S2 title match" if not papers else "S2 match failed title/byline check or has no arXiv ID")
    counts["papers"] = len(members)
    counts["with_identifier"] = sum(1 for m in members if (done.get(m["paper_key"]) or {}).get("status") == "ok")
    unresolved = sum(1 for m in members if m["paper_key"] not in done)
    ed.mark("discover", unresolved == 0, counts)
    if unresolved:
        print(f"  discover incomplete: {unresolved} papers still pending (re-run to resume)", file=sys.stderr)
    return counts


def stage_enrich(ed, key, max_list_calls):
    members = ed.included()
    disc = {r["paper_key"]: r for r in read_jsonl(ed.discovery_path)}
    wanted = set()
    for m in members:
        if m.get("publisher_doi"):
            wanted.add(m["publisher_doi"])
        d = disc.get(m["paper_key"]) or {}
        # Title-search hits already carry their OpenAlex works.
        if d.get("status") == "ok" and d.get("arxiv_doi") and not d.get("openalex_key"):
            wanted.add(d["arxiv_doi"])
    done = {r["key"] for r in read_jsonl(ed.openalex_path)}
    pending = sorted(wanted - done)
    counts = Counter(dois_wanted=len(wanted), dois_already_queried=len(wanted & done))
    client = OAClient(key, max_list_calls)
    error = None
    for start in range(0, len(pending), refresh_ml.BATCH):
        batch = pending[start:start + refresh_ml.BATCH]
        try:
            by_doi = candidate_sets(client.batch(batch))
            rows = []
            for doi in batch:
                cands = []
                for raw in by_doi.get(doi, []):
                    full, hydrated = hydrate(raw, client)
                    work = trim_openalex(full)
                    work["authors_hydrated"] = hydrated
                    cands.append(work)
                rows.append({"key": doi, "status": "ok" if cands else "none", "candidates": cands, "at": utc_now()})
        except RefreshError as exc:
            # Nothing from this batch is recorded, so a resume re-queries it.
            error = str(exc)
            break
        for row in rows:
            append_jsonl(ed.openalex_path, row)
            counts[f"doi_{row['status']}"] += 1
    counts["list_calls"] = client.state["list_calls"]
    counts["singleton_calls"] = client.state["singleton_calls"]
    counts["retries"] = client.state["retries"]
    complete = error is None
    ed.mark("enrich", complete, counts)
    if error:
        ed.state["enrich"]["error"] = error
        ed.save_state()
        print(f"  enrich stopped: {error} (partial results kept; re-run to resume)", file=sys.stderr)
    return counts


def download_pdf(url, attempts=4):
    """Fetch one PDF. Returns bytes; raises HarvestError after retries."""
    for attempt in range(attempts):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                body = response.read()
            if not body.startswith(b"%PDF"):
                raise HarvestError(f"Not a PDF: {url}")
            return body
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                time.sleep(min(60, 2 ** attempt))
                continue
            raise HarvestError(f"HTTP {exc.code} for {url}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt + 1 < attempts:
                time.sleep(min(60, 2 ** attempt))
                continue
            raise HarvestError(f"Network failure for {url}") from None
    raise HarvestError(f"Retries exhausted for {url}")


def stage_pdf(ed, workers=PDF_WORKERS, keep_pdfs=False, offline=False):
    """Final publisher PDF -> stored first-page text -> per-author affiliations.

    Two layers so each is cheap to redo: pdf-fetch.jsonl (append-only; one
    successful row per paper means its text is on disk) and pdf-extract.jsonl
    (rewritten every run from the stored text). A download failure is logged
    and retried next run; it never counts as "no affiliations".
    """
    members = ed.included()
    ed.pdf_text_dir.mkdir(parents=True, exist_ok=True)
    ed.pdf_dir.mkdir(parents=True, exist_ok=True)
    fetched = {r["paper_key"]: r for r in read_jsonl(ed.pdf_fetch_path) if r.get("status") == "ok"}
    counts = Counter()

    def text_path(m):
        return ed.pdf_text_dir / f"{m['membership_id']}.txt"

    def fetch(member):
        pdf_path = ed.pdf_dir / f"{member['membership_id']}.pdf"
        if pdf_path.exists():
            body, source = pdf_path.read_bytes(), "local"
        elif offline:
            raise HarvestError("--offline and PDF not downloaded")
        else:
            body, source = download_pdf(member["pdf_url"]), "download"
            tmp = pdf_path.with_suffix(".part")
            tmp.write_bytes(body)
            os.replace(tmp, pdf_path)
        text = pdf_affiliations.first_page_text(pdf_path)
        tpath = text_path(member)
        tmp = tpath.with_suffix(".part")
        tmp.write_text(text, encoding="utf8")
        os.replace(tmp, tpath)
        result = pdf_affiliations.extract(text, member["authors"])
        # Keep the PDF only where a human (or the image fallback) may need it.
        if not keep_pdfs and result["confidence"] == "high":
            pdf_path.unlink()
        return {"paper_key": member["paper_key"], "status": "ok", "source": source,
                "pdf_sha256": hashlib.sha256(body).hexdigest(), "pdf_bytes": len(body),
                "text_sha256": hashlib.sha256(text.encode("utf8")).hexdigest(), "at": utc_now()}

    todo = [m for m in members if m["paper_key"] not in fetched or not text_path(m).exists()]
    counts["already_fetched"] = len(members) - len(todo)
    if todo:
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(fetch, m): m for m in todo}
            for number, future in enumerate(futures, 1):
                member = futures[future]
                try:
                    row = future.result()
                except (HarvestError, OSError, subprocess.SubprocessError) as exc:
                    counts["fetch_errors"] += 1
                    append_jsonl(ed.pdf_fetch_path, {"paper_key": member["paper_key"], "status": "error",
                                                     "error": str(exc)[:200], "at": utc_now()})
                    continue
                append_jsonl(ed.pdf_fetch_path, row)
                fetched[member["paper_key"]] = row
                counts[f"fetched_{row['source']}"] += 1
                if number % 250 == 0:
                    print(f"  [{ed.venue}/{ed.year}] PDFs {number}/{len(todo)} ({time.monotonic() - start:.0f}s)", flush=True)

    rows, review = [], []
    for member in members:
        tpath = text_path(member)
        if member["paper_key"] not in fetched or not tpath.exists():
            continue
        result = pdf_affiliations.extract(tpath.read_text(encoding="utf8"), member["authors"])
        rows.append({"paper_key": member["paper_key"], "extractor_version": pdf_affiliations.EXTRACTOR_VERSION,
                     "text_sha256": fetched[member["paper_key"]].get("text_sha256"), **result})
        counts[f"confidence:{result['confidence']}"] += 1
        counts[f"layout:{result['layout']}"] += 1
        if result["confidence"] != "high":
            pdf_path = ed.pdf_dir / f"{member['membership_id']}.pdf"
            review.append({"paper_key": member["paper_key"], "title": member["title"], "confidence": result["confidence"],
                           "reason": result["reason"], "authors": member["authors"], "extracted": result["affiliations"],
                           "pdf_url": member["pdf_url"], "local_pdf": str(pdf_path) if pdf_path.exists() else None})
    atomic_write_lines(ed.pdf_extract_path, rows)
    atomic_write_lines(ed.dir / "pdf-review.jsonl", review)
    counts["papers"] = len(members)
    counts["extracted"] = len(rows)
    counts["review_queue"] = len(review)
    complete = len(rows) == len(members)
    ed.mark("pdf", complete, counts)
    if not complete:
        print(f"  pdf incomplete: {len(members) - len(rows)} papers without text (re-run to retry)", file=sys.stderr)
    return counts


def evaluate_candidate(member, lookup_doi, cand, year):
    """Return (accepted, pairs, reasons) for one OpenAlex candidate.

    lookup_doi is the DOI the candidate was fetched by, or None for a
    title-search hit (identity then rests on title, byline and year alone).
    """
    reasons = []
    cand_doi = norm_doi(cand.get("doi"))
    if lookup_doi and cand_doi != lookup_doi:
        reasons.append("doi_mismatch")
    if title_score(member["title"], cand.get("title")) < OA_TITLE_MIN:
        reasons.append("title_mismatch")
    if not year_plausible(cand_doi, cand.get("publication_year"), year):
        reasons.append("year_implausible")
    cand_names = [a.get("author_name") for a in cand.get("authorships") or []]
    pairs = align_bylines(member["authors"], cand_names)
    if not member["authors"] or len(pairs) < ALIGN_MIN * len(member["authors"]) or len(pairs) < ALIGN_MIN * len(cand_names):
        reasons.append("byline_mismatch")
    return not reasons, pairs, reasons


def has_affiliation(cand):
    return any(a.get("institutions") or a.get("raw_affiliations") for a in cand.get("authorships") or [])


def build_row(ed, member, disc, oa, pdf=None, verify=None):
    venue, year = ed.venue, ed.year
    evidence = {"dois": [], "rejected": []}
    options = []
    disc_ok = (disc or {}).get("status") == "ok"
    lookups = [(member.get("publisher_doi"), member.get("publisher_doi"))]
    if disc_ok and disc.get("openalex_key"):
        lookups.append((disc["openalex_key"], None))
    elif disc_ok:
        lookups.append((disc.get("arxiv_doi"), disc.get("arxiv_doi")))
    for oa_key, lookup_doi in lookups:
        if not oa_key:
            continue
        if lookup_doi:
            evidence["dois"].append(lookup_doi)
        for cand in (oa.get(oa_key) or {}).get("candidates", []):
            ok, pairs, reasons = evaluate_candidate(member, lookup_doi, cand, year)
            cand_doi = norm_doi(cand.get("doi"))
            label = "openalex-arxiv-doi" if is_arxiv(cand_doi) else "openalex-publisher-doi"
            if cand_doi and lookup_doi is None and not is_arxiv(cand_doi) and cand_doi != member.get("publisher_doi"):
                # A title-search hit with some other DOI (a journal extension,
                # a workshop version) is a different publication.
                ok, reasons = False, reasons + ["foreign_doi"]
            if not cand_doi:
                label = "openalex-title-match"
            if ok:
                options.append((label, cand, pairs))
            else:
                evidence["rejected"].append({"key": oa_key, "openalex_id": cand.get("id"), "reasons": reasons})
    # Publisher record first when it actually carries affiliations; otherwise
    # the richest accepted twin.
    options.sort(key=lambda o: (has_affiliation(o[1]), o[0] == "openalex-publisher-doi",
                                sum(bool(a.get("institutions")) for a in o[1]["authorships"])), reverse=True)
    chosen = options[0] if options else None
    aligned = {i: j for i, j in chosen[2]} if chosen else {}
    pdf_ok = bool(pdf) and pdf.get("confidence") in PDF_ACCEPT and len(pdf.get("affiliations") or []) == len(member["authors"])
    authorships, conflicts = [], []
    for i, name in enumerate(member["authors"]):
        oa_author = chosen[1]["authorships"][aligned[i]] if i in aligned else None
        author_id = (oa_author or {}).get("author_id") or f"{venue}:name:{author_slug(name, '')}"
        oa_has = bool(oa_author and (oa_author.get("institutions") or oa_author.get("raw_affiliations")))
        pdf_values = list(pdf["affiliations"][i]) if pdf_ok else []
        pdf_label = "publisher-pdf"
        if verify and verify.get("image_ok") and i < len(verify["authors"]):
            # The page image overrides the text parser: it is the same
            # document, read the way a person reads it.
            check = verify["authors"][i]
            if check["verdict"] in ("wrong", "missing") and check["page_affiliations"]:
                pdf_values, pdf_label = list(check["page_affiliations"]), "publisher-pdf-image"
            elif check["verdict"] == "absent":
                pdf_values = []
        if oa_has and pdf_values:
            oa_strings = list(oa_author.get("raw_affiliations") or []) + [x.get("display_name") or "" for x in oa_author.get("institutions") or []]
            if not pdf_affiliations.strings_agree(pdf_values, oa_strings):
                conflicts.append({"author": name, "pdf": pdf_values, "openalex": oa_strings[:3]})
        use_pdf = bool(pdf_values) and (ed.prefer_pdf or not oa_has)
        if use_pdf:
            # Raw strings only: institutions are resolved downstream through
            # data/affiliation-map.csv, exactly like Crossref strings.
            authorships.append({"author_id": author_id, "author_name": name, "institutions": [],
                                "raw_affiliations": pdf_values, "affiliation_source": pdf_label})
        elif oa_has:
            authorships.append({"author_id": author_id, "author_name": name,
                                "institutions": oa_author.get("institutions") or [],
                                "raw_affiliations": oa_author.get("raw_affiliations") or [],
                                "affiliation_source": chosen[0]})
        else:
            authorships.append({"author_id": author_id, "author_name": name, "institutions": [], "raw_affiliations": []})
    if pdf:
        evidence["pdf"] = {"confidence": pdf.get("confidence"), "layout": pdf.get("layout"),
                           "credited": pdf_ok, "reason": pdf.get("reason")}
    if verify:
        evidence["pdf_image_check"] = {"kind": verify.get("kind"), "model": verify.get("model"),
                                       "image_ok": verify.get("image_ok"),
                                       "verdicts": [a["verdict"] for a in verify["authors"]]}
    if conflicts:
        evidence["pdf_openalex_conflicts"] = conflicts
    if chosen:
        evidence.update(openalex_id=chosen[1].get("id"), openalex_doi=norm_doi(chosen[1].get("doi")),
                        source=chosen[0], aligned_authors=len(aligned),
                        candidate_authors=len(chosen[1]["authorships"]))
    if disc:
        evidence["discovered_via"] = disc.get("source") if disc_ok else None
    return {
        "id": member["paper_key"],
        "doi": f"https://doi.org/{member['publisher_doi']}" if member.get("publisher_doi") else None,
        "title": member["title"],
        "publication_year": year,
        "type": "proceedings-article",
        "source": urllib.parse.urlsplit(member["membership_url"]).netloc,
        "membership": {k: member.get(k) for k in ("membership_id", "membership_url", "pdf_url", "track")},
        "evidence": evidence,
        "authorships": authorships,
    }


def stage_build(ed):
    members = read_jsonl(ed.membership_path)
    disc = {r["paper_key"]: r for r in read_jsonl(ed.discovery_path)}
    oa = {r["key"]: r for r in read_jsonl(ed.openalex_path)}
    pdfs = {r["paper_key"]: r for r in read_jsonl(ed.pdf_extract_path)}
    checks = {r["paper_key"]: r for r in read_jsonl(ed.pdf_verify_path)}
    tracks = set(ed.config["include_tracks"])
    included, excluded = [], []
    for member in members:
        row = build_row(ed, member, disc.get(member["paper_key"]), oa, pdfs.get(member["paper_key"]),
                        checks.get(member["paper_key"]))
        (included if member["track"] in tracks else excluded).append(row)
    keys = Counter(work_key(r, ed.venue, ed.year) for r in included)
    counts = Counter(works=len(included), excluded_track_rows=len(excluded),
                     duplicate_work_keys=sum(c - 1 for c in keys.values() if c > 1))
    for row in included:
        source = row["evidence"].get("source")
        counts[f"evidence:{source or 'none'}"] += 1
        counts["rejected_candidates"] += len(row["evidence"]["rejected"])
        counts["pdf_openalex_conflict_slots"] += len(row["evidence"].get("pdf_openalex_conflicts") or [])
        for a in row["authorships"]:
            counts[f"slot_source:{a.get('affiliation_source') or 'none'}"] += 1
    sha = atomic_write_lines(ed.works_path, included)
    atomic_write_lines(ed.cache_dir / "excluded-tracks.jsonl", excluded)
    ed.mark("build", True, counts)
    ed.state["build"]["sha256"] = sha
    ed.save_state()
    return counts


def load_affiliation_map():
    """data/affiliation-map.csv, read the way aggregate.py reads it."""
    import aggregate
    return aggregate.load_affiliation_map(), aggregate.resolve_raw_affiliations


def compute_gates(ed, works):
    cfg = ed.config
    affil_map, resolve = load_affiliation_map()
    slots = with_aff = with_inst = with_edu = 0
    map_resolved = pdf_slots = pdf_resolved = 0
    papers_full = papers_any = byline_mismatch = 0
    leaks = bad_scope = 0
    for w in works:
        auths = w["authorships"]
        covered = 0
        for a in auths:
            slots += 1
            if "profile_affiliations" in a or (a.get("affiliation_source") and a["affiliation_source"] not in AFFILIATION_SOURCES):
                leaks += 1
            if a.get("institutions") or a.get("raw_affiliations"):
                with_aff += 1
                covered += 1
                insts = a.get("institutions") or []
                if not insts:
                    # aggregate.py resolves raw strings through the curated
                    # map only when institutions is empty; mirror that here.
                    insts = resolve(a.get("raw_affiliations") or [], affil_map)
                    map_resolved += bool(insts)
                with_inst += bool(insts)
                with_edu += any(i.get("type") == "education" for i in insts)
                if a.get("affiliation_source") in ("publisher-pdf", "publisher-pdf-image"):
                    pdf_slots += 1
                    pdf_resolved += bool(insts)
        papers_full += bool(auths) and covered == len(auths)
        papers_any += covered > 0
        byline_mismatch += any("byline_mismatch" in r["reasons"] for r in w["evidence"]["rejected"]) and not w["evidence"].get("source")
        m = w.get("membership") or {}
        bad_scope += not m.get("membership_id") or m.get("track") not in cfg["include_tracks"]
    n = len(works)
    gates = {}
    anchors = []
    for exp in cfg.get("expected", []):
        if exp["scope"] == "included":
            have = n
        elif exp["scope"] == "all":
            have = len(read_jsonl(ed.membership_path))
        else:
            track = exp["scope"].split(":", 1)[1]
            have = sum(w["membership"]["track"] == track for w in works)
        anchors.append({**exp, "have": have, "diff": have - exp["count"], "rel_diff": round(abs(have - exp["count"]) / exp["count"], 5)})
    included_anchors = [a for a in anchors if a["scope"] in ("included",) or a["scope"].startswith("track:")]
    gates["membership"] = {
        "anchors": anchors,
        "rows_without_membership_or_allowed_track": bad_scope,
        "pass": bool(included_anchors) and bad_scope == 0 and
                all(a["rel_diff"] <= GATES["membership_unexplained_diff_max"] for a in included_anchors),
        "note": "No included-track anchor configured; membership cannot pass." if not included_anchors else None,
    }
    aff_rate = with_aff / slots if slots else 0.0
    gates["paper_specific_affiliations"] = {
        "author_slots": slots, "slots_with_affiliation": with_aff, "rate": round(aff_rate, 4),
        "papers": n, "papers_fully_covered": papers_full, "papers_any_coverage": papers_any,
        "threshold": GATES["author_slot_affiliation_min"], "pass": aff_rate >= GATES["author_slot_affiliation_min"],
    }
    res_rate = with_inst / with_aff if with_aff else 0.0
    gates["institution_resolution"] = {
        "slots_with_affiliation": with_aff, "slots_with_institution": with_inst, "slots_with_education_institution": with_edu,
        "resolved_via_affiliation_map": map_resolved, "pdf_slots": pdf_slots, "pdf_slots_resolved": pdf_resolved,
        "note": "PDF strings resolve only after normalize_semantic.py adds them to data/affiliation-map.csv." if pdf_slots > pdf_resolved else None,
        "rate": round(res_rate, 4), "threshold": GATES["institution_resolution_min"],
        "pass": res_rate >= GATES["institution_resolution_min"],
    }
    dup = (ed.state.get("build") or {}).get("counts", {}).get("duplicate_work_keys", 0)
    gates["byline_integrity"] = {"papers_without_evidence_due_to_byline_mismatch": byline_mismatch,
                                 "empty_bylines": sum(not w["authorships"] for w in works),
                                 "pass": all(w["authorships"] for w in works)}
    gates["scope_purity"] = {"duplicate_work_keys": dup, "pass": dup == 0 and bad_scope == 0,
                             "audit_sample": str(ed.dir / "audit-sample.jsonl")}
    gates["profile_leakage"] = {"author_slots_with_profile_or_unknown_source": leaks, "pass": leaks == 0}
    pdf_state = (ed.state.get("pdf") or {}).get("counts", {})
    gates["pdf_evidence"] = {
        "papers_extracted": pdf_state.get("extracted", 0),
        "confidence": {k.split(":", 1)[1]: v for k, v in pdf_state.items() if k.startswith("confidence:")},
        "review_queue": pdf_state.get("review_queue", 0),
        "review_queue_path": str(ed.dir / "pdf-review.jsonl"),
        "pdf_openalex_conflict_slots": sum(len(w["evidence"].get("pdf_openalex_conflicts") or []) for w in works),
        "credited_confidence_levels": sorted(PDF_ACCEPT), "prefer_pdf": ed.prefer_pdf,
        "slots_from_image": sum(a.get("affiliation_source") == "publisher-pdf-image" for w in works for a in w["authorships"]),
        # Informational: conflicts and the review queue need human review but
        # do not by themselves block the edition.
        "pass": True,
    }
    rows = {r["paper_key"]: r for r in read_jsonl(ed.pdf_verify_path)}
    accuracy, correct, wrong = pdf_verify.sample_accuracy(rows)
    gates["pdf_verification"] = {
        "sample_papers_checked": sum(1 for r in rows.values() if r["kind"] == "sample"),
        "extractor_slots_correct": correct, "extractor_slots_wrong": wrong,
        "extractor_accuracy": round(accuracy, 4) if accuracy is not None else None,
        "threshold": PDF_TEXT_ACCURACY_MIN,
        "review_papers_read_from_image": sum(1 for r in rows.values() if r["kind"] == "review"),
        "conflict_papers_checked": sum(1 for r in rows.values() if r["kind"] == "conflict"),
        "judge_model": sorted({r.get("model") for r in rows.values() if r.get("model")}),
        "pass": accuracy is not None and accuracy >= PDF_TEXT_ACCURACY_MIN,
        "note": None if accuracy is not None else "Image verification not run: --stage verify-prep, then the verify-pdf-affiliations skill, then --stage verify-apply",
    }
    return gates


def stage_gates(ed):
    works = read_jsonl(ed.works_path)
    gates = compute_gates(ed, works)
    sample = sorted(works, key=lambda w: hashlib.sha256(w["id"].encode()).hexdigest())[:100]
    atomic_write_lines(ed.dir / "audit-sample.jsonl",
                       [{"id": w["id"], "title": w["title"], "track": w["membership"]["track"],
                         "url": w["membership"]["membership_url"], "authors": [a["author_name"] for a in w["authorships"]],
                         "evidence": w["evidence"].get("source")} for w in sample])
    passed = all(g["pass"] for g in gates.values())
    ed.mark("gates", True, Counter(passed=int(passed)))
    ed.state["gates"]["gates"] = gates
    ed.state["gates"]["gates_passed"] = passed
    ed.save_state()
    return gates, passed


def write_manifest(manifest_path, ed, stats):
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    gates_entry = ed.state.get("gates") or {}
    passed = bool(gates_entry.get("gates_passed"))
    all_done = all(ed.is_done(s) for s in STAGES)
    row = {
        "venue": ed.venue, "year": ed.year,
        "status": "complete" if (all_done and passed) else "staged",
        "sha256": sha256_file(ed.works_path), "path": str(ed.works_path.relative_to(ROOT)) if ed.works_path.is_relative_to(ROOT) else str(ed.works_path),
        "works": len(read_jsonl(ed.works_path)), "membership_source": ed.config["url"],
        "include_tracks": ed.config["include_tracks"],
        "stages": {s: {k: v for k, v in (ed.state.get(s) or {}).items() if k != "gates"} for s in STAGES},
        "gates": gates_entry.get("gates"), "gates_passed": passed,
        "http_last_run": stats,
    }
    results = [r for r in manifest.get("results", []) if (r.get("venue"), r.get("year")) != (ed.venue, ed.year)]
    results.append(row)
    manifest.update({
        "generated_at": utc_now(), "provider": "harvest_ml.py",
        "membership_semantics": "Rows come only from the publisher's official edition list; track filter applied at build.",
        "affiliation_semantics": "Only paper-specific evidence populates raw_affiliations/institutions: OpenAlex work-author joins for the publisher DOI or an identity-checked arXiv twin, and the author block of the final publisher PDF (affiliation_source records which, per author). Semantic Scholar supplies arXiv identifiers only; no author-profile affiliations are stored.",
        "status_semantics": "status is 'complete' only when every stage is done and every gate passes; otherwise 'staged'.",
        "gate_thresholds": GATES,
        "results": sorted(results, key=lambda r: (r["venue"], r["year"])),
    })
    atomic_write_json(manifest_path, manifest)
    return row


def pdf_verification_reminder(ed):
    """Text telling the agent reading this output to run image verification.

    None once every review-queue paper and the accuracy sample have been
    verified and applied. Printed after the pdf stage on every run until then,
    because the pdf_verification gate fails without it.
    """
    review = {r["paper_key"] for r in read_jsonl(ed.dir / "pdf-review.jsonl")}
    verified = {r["paper_key"]: r for r in read_jsonl(ed.pdf_verify_path)}
    sample_done = any(r["kind"] == "sample" for r in verified.values())
    if review <= set(verified) and sample_done:
        return None
    status = pdf_verify.status(ed)
    prepared = pdf_verify.paths(ed)["batches"].exists()
    cmd = f"python3 pipeline/harvest_ml.py --venue {ed.venue} --year {ed.year}"
    lines = ["=" * 78,
             "NEXT REQUIRED STEP: image-verify the PDF-extracted affiliations",
             f"  review queue: {len(review)} papers the text parser did not fully resolve; "
             f"verified so far: {len(review & set(verified))}; accuracy sample: {'done' if sample_done else 'not run'}"]
    if prepared and status["pending_batches"]:
        lines.append(f"  prepared and pending: {status['pending_batches']} batches / {status['pending_images']} images "
                     f"{status['by_kind']}")
    else:
        lines.append(f"  1. {cmd} --stage verify-prep")
    lines += [f"  {'2' if not (prepared and status['pending_batches']) else '1'}. run the verify-pdf-affiliations skill "
              "(it asks the user which subagent model and how much to run)",
              f"  {'3' if not (prepared and status['pending_batches']) else '2'}. {cmd} --stage verify-apply, then --stage build",
              "  Until then the pdf_verification gate fails and this edition stays 'staged'.",
              "=" * 78]
    return "\n".join(lines)


def stage_normalize(ed, stage_root):
    """Resolve this edition's new raw strings into data/affiliation-map.csv.

    Writes the shared map, so it is never part of --stage all and refuses to
    start while another map writer is running.
    """
    others = subprocess.run(["pgrep", "-af", "normalize_|fix_acronym|fix_name|fix_campus|adjudication.py"],
                            capture_output=True).stdout.decode().splitlines()
    others = [line for line in others if "pgrep" not in line and str(os.getpid()) != line.split()[0]]
    if others:
        raise HarvestError("another affiliation-map writer is running: " + "; ".join(others)[:300])
    venv = ROOT / ".venv" / "bin" / "python"
    if venv.exists():
        cmd = [str(venv), str(ROOT / "pipeline" / "normalize_semantic.py")]
    else:
        print("  .venv not found: using the stdlib normalizer (normalize_affiliations_local.py)")
        cmd = [sys.executable, str(ROOT / "pipeline" / "normalize_affiliations_local.py")]
    cmd += ["--cache-dir", str(Path(stage_root) / "cache"), "--venue", ed.venue, "--year", str(ed.year)]
    print("  " + " ".join(cmd), flush=True)
    if subprocess.run(cmd, cwd=ROOT).returncode != 0:
        raise HarvestError("normalizer failed")
    return {"normalizer": Path(cmd[1]).name}


def reconcile_openreview(ed):
    venueid = ed.config.get("openreview_venueid")
    if not venueid:
        raise HarvestError("No openreview_venueid configured for this edition")
    notes = openreview_notes(ed.fetcher, venueid, ed.env_path)
    members = ed.included()
    by_title = {norm_title(m["title"]): m for m in members}
    or_titles = {norm_title(n["title"]): n for n in notes}
    only_or = [n for t, n in or_titles.items() if t not in by_title]
    only_pub = [m for t, m in by_title.items() if t not in or_titles]
    report = {"checked_at": utc_now(), "openreview_venueid": venueid, "openreview_notes": len(notes),
              "publisher_rows": len(members), "only_in_openreview": only_or, "only_in_publisher":
              [{k: m[k] for k in ("paper_key", "title", "membership_url")} for m in only_pub]}
    atomic_write_json(ed.dir / "openreview-reconciliation.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--venue", required=True, choices=("iclr", "icml", "neurips"))
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--stage", default="all",
                        choices=STAGES + ("all", "reconcile-openreview", "normalize", "verify-prep", "verify-status", "verify-apply"))
    parser.add_argument("--stage-root", type=Path, default=DEFAULT_STAGE_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--max-list-calls", type=int, default=80, help="OpenAlex list-call budget for this run")
    parser.add_argument("--max-search-calls", type=int, default=400,
                        help="Cap OpenAlex title-search calls this run (10 credits = $0.001 each)")
    parser.add_argument("--s2-match", action="store_true",
                        help="Also try S2 per-title match (impractical without S2_API_KEY in .env)")
    parser.add_argument("--max-match-calls", type=int, default=None, help="Cap S2 title-match calls this run")
    parser.add_argument("--restart-stage", choices=STAGES, default=None,
                        help="Discard this stage's outputs (and invalidate later stages) before running")
    parser.add_argument("--offline", action="store_true", help="Use only cached HTTP responses")
    parser.add_argument("--pdf-workers", type=int, default=PDF_WORKERS,
                        help="Parallel PDF downloads (4 reached ~8 PDFs/s on proceedings.iclr.cc, no throttling)")
    parser.add_argument("--keep-pdfs", action="store_true", help="Keep every downloaded PDF, not just review-queue ones")
    parser.add_argument("--prefer-openalex", action="store_true",
                        help="Credit OpenAlex over PDF affiliations where both exist (default: PDF first, decided 2026-10-30)")
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    verify = parser.add_argument_group(
        "image verification (verify-prep / verify-status / verify-apply)",
        "The image reading itself is done by an agent through the verify-pdf-affiliations skill, "
        "on the user's Claude Code subscription; this script only prepares batches and applies results.")
    verify.add_argument("--verify-sample", type=int, default=pdf_verify.DEFAULT_SAMPLE,
                        help="High-confidence papers sampled to measure extractor accuracy")
    verify.add_argument("--verify-batch", type=int, default=pdf_verify.DEFAULT_BATCH, help="Images per subagent")
    verify.add_argument("--verify-limit", type=int, default=None, help="Only the first N tasks (pilots)")
    args = parser.parse_args(argv)

    fetcher = Fetcher(args.stage_root / "raw", offline=args.offline)
    try:
        ed = Edition(args.venue, args.year, args.stage_root, fetcher, args.env)
        ed.prefer_pdf = not args.prefer_openalex
        if args.stage == "reconcile-openreview":
            report = reconcile_openreview(ed)
            print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in report.items()}, indent=2))
            return 0
        if args.stage == "normalize":
            print(json.dumps(stage_normalize(ed, args.stage_root)))
            print("  next: harvest_ml.py --stage gates (resolution), then the adjudicate-affiliations skill")
            return 0
        if args.stage == "verify-prep":
            if not ed.works_path.exists():
                raise HarvestError("verify-prep needs a build first (--stage build)")
            counts = pdf_verify.prep(ed, read_jsonl(ed.works_path), args.verify_sample, args.verify_batch,
                                     args.pdf_workers, download_pdf, args.keep_pdfs, args.verify_limit)
            print(json.dumps(dict(counts), indent=2, sort_keys=True))
            print("  next: the verify-pdf-affiliations skill reads the batches with subagents, then --stage verify-apply")
            return 0
        if args.stage == "verify-status":
            print(json.dumps(pdf_verify.status(ed), indent=1))
            return 0
        if args.stage == "verify-apply":
            counts, _ = pdf_verify.apply(ed)
            print(json.dumps(dict(counts), indent=2, sort_keys=True))
            print("  next: --stage build, then --stage gates")
            return 0
        if args.restart_stage:
            outputs = {"membership": [ed.membership_path], "discover": [ed.discovery_path, ed.dir / "title-search-misses.jsonl"],
                       "enrich": [ed.openalex_path], "pdf": [ed.pdf_extract_path],
                       "build": [ed.works_path], "gates": []}
            for stage in STAGES[STAGES.index(args.restart_stage):]:
                ed.state.pop(stage, None)
            for path in outputs[args.restart_stage]:
                if path.exists():
                    path.unlink()
            ed.save_state()
        stages = STAGES if args.stage == "all" else (args.stage,)
        key = load_key(args.env)
        for stage in stages:
            if ed.is_done(stage) and stage != "gates":
                print(f"[{args.venue}/{args.year}] {stage}: up to date")
                if stage == "pdf" and (reminder := pdf_verification_reminder(ed)):
                    print(reminder, flush=True)
                continue
            if args.offline and stage == "enrich" and not ed.is_done("enrich"):
                raise HarvestError("--offline cannot run an incomplete enrich stage")
            print(f"[{args.venue}/{args.year}] {stage} ...", flush=True)
            if stage == "membership":
                result = stage_membership(ed)
            elif stage == "discover":
                result = stage_discover(ed, key, args.max_search_calls, args.s2_match, args.max_match_calls)
            elif stage == "enrich":
                result = stage_enrich(ed, key, args.max_list_calls)
            elif stage == "pdf":
                result = stage_pdf(ed, args.pdf_workers, args.keep_pdfs, args.offline)
            elif stage == "build":
                result = stage_build(ed)
            else:
                gates, passed = stage_gates(ed)
                result = {name: g["pass"] for name, g in gates.items()}
                result["all_passed"] = passed
            print(json.dumps(dict(result), indent=2, sort_keys=True))
            if stage == "pdf" and ed.is_done("pdf") and (reminder := pdf_verification_reminder(ed)):
                print(reminder, flush=True)
            if not ed.is_done(stage):
                print(f"[{args.venue}/{args.year}] {stage} incomplete; later stages not run", file=sys.stderr)
                break
        row = write_manifest(args.manifest, ed, dict(fetcher.stats))
        print(f"[{args.venue}/{args.year}] manifest status={row['status']} gates_passed={row['gates_passed']} works={row['works']}")
    except (HarvestError, RefreshError, pdf_verify.VerifyError) as exc:
        print(f"harvest_ml: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
