#!/usr/bin/env python3
"""Extract per-author affiliations from the first page of a final proceedings PDF.

The publisher PDF is the version of record, so its author block is paper-specific
affiliation evidence for every byline author it names. The publisher byline
(from the membership list) is authoritative for who the authors are and in what
order; this module only finds each of those authors on the page and reads the
affiliation text attached to them. Nothing here invents an author.

Text comes from poppler's `pdftotext -layout` (a system binary, not a pip
install). Layout mode keeps the side-by-side author columns in reading order;
plain mode scrambles them.

Two layouts cover ICLR-style headers:

  columns   Name / affiliation lines / email stacked in side-by-side columns.
            Several names in one block over one affiliation is the shared form.
  markers   Names carry superscript marks ("Lu1,3,*", "Ye1†"), followed by an
            affiliation list keyed by the same marks ("1 Tencent AI Lab 2 Peking
            University"). pdftotext often puts a mark on its own line above the
            text it labels.

Each result carries a confidence: "high" when every byline author is anchored
and has at least one affiliation, "partial" when some are, "none" otherwise.
Anything below "high" belongs in a review queue, not in automatic credit.
"""
from __future__ import annotations

import re
import subprocess
import unicodedata

PDFTOTEXT = "pdftotext"
# Bump when extraction logic changes; harvest_ml re-extracts stored text.
EXTRACTOR_VERSION = 2

_ABSTRACT = re.compile(r"^\s*A\s*B\s*S\s*T\s*R\s*A\s*C\s*T\b", re.I)
_EMAIL = re.compile(r"@|\{[^}]*\}\s*@|^\s*e-?mail", re.I)
_NOISE = re.compile(r"(equal contribution|corresponding author|project page|code is available|https?://|github\.com|work done|denotes|∗ ?equal)", re.I)
# Superscript marks as pdftotext renders them. 'B' is the envelope glyph that
# many templates use for corresponding authors; it never labels an affiliation.
_SYMBOLS = "†‡§¶*∗♣♠♡♢♦♥⋆★☆◦•‖#°♯♮♭↿⇂⊥⊤⊣⊢∇△▽◇◆□■○●⋄⊕⊗※¤"
_SYM = re.escape(_SYMBOLS)
# A repeated symbol is its own mark: "††" labels a different affiliation
# from "†". Matched with finditer; group(0) is the whole mark.
_MARK_TOKEN = re.compile(r"\d{1,2}|([" + _SYM + r"])\1*|B(?![A-Za-z])")
_MARK = r"(?:\d{1,2}|[" + _SYM + r"]+|B(?![A-Za-z]))"
_MARK_RUN = re.compile(r"^[\s,]*(" + _MARK + r"(?:[\s,]*" + _MARK + r")*)")
_AFFIL_MARK = re.compile(r"(?:(?<=\s)|^)(\d{1,2}|([" + _SYM + r"])\2*)\s+(?=[A-Z])")
_SEGMENT_GAP = re.compile(r"\s{3,}")


def first_page_text(pdf_path, timeout=60):
    """Layout-mode text of page 1, or '' when the PDF has no extractable text."""
    result = subprocess.run([PDFTOTEXT, "-f", "1", "-l", "1", "-layout", str(pdf_path), "-"],
                            capture_output=True, timeout=timeout)
    return result.stdout.decode("utf8", "replace") if result.returncode == 0 else ""


