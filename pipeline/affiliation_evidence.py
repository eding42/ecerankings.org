#!/usr/bin/env python3
"""Evidence inside a raw affiliation string that a name match ignores.

A matcher compares names. The string usually says more: the country it ends
with, and whether it describes a company. Ignoring that produced these, all
live in the published rankings on 2026-11-12:

  'Southeast University,Nanjing,China'        -> Southeast University (BD)
  'Korea University,Seoul,Korea'              -> Korea University (JP)
  'Imperial College, ..., London, UK'         -> Imperial Valley College (US)
  'Sony Semiconductor ... Corporation,Kanagawa,Japan' -> Kanagawa University

Shared by the normalizers (to stop producing such rows), adjudication.py check
and verify_global.py (to find them), and fix_country_mismatches.py (to propose
repairs). Python stdlib only.
"""

import html
import re
import unicodedata
from collections import defaultdict

# Country names as they appear at the end of affiliation strings.
_COUNTRY_PATTERNS = {
    "US": r"USA|U\.S\.A\.?|United States", "GB": r"UK|U\.K\.?|United Kingdom|England|Scotland|(?<!South )Wales",
    "CN": r"China|P\.?R\.? ?China|PRC", "AU": r"Australia", "CA": r"Canada", "DE": r"Germany|Deutschland",
    "FR": r"France", "JP": r"Japan", "KR": r"Korea|South Korea|Republic of Korea", "IN": r"India",
    "IT": r"Italy|Italia", "ES": r"Spain|España", "NL": r"Netherlands", "CH": r"Switzerland",
    "SG": r"Singapore", "TW": r"Taiwan", "HK": r"Hong Kong", "BR": r"Brazil|Brasil", "SE": r"Sweden",
    "IL": r"Israel", "IR": r"Iran", "TR": r"Turkey|Türkiye", "BE": r"Belgium", "AT": r"Austria",
    "DK": r"Denmark", "FI": r"Finland", "NO": r"Norway", "PL": r"Poland", "PT": r"Portugal",
    "GR": r"Greece", "IE": r"Ireland", "BD": r"Bangladesh", "PK": r"Pakistan", "EG": r"Egypt",
    "MX": r"(?<!New )Mexico|México", "SA": r"Saudi Arabia", "AE": r"UAE|United Arab Emirates", "NZ": r"New Zealand",
    "MY": r"Malaysia", "TH": r"Thailand", "VN": r"Viet ?nam", "RU": r"Russia", "ZA": r"South Africa",
    "PH": r"Philippines", "ID": r"Indonesia", "CL": r"Chile", "AR": r"Argentina", "CO": r"Colombia",
}
COUNTRY_RES = {cc: re.compile(rf"\b(?:{pattern})\b") for cc, pattern in _COUNTRY_PATTERNS.items()}
# Strings and records that legitimately name either side of these pairs.
COUNTRY_EQUIVALENT = {frozenset(p) for p in (("CN", "HK"), ("CN", "TW"), ("CN", "MO"), ("GB", "IE"))}
COUNTRY_TAIL = 60            # a country at the end of the string is the author's own

COMPANY_RE = re.compile(
    r"\b(?:Ltd\.?|Limited|Inc\.?|GmbH|Corp\.?|Corporation|Co\.,?|LLC|S\.A\.|AG|B\.V\.|Pte)(?=[\s,.;)]|$)")
ACADEMIC_RE = re.compile(
    r"univ|college|institut|school|academy|polytech|politec|faculty|facult|department|dept|laborator|hochschule",
    re.I)


# Words that mark a string as an academic unit. Generic ones ("laboratory",
# "research", "center") are left out on purpose: companies use them too.
STRONG_ACADEMIC_RE = re.compile(
    r"univ|college|polytech|politec|hochschule|\becole\b|escuela|scuola|daigaku|hogeschool|academ|akadem|"
    r"institute of tech|institut[eo]? (?:of|de|for|di) |institut(?:o)? tecn|school of|faculty|facult|"
    r"departement|dipartimento|departamento|\bcnrs\b|\binria\b")


def fold(text):
    """ASCII, lowercase, single-spaced; HTML entities decoded first."""
    text = unicodedata.normalize("NFKD", html.unescape(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def academic_evidence(raw, inst):
    """True when the raw string gives a reason to credit a university: an
    academic word, or the institution's own name, alternative or acronym.

    A string with neither ("Akita Software, Palo Alto, CA") was matched on a
    city or a fragment, not on the institution. `inst` is the index record.
    """
    folded = fold(raw)
    if STRONG_ACADEMIC_RE.search(folded):
        return True
    padded = f" {folded} "
    for name in [inst.get("display_name")] + list(inst.get("alternatives") or []) + list(inst.get("acronyms") or []):
        name = fold(name)
        if len(name) >= 3 and f" {name} " in padded:
            return True
    return False


def countries_named(raw):
    """Country codes named at the end of a raw affiliation string."""
    tail = raw[-COUNTRY_TAIL:]
    return {cc for cc, pattern in COUNTRY_RES.items() if pattern.search(tail)}


def country_contradiction(raw, mapped_cc):
    """Return the named countries when they exclude the mapped institution's."""
    if not mapped_cc:
        return None
    named = countries_named(raw)
    if not named or mapped_cc in named:
        return None
    if any(frozenset((mapped_cc, cc)) in COUNTRY_EQUIVALENT for cc in named):
        return None
    return named


def looks_like_company(raw):
    return bool(COMPANY_RE.search(raw)) and not ACADEMIC_RE.search(raw)


def build_name_index(by_id):
    """lowercased name or alternative -> ids of education institutions."""
    index = defaultdict(set)
    for iid, inst in by_id.items():
        if inst.get("type") != "education":
            continue
        for name in [inst.get("display_name")] + list(inst.get("alternatives") or []):
            if name:
                index[name.strip().lower()].add(iid)
    return index


def same_name_abroad(raw, row, by_id, name_index):
    """The one education institution sharing the matched name in the country
    the string names, or None when there is none or more than one."""
    named = country_contradiction(raw, row.get("country_code", ""))
    if not named:
        return None
    keys = {(row.get("matched_via") or "").strip().lower(), (row.get("institution_name") or "").strip().lower()}
    found = {iid for key in keys if key for iid in name_index.get(key, ())
             if (by_id[iid].get("country_code") or "") in named}
    return by_id[next(iter(found))] if len(found) == 1 else None


def guard_row(raw, row, by_id, name_index):
    """Hold a freshly matched row to the string's own evidence. Mutates and
    returns `row`. Only auto-accepted education matches are touched.

    - Country contradiction, and exactly one same-named education institution
      in the named country: switch to it.
    - Country contradiction otherwise: demote to review.
    - Company string: demote to review.
    - No academic word and no trace of the institution's name: demote to review.
    """
    if row.get("status") != "auto" or row.get("institution_type") != "education":
        return row
    if country_contradiction(raw, row.get("country_code", "")):
        other = same_name_abroad(raw, row, by_id, name_index)
        if other:
            row.update(institution_id=other["id"], institution_name=other["display_name"],
                       institution_type=other.get("type") or "", country_code=other.get("country_code") or "",
                       lineage="|".join(other.get("lineage") or [other["id"]]))
        else:
            row["status"] = "review"
    elif looks_like_company(raw):
        row["status"] = "review"
    else:
        inst = by_id.get(row.get("institution_id"))
        if inst and not academic_evidence(raw, inst):
            row["status"] = "review"
    return row
