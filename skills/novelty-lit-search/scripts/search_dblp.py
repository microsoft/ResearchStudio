"""DBLP search connector (map mode only).

Why: DBLP is the canonical ML/AI conference index — confirms whether a topic
appeared at top venues recently and resolves author ambiguity. Doesn't expose
abstracts on the simple endpoint, so collision mode skips this connector.

I/O:
  python -m scripts.search_dblp --queries '["..."]' --window-months 24 --out hits.json
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = 'https://dblp.org/search/publ/api'

# Default venue whitelist for the ML/AI track. Override via --venues "iclr,icml,..."
# when working in adjacent fields (robotics: corl,rss,iros,icra; security: usenix-sec,sp,ccs,ndss;
# medical imaging: miccai; etc.). The whitelist is a coverage filter — without it dblp returns
# any matched-title paper from any conference, including off-topic CS workshops.
DEFAULT_VENUES_ML_AI = {'iclr', 'icml', 'neurips', 'nips', 'aaai', 'ijcai', 'acl', 'emnlp',
                        'naacl', 'cvpr', 'eccv', 'iccv', 'kdd', 'www', 'sigir', 'uai', 'aistats',
                        'colm', 'tmlr'}


def normalize_title(t: str) -> str:
    return re.sub(r'\W+', ' ', (t or '').lower()).strip()[:80]


def is_top_venue(venue: str, venues_ok: set[str]) -> bool:
    v = venue.lower()
    return any(k in v for k in venues_ok)


def search(query: str, venues_ok: set[str], max_results: int = 100) -> list[dict]:
    params = {'q': query, 'format': 'json', 'h': max_results}
    url = f'{API}?{urllib.parse.urlencode(params)}'
    req = urllib.request.Request(url, headers={'User-Agent': 'novelty-lit-search/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    hits = (((data.get('result') or {}).get('hits') or {}).get('hit') or [])
    out = []
    for h in hits:
        info = h.get('info', {})
        title = (info.get('title') or '').rstrip('. ')
        venue = info.get('venue') or ''
        if not is_top_venue(venue, venues_ok): continue
        try: year = int(info.get('year', 0))
        except Exception: year = None
        authors_raw = info.get('authors', {}) or {}
        author_list = authors_raw.get('author', [])
        if isinstance(author_list, dict): author_list = [author_list]
        authors = [a.get('text', '') for a in author_list if isinstance(a, dict)][:6]
        out.append({
            'title': title,
            'title_norm': normalize_title(title),
            'abstract': '',  # DBLP simple endpoint has no abstract
            'year': year,
            'venue': venue,
            'authors': authors,
            'citations': None,
            'source': 'dblp',
            'source_id': info.get('key', ''),
            'doi': info.get('doi', ''),
            'paper_url': info.get('ee', ''),
            'published_iso': '',
        })
    return out


def query_overlap_score(title: str, queries: list[str]) -> int:
    """Lightweight client-side relevance: count unique query tokens that appear in title.
    DBLP has no relevance ranking and only matches title — this restores some signal."""
    title_low = (title or '').lower()
    title_tokens = set(re.findall(r'\w+', title_low))
    matched = set()
    for q in queries:
        for tok in re.findall(r'\w+', q.lower()):
            if len(tok) >= 3 and tok in title_tokens:
                matched.add(tok)
    return len(matched)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--queries', required=True)
    ap.add_argument('--window-months', type=int, default=24, help='Window-max in months (year-granular)')
    ap.add_argument('--window-min-months', type=int, default=0, help='Window-min in months (year-granular; excludes the most recent N months)')
    ap.add_argument('--max-per-query', type=int, default=50)
    ap.add_argument('--max-results', type=int, default=0, help='Final cap on output, after client-side rerank by query-token overlap (0 = no cap)')
    ap.add_argument('--venues', default='', help='Comma-separated venue acronym whitelist. Empty = default ML/AI track. Override for adjacent fields (e.g., "corl,rss,iros" for robotics, "miccai" for medical imaging).')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    from scripts._time_guard import assert_sane_now
    queries = json.loads(args.queries)
    now = assert_sane_now()
    cutoff_year_min = now.year - max(0, args.window_months // 12)
    # window_min_months is excluded — papers newer than window-min are dropped
    cutoff_year_max = now.year - max(0, args.window_min_months // 12) if args.window_min_months > 0 else now.year + 1

    venues_ok = {v.strip().lower() for v in args.venues.split(',') if v.strip()} if args.venues else DEFAULT_VENUES_ML_AI

    seen = set(); merged = []
    for q in queries:
        try:
            hits = search(q, venues_ok, max_results=args.max_per_query)
        except Exception as e:
            print(f'  dblp {q!r} failed: {e}', file=sys.stderr); continue
        for h in hits:
            yr = h.get('year') or 0
            if yr < cutoff_year_min: continue
            if args.window_min_months > 0 and yr > cutoff_year_max: continue
            key = h['title_norm']
            if not key or key in seen: continue
            seen.add(key); merged.append(h)
        time.sleep(1.0)  # gentle scrape

    if args.max_results > 0:
        # Client-side rerank: query-token overlap descending, year descending tie-break
        merged.sort(key=lambda h: (-query_overlap_score(h.get('title', ''), queries), -(h.get('year') or 0)))
        merged = merged[:args.max_results]
    Path(args.out).write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    print(f'wrote {args.out} with {len(merged)} unique papers', file=sys.stderr)


if __name__ == '__main__':
    main()