def fold(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def header_lines(text):
    """Lines above the Abstract heading, minus the running header."""
    lines = []
    for line in text.splitlines():
        if _ABSTRACT.match(line):
            return lines, True
        lines.append(line.rstrip())
    return lines, False


def segments(line):
    """Split a layout line into (start, end, text) column segments."""
    out, pos = [], 0
    for part in _SEGMENT_GAP.split(line):
        start = line.find(part, pos) if part else pos
        if part.strip():
            lead = len(part) - len(part.lstrip())
            out.append((start + lead, start + len(part.rstrip()), part.strip()))
        pos = start + len(part)
    return out


def _name_pattern(name):
    """Regex for an author name on the page: tokens in order, flexible gaps.

    Falls back to the surname alone because listings and PDFs disagree on
    middle names and particles ("Tiago Silva" vs "Tiago da Silva")."""
    toks = fold(name).split()
    if not toks:
        return None, None
    full = r"\b" + r"\W+(?:\w+\W+){0,2}?".join(map(re.escape, toks)) + r"\b"
    return re.compile(full), re.compile(r"\b" + re.escape(toks[-1]) + r"\b")


def _folded_with_map(text):
    """fold() that also returns, per folded char, its index in the source."""
    out, index = [], []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKD", ch):
            if unicodedata.combining(c):
                continue
            c = c.casefold()
            # Digits become gaps: superscripts are glued to names ("Lu1,3").
            if not re.match(r"[a-z]", c):
                c = " "
            out.append(c)
            index.append(i)
    return "".join(out), index


def locate_authors(lines, authors, start_line=0):
    """Find each byline author's (line, col_start, col_end), in byline order."""
    found = [None] * len(authors)
    cursor = (start_line, 0)
    for k, name in enumerate(authors):
        full, surname = _name_pattern(name)
        if not full:
            continue
        for pattern in (full, surname):
            hit = None
            for li in range(cursor[0], len(lines)):
                folded, index = _folded_with_map(lines[li])
                begin = cursor[1] if li == cursor[0] else 0
                fbegin = next((j for j, src in enumerate(index) if src >= begin), len(folded))
                m = pattern.search(folded, fbegin)
                if m:
                    hit = (li, index[m.start()], index[m.end() - 1] + 1)
                    break
            if hit:
                found[k] = hit
                cursor = (hit[0], hit[2])
                break
    return found


def _clean_affiliation(text):
    text = re.sub(r"\b(?:https?://|www\.)\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;.")
    # Marks of the next entry left dangling at the end ("...of China 1 3").
    text = re.sub(r"(?:[\s,]+(?:\d{1,2}|[" + _SYM + r"]+))+$", "", text).strip(" ,;.")
    text = re.sub(r"^(and|&)\s+", "", text, flags=re.I)
    return text


def parse_markers(lines, authors, found):
    """Superscript layout. Returns {author_index: [affiliation, ...]} or None."""
    located = [f for f in found if f]
    if not located:
        return None
    last_name_line = max(f[0] for f in located)
    marks_by_author = {}
    for k, f in enumerate(found):
        if not f:
            continue
        li, _, end = f
        tail = lines[li][end:]
        # The PDF byline may carry name tokens the listing omits before the
        # marks ("Dung Nguyen Manh†"); skip up to two of them.
        tail = re.sub(r"^(?:\s*[A-Z][\w.'’-]*(?=[\s\d" + _SYM + r",]|$)){0,2}", "", tail)
        m = _MARK_RUN.match(tail)
        marks = [t.group(0) for t in _MARK_TOKEN.finditer(m.group(1)) if t.group(0) != "B"] if m else []
        marks_by_author[k] = marks
    if sum(1 for v in marks_by_author.values() if v) < max(1, len(located) // 2):
        return None
    body, blanks = [], 0
    for line in lines[last_name_line + 1:]:
        if not line.strip():
            blanks += 1
            # A wide gap after the affiliation list ends the author block;
            # what follows is a teaser figure or its caption.
            if blanks >= 2 and any(body):
                break
            if body and body[-1] != "":
                body.append("")
            continue
        blanks = 0
        if _EMAIL.search(line) or _NOISE.search(line):
            continue
        body.append(line.strip())
    text = " ".join(x for x in body if x)
    text = " " + text
    hits = list(_AFFIL_MARK.finditer(text))
    affiliations = {}
    for n, hit in enumerate(hits):
        stop = hits[n + 1].start() if n + 1 < len(hits) else len(text)
        mark, value = hit.group(1), _clean_affiliation(text[hit.end():stop].split(";")[0])
        if value and len(value) > 2:
            affiliations.setdefault(mark, value)
    if not affiliations:
        return None
    result = {}
    for k, marks in marks_by_author.items():
        values = [affiliations[m] for m in marks if m in affiliations]
        if values:
            result[k] = list(dict.fromkeys(values))
    # One affiliation, no marks on names: everyone shares it.
    if not result and len(affiliations) == 1:
        only = next(iter(affiliations.values()))
        result = {k: [only] for k in marks_by_author}
    return result


def parse_columns(lines, authors, found):
    """Column-block layout. Returns {author_index: [affiliation, ...]}."""
    result = {}
    name_lines = {f[0] for f in found if f}
    for k, f in enumerate(found):
        if not f:
            continue
        li, start, end = f
        # The author's column is the segment containing the name.
        seg = next(((s, e, t) for s, e, t in segments(lines[li]) if s <= start < e + 1), None)
        if not seg:
            continue
        col = (seg[0], seg[1])
        collected = []
        for lj in range(li + 1, min(len(lines), li + 8)):
            line = lines[lj]
            if not line.strip():
                if collected:
                    break
                continue
            # A segment belongs to this column when at least half of the
            # narrower of the two overlaps; a long string from the next
            # column that merely touches it does not.
            hits = [(s, e, t) for s, e, t in segments(line)
                    if min(e, col[1]) - max(s, col[0]) >= 0.5 * max(1, min(e - s, col[1] - col[0]))]
            if not hits:
                continue
            text = " ".join(t for _, _, t in hits)
            if _EMAIL.search(text):
                break
            # Another author's name in this column starts the next block.
            if lj in name_lines and any(g and g[0] == lj and g[1] < col[1] + 2 and g[2] > col[0] - 2 for g in found):
                break
            if _NOISE.search(text):
                continue
            collected.append(text)
        if collected:
            result[k] = [_clean_affiliation(", ".join(collected))]
    return result


def extract(text, authors):
    """Map byline authors to affiliation strings from first-page layout text.

    Returns {"layout", "confidence", "affiliations": [[str, ...] per author],
             "anchored": n, "reason"}.
    """
    lines, saw_abstract = header_lines(text)
    out = {"layout": None, "confidence": "none", "affiliations": [[] for _ in authors],
           "anchored": 0, "reason": None}
    if not text.strip():
        out["reason"] = "no extractable text (image-only PDF?)"
        return out
    if not saw_abstract:
        out["reason"] = "abstract heading not found"
        return out
    found = locate_authors(lines, authors)
    out["anchored"] = sum(1 for f in found if f)
    if not out["anchored"]:
        out["reason"] = "no byline author found on page"
        return out
    mapping, layout = parse_markers(lines, authors, found), "markers"
    if not mapping:
        mapping, layout = parse_columns(lines, authors, found), "columns"
    out["layout"] = layout
    for k, values in (mapping or {}).items():
        # A stray mark or digit is not an affiliation.
        values = [v for v in values if re.search(r"[A-Za-z]{3}", v)]
        if values:
            out["affiliations"][k] = values
    covered = sum(1 for v in out["affiliations"] if v)
    if covered == len(authors) and out["anchored"] == len(authors):
        out["confidence"] = "high"
    elif covered:
        out["confidence"] = "partial"
        out["reason"] = f"{covered}/{len(authors)} authors with affiliations, {out['anchored']} anchored"
    else:
        out["reason"] = "authors anchored but no affiliation text attached"
    return out


# Generic words that say nothing about which institution a string names.
_GENERIC = set("""university univ of the and for in at department dept school college institute
institution lab laboratory labs center centre research inc ltd llc co corp company group national
key state science sciences technology engineering computer electrical faculty division program
graduate usa us uk china germany france japan korea canada india singapore""".split())


def strings_agree(left, right):
    """Do two lists of affiliation strings plausibly name the same place?

    True on an exact folded match or any shared distinctive token. Used to flag
    PDF-vs-OpenAlex conflicts for review, never to decide credit.
    """
    lf, rf = {fold(x) for x in left if x}, {fold(x) for x in right if x}
    if lf & rf:
        return True
    tokens = lambda xs: {t for x in xs for t in fold(x).split() if len(t) >= 3 and t not in _GENERIC}  # noqa: E731
    return bool(tokens(left) & tokens(right))
