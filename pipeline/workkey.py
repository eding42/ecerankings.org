#!/usr/bin/env python3
"""Stable identity for a cached work, shared by every script that needs to
name one work across files.

Two scripts independently normalizing DOIs is how an exclusion list silently
stops matching: one lowercases, the other doesn't, and the mismatch looks like
"the exclusion didn't apply" rather than a bug. Everything that keys on a work
imports from here.

DOI is the identifier where one exists, but 2.6% of cached works have none --
and short commentary, which is exactly what the exclusion list targets, is
over-represented among them. So the fallback is (venue, year, title), which is
stable for a given cache but NOT portable across a re-harvest that changes
titles. Prefer DOI keys when curating by hand.
"""

import re

_DOI_PREFIX = re.compile(r"^https?://(dx\.)?doi\.org/", re.I)
_TITLE_TAGS = re.compile(r"<[^>]+>")          # OpenAlex titles carry <i>, <sub>, ...
_TITLE_NOISE = re.compile(r"[^a-z0-9]+")


def norm_doi(doi):
    """Lowercase, strip the resolver prefix. Returns None for empty input."""
    if not doi:
        return None
    d = _DOI_PREFIX.sub("", str(doi).strip().lower())
    return d or None


def norm_title(title):
    """Collapse a title to a comparison key: markup stripped, alphanumerics only."""
    if not title:
        return ""
    t = _TITLE_TAGS.sub(" ", str(title)).lower()
    return _TITLE_NOISE.sub("-", t).strip("-")


def work_key(work, venue=None, year=None):
    """Return a single stable string identifying `work`.

    'doi:<normalized>'            when the work has a DOI
    'vt:<venue>|<year>|<title>'   otherwise

    `venue` and `year` are only consulted for the fallback form; pass them
    whenever available so no-DOI works remain addressable.
    """
    d = norm_doi(work.get("doi"))
    if d:
        return "doi:" + d
    yr = year if year is not None else work.get("publication_year")
    return f"vt:{venue or '?'}|{yr or '?'}|{norm_title(work.get('title'))}"
