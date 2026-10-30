"""Secondary S2 discovery only; never emits membership or ranking authorships.

Raw responses (including any unexpected profile fields) stay in the HTTP cache.
All public discovery results use an explicit allowlist. Share one Client between
workers for a shared, capacity-one rate limiter; separate processes need external
coordination. API failures raise S2Error and must never be checkpointed as misses.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import random
import re
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime

BASE = 'https://api.semanticscholar.org/graph/v1/'
FIELDS = 'title,authors,year,externalIds'
ROOT = Path(__file__).resolve().parents[1]


class S2Error(RuntimeError):
    pass


def load_api_key(env_path=ROOT / '.env'):
    """Environment wins; read only the requested key, without modifying environ."""
    if os.environ.get('S2_API_KEY'):
        return os.environ['S2_API_KEY']
    path = Path(env_path)
    if path.exists():
        for line in path.read_text().splitlines():
            match = re.match(r'^\s*(?:export\s+)?S2_API_KEY\s*=\s*(.*?)\s*$', line)
            if match:
                return match[1].strip('\"\'')
    return None


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as out:
            name = out.name
            json.dump(value, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


class Client:
    """Serial, capacity-one token bucket; every attempt consumes a token.

    Defaults remain conservative with keys (introductory S2 keys are 1 RPS).
    Successful raw JSON is atomically cached by method, URL and POST body.
    """
    def __init__(self, cache_dir=ROOT / '.tmp/s2_cache', *, api_key=None,
                 env_path=ROOT / '.env', interval=1.1, attempts=6, offline=False,
                 opener=urllib.request.urlopen, clock=time.monotonic,
                 sleep=time.sleep, jitter=random.random, wall_clock=time.time):
        if interval < 1.1 or attempts < 1:
            raise ValueError('interval must be >= 1.1 and attempts >= 1')
        self.cache_dir = Path(cache_dir)
        self.api_key = load_api_key(env_path) if api_key is None else api_key
        self.interval, self.attempts, self.offline = interval, attempts, offline
        self.opener, self.clock, self.sleep = opener, clock, sleep
        self.jitter, self.wall_clock = jitter, wall_clock
        self.next_request = 0.0
        self.lock = threading.Lock()

    def request(self, path, params=None, body=None, *, ok_statuses=(200,)):
        """Return (HTTP status, JSON). Only relative Graph API paths allowed."""
        if path.startswith('/') or '://' in path or '..' in path:
            raise ValueError('Expected a relative Graph API path')
        url = BASE + path
        if params:
            url += '?' + urllib.parse.urlencode(sorted(params.items()))
        data = json.dumps(body, sort_keys=True).encode() if body is not None else None
        method = 'POST' if data is not None else 'GET'
        digest = hashlib.sha256(method.encode() + url.encode() + (data or b'')).hexdigest()
        cache = self.cache_dir / (digest + '.json')
        with self.lock:
            if cache.exists():
                try:
                    saved = json.loads(cache.read_text())
                    if saved['status'] in ok_statuses:
                        return saved['status'], saved['payload']
                except (ValueError, KeyError, TypeError):
                    pass  # corrupt/incomplete cache is not a negative result
            if self.offline:
                raise S2Error('Offline S2 cache miss')
            headers = {'Accept': 'application/json', 'Content-Type': 'application/json',
                       'User-Agent': 'ECERankings-S2-discovery/1.0'}
            if self.api_key:
                headers['x-api-key'] = self.api_key
            for attempt in range(self.attempts):
                self.sleep(max(0, self.next_request - self.clock()))
                self.next_request = self.clock() + self.interval
                retry_after = None
                try:
                    req = urllib.request.Request(url, data=data, headers=headers, method=method)
                    with self.opener(req, timeout=60) as response:
                        status, raw = response.status, response.read()
                except urllib.error.HTTPError as exc:
                    status, raw = exc.code, exc.read()
                    retry_after = (exc.headers or {}).get('Retry-After')
                    exc.close()
                except (urllib.error.URLError, TimeoutError, OSError):
                    status, raw = 503, b''
                if status in ok_statuses:
                    try:
                        payload = json.loads(raw) if raw else None
                    except ValueError as exc:
                        raise S2Error('Invalid S2 JSON; response not cached') from exc
                    atomic_json(cache, {'status': status, 'payload': payload})
                    return status, payload
                if status != 429 and not 500 <= status < 600:
                    raise S2Error(f'S2 HTTP {status}')
                delay = min(60, 2 ** attempt) + self.jitter()
                if retry_after:
                    try:
                        wait = float(retry_after)
                    except ValueError:
                        try:
                            wait = parsedate_to_datetime(retry_after).timestamp() - self.wall_clock()
                        except (ValueError, TypeError, OverflowError):
                            wait = 0
                    delay = max(delay, wait)
                self.next_request = max(self.next_request, self.clock() + delay)
                if attempt + 1 == self.attempts:
                    raise S2Error(f'S2 retries exhausted (HTTP {status}); retry on resume')

    def search(self, title, limit=20):
        if not title.strip() or not 1 <= limit <= 100:
            raise ValueError('Expected a title and limit in 1..100')
        payload = self.request('paper/search', {'query': title, 'limit': limit, 'fields': FIELDS})[1]
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
            raise S2Error('Malformed S2 search response')
        return [safe_paper(p) for p in payload['data']]

    def batch(self, ids, *, metrics=False, batch_size=500):
        """Resolve known IDs, preserving order and nulls; titles require search."""
        if not 1 <= batch_size <= 500:
            raise ValueError('batch_size must be in 1..500')
        ids = list(ids)
        fields = FIELDS + (',citationCount,influentialCitationCount' if metrics else '')
        results = []
        for start in range(0, len(ids), batch_size):
            part = ids[start:start + batch_size]
            payload = self.request('paper/batch', {'fields': fields}, {'ids': part})[1]
            if not isinstance(payload, list) or len(payload) != len(part):
                raise S2Error('Malformed S2 batch response')
            results.extend(safe_paper(p, metrics=metrics) if p else None for p in payload)
        return results


def normalize(text):
    text = unicodedata.normalize('NFKD', str(text or '')).casefold()
    return ''.join(c for c in text if c.isalnum() and not unicodedata.combining(c))


def safe_paper(paper, *, metrics=False):
    """Allowlist deliberately excludes affiliations, venues and authorships."""
    ids = paper.get('externalIds') or {}
    result = {'paperId': paper.get('paperId'), 'title': paper.get('title'),
              'year': paper.get('year'),
              'authors': [{'name': a.get('name')} for a in paper.get('authors') or []],
              'externalIds': {k: ids[k] for k in ('DOI', 'ArXiv', 'CorpusId', 'ACL') if ids.get(k) is not None}}
    if metrics:
        result['informational_metrics'] = {k: paper.get(k) for k in ('citationCount', 'influentialCitationCount')}
    return result


def discover(canonical, candidates):
    """Conservative exact normalized title + complete ordered byline matching.

    Ambiguities require review; a nearby preprint year is allowed, but flagged.
    Accepts local dataset candidates or Graph results. Never modifies canonical.
    """
    matches = []
    names = [normalize(n) for n in canonical.get('authors', [])]
    for raw in candidates:
        p = safe_paper(raw)
        if (normalize(canonical.get('title')) and names and all(names)
                and normalize(p['title']) == normalize(canonical['title'])
                and [normalize(a['name']) for a in p['authors']] == names
                and (not canonical.get('year') or not p['year'] or abs(canonical['year'] - p['year']) <= 1)):
            matches.append(p)
    unique = {json.dumps(p, sort_keys=True): p for p in matches}
    matches = list(unique.values())
    if len(matches) != 1:
        return {'status': 'ambiguous' if matches else 'unresolved', 'candidates': matches}
    paper = matches[0]
    ids = paper['externalIds']
    doi = ids.get('DOI')
    arxiv = ids.get('ArXiv')
    lookups = ([{'kind': 'doi', 'value': doi}] if doi else [])
    if arxiv:
        lookups.append({'kind': 'doi', 'value': '10.48550/arXiv.' + re.sub(r'v\d+$', '', arxiv)})
    return {'status': 'matched' if lookups else 'identifier_only', 's2': paper,
            'openalex_lookups': lookups, 'requires_openalex_identity_check': True,
            'year_difference': bool(canonical.get('year') and paper['year'] != canonical['year'])}


def reconcile(canonical, candidates):
    """Audit-only title/byline/version differences; never adds membership."""
    candidates = [safe_paper(p) for p in candidates]
    reports = []
    for member in canonical:
        hits = [p for p in candidates if normalize(p['title']) == normalize(member['title'])]
        issues = []
        if not hits:
            issues.append('missing_in_s2')
        for p in hits:
            names = [a['name'] for a in p['authors']]
            if len(names) != len(member['authors']):
                issues.append('author_count_mismatch')
            elif [normalize(n) for n in names] != [normalize(n) for n in member['authors']]:
                issues.append('byline_mismatch')
            if member.get('year') and p['year'] != member['year']:
                issues.append('possible_version_mismatch')
        if len(hits) > 1:
            issues.append('multiple_s2_versions')
        reports.append({'canonical_id': member.get('paper_key', member.get('id')),
                        'issues': sorted(set(issues)), 's2_candidates': hits})
    titles = {normalize(m['title']) for m in canonical}
    return {'papers': reports, 's2_only': [p for p in candidates if normalize(p['title']) not in titles],
            'membership_authority': 'publisher', 'audit_only': True}
