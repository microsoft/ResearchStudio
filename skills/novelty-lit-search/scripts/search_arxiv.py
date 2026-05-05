"""arXiv search connector.

Why: arXiv has the freshest preprints with no auth and a stable API.

I/O:
  python -m scripts.search_arxiv --queries '["...","..."]' --window-months 6 --out hits.json

Rate: throttle to 3 req/s. arXiv is generous but considerate is the norm.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ARXIV_API = 'http://export.arxiv.org/api/query'
NS = {'atom': 'http://www.w3.org/2005/Atom',
      'arxiv': 'http://arxiv.org/schemas/atom'}


def normalize_title(t: str) -> str:
    import re
    return re.sub(r'\W+', ' ', (t or '').lower()).strip()[:80]


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
    with urllib.request.urlopen(url, timeout=30) as r:
        body = r.read()
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
    ap.add_argument('--max-per-query', type=int, default=50)
    ap.add_argument('--max-results', type=int, default=0, help='Final cap on output (0 = no cap; if set, take top by recency)')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    from scripts._time_guard import assert_sane_now
    now = assert_sane_now()

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
        time.sleep(0.34)  # ~3 req/s
    if args.max_results > 0:
        # Already sorted by relevance (arxiv sortBy=relevance); take head
        merged = merged[:args.max_results]
    Path(args.out).write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    print(f'wrote {args.out} with {len(merged)} unique papers', file=sys.stderr)


if __name__ == '__main__':
    main()
