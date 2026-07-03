"""arXiv search connector.

Why: arXiv has the freshest preprints with no auth and a stable API.

I/O:
  python3 -m scripts.search_arxiv --queries '["...","..."]' --window-months 6 --out hits.json

Rate: arXiv is anonymous-only (no auth, no API key, no per-account quota), so the only
lever is request pacing. We space requests >= 4s apart and back off on HTTP 429
(Too Many Requests) — a too-tight cadence is exactly what triggers the 429 that
silently zeroes out this connector.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

# https (not http): http://export.arxiv.org 301-redirects to https, wasting a round-trip
# and occasionally landing the retry on a 429 before the real request even runs.
ARXIV_API = 'https://export.arxiv.org/api/query'
# arXiv flags requests with no/again-default User-Agent; identify ourselves politely.
USER_AGENT = 'research-studio-idea/1.0 (+https://arxiv.org/help/api)'
MIN_INTERVAL_S = float(os.environ.get('ARXIV_MIN_INTERVAL', '4.0'))  # >= 4s between any two arXiv hits
MAX_RETRIES = 4        # on 429, back off and retry this many times before giving up
NS = {'atom': 'http://www.w3.org/2005/Atom',
      'arxiv': 'http://arxiv.org/schemas/atom'}

# Pacing must hold ACROSS processes, not just within one: if the orchestrator ever runs two
# arxiv connectors in parallel (e.g. concurrent prompt runs), a module-global clock alone would
# let each fire immediately and burst arXiv into a 429. We serialize on a lockfile in the system
# temp dir, holding the exclusive flock across the sleep so concurrent callers queue and each
# request lands >= MIN_INTERVAL_S after the previous one actually fired.
_THROTTLE_FILE = os.path.join(tempfile.gettempdir(), 'arxiv_search_throttle.lock')


def _throttle():
    """Block until at least MIN_INTERVAL_S has elapsed since the previous arXiv request.

    Cross-process via fcntl.flock; degrades to a plain per-process sleep floor where fcntl
    is unavailable (non-POSIX)."""
    try:
        import fcntl
    except ImportError:
        time.sleep(MIN_INTERVAL_S)
        return

    fd = os.open(_THROTTLE_FILE, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # serializes all arXiv callers on this machine
        raw = os.read(fd, 64).decode('utf-8').strip()
        try:
            last = float(raw) if raw else 0.0
        except ValueError:
            last = 0.0
        wait = MIN_INTERVAL_S - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        # Stamp the moment this request is about to fire, so the next caller spaces from here.
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, str(time.time()).encode('utf-8'))
    finally:
        os.close(fd)  # releasing the fd also releases the flock


def normalize_title(t: str) -> str:
    import re
    return re.sub(r'\W+', ' ', (t or '').lower()).strip()[:80]


def _fetch(url: str) -> bytes:
    """GET with paced cadence + exponential backoff on 429. Raises if all retries fail."""
    for attempt in range(MAX_RETRIES + 1):
        _throttle()
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < MAX_RETRIES:
                backoff = MIN_INTERVAL_S * (2 ** attempt)  # 4s, 8s, 16s, 32s
                print(f'  arxiv 429 (rate-limited), backing off {backoff:.0f}s '
                      f'(attempt {attempt + 1}/{MAX_RETRIES})', file=sys.stderr)
                time.sleep(backoff)
                continue
            raise
    raise RuntimeError('unreachable')


def search(query: str, max_results: int = 100) -> list[dict]:
    # sortBy=relevance ranks by query fit; the orchestrator's --window-months
    # then provides the freshness filter via in_window(). Sorting by submittedDate
    # makes the recency-of-submission dominate, so loose keyword matches (papers
    # containing "model" or "sampling") flood the result set with off-topic noise.
    params = {
        'search_query': f'all:{query}',
        'sortBy': 'relevance',
        'sortOrder': 'descending',
        'max_results': max_results,
    }
    url = f'{ARXIV_API}?{urllib.parse.urlencode(params)}'
    body = _fetch(url)
    root = ET.fromstring(body)
    out = []
    for entry in root.findall('atom:entry', NS):
        title = (entry.find('atom:title', NS).text or '').strip()
        abstract = (entry.find('atom:summary', NS).text or '').strip()
        published = entry.find('atom:published', NS).text
        authors = [a.find('atom:name', NS).text for a in entry.findall('atom:author', NS)]
        ids = [link.get('href') for link in entry.findall('atom:link', NS) if link.get('rel') == 'alternate']
        arxiv_id = ids[0].split('/')[-1] if ids else entry.find('atom:id', NS).text.split('/')[-1]
        try:
            year = int(published[:4])
        except Exception:
            year = None
        out.append({
            'title': title,
            'title_norm': normalize_title(title),
            'abstract': abstract,
            'year': year,
            'venue': 'arXiv',
            'authors': authors,
            'citations': None,
            'source': 'arxiv',
            'source_id': arxiv_id,
            'doi': '',
            'paper_url': f'https://arxiv.org/abs/{arxiv_id}',
            'published_iso': published,
        })
    return out


def in_window(paper: dict, since: datetime, until: datetime) -> bool:
    """Window is [since, until]: paper must be at or after `since` AND at or before `until`."""
    try:
        d = datetime.fromisoformat(paper['published_iso'].replace('Z', '+00:00'))
        return since <= d <= until
    except Exception:
        # Year-level fallback: same comparison at year granularity
        y = paper.get('year', 0)
        return since.year <= y <= until.year


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--queries', required=True, help='JSON list of query strings')
    ap.add_argument('--window-months', type=int, default=24, help='Window-max in months (papers older than this are excluded)')
    ap.add_argument('--window-min-months', type=int, default=0, help='Window-min in months (papers newer than this are excluded; default 0 = up to now)')
    ap.add_argument('--as-of', default='', help='YYYY-MM-DD: backdate the window reference date (for forward-prediction evals); default = real now')
    ap.add_argument('--max-per-query', type=int, default=50)
    ap.add_argument('--max-results', type=int, default=0, help='Final cap on output (0 = no cap; if set, take top by recency)')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    from scripts._time_guard import resolve_now
    now = resolve_now(args.as_of)

    queries = json.loads(args.queries)
    since = now - timedelta(days=30 * args.window_months)
    until = now - timedelta(days=30 * args.window_min_months)
    seen = set()
    merged = []
    for q in queries:
        try:
            hits = search(q, max_results=args.max_per_query)
        except Exception as e:
            print(f'  arxiv {q!r} failed: {e}', file=sys.stderr)
            continue
        for h in hits:
            if not in_window(h, since, until): continue
            key = h['title_norm']
            if key in seen: continue
            seen.add(key); merged.append(h)
        # pacing is centralized in _fetch()->_throttle() (>= 4s between requests);
        # no extra inter-query sleep needed here.
    if args.max_results > 0:
        # Already sorted by relevance (arxiv sortBy=relevance); take head
        merged = merged[:args.max_results]
    Path(args.out).write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    print(f'wrote {args.out} with {len(merged)} unique papers', file=sys.stderr)


if __name__ == '__main__':
    main()
