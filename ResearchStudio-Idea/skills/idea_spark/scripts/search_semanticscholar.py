"""Semantic Scholar search connector.

Why: Semantic Scholar (~200M works, CS-focused) provides cleaner CS/ML retrieval
than OpenAlex's broad academic indexing. Key differentiators vs OpenAlex:
- TLDR field (Allen AI auto-generated 1-sentence summary) for quick relevance triage
- External IDs include DBLP key, arxiv ID, DOI in one record (better dedup)
- More academic-CS focused, lower drift to adjacent fields (biology, medicine)
- Direct citationCount + publicationTypes
- Returns abstract as plain text (not inverted index — no reconstruction needed)

API key in env (SEMANTICSCHOLAR_API_KEY) — strongly recommended. Rate limits:
  - With introductory API key: 1 req/sec CUMULATIVE across all SS endpoints
  - Anonymous: ~100 req/5min (effectively ~0.3 req/sec, but throttled in bursts)
The cumulative-across-endpoints constraint means we sleep ≥1.1s between calls
even when authenticated.

I/O:
  python3 -m scripts.search_semanticscholar --queries '["..."]' --window-months 24 --out hits.json
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = 'https://api.semanticscholar.org/graph/v1/paper/search'

FIELDS = [
    'paperId',
    'externalIds',
    'title',
    'abstract',
    'venue',
    'year',
    'publicationDate',
    'publicationVenue',
    'publicationTypes',
    'citationCount',
    'openAccessPdf',
    'tldr',
    'authors.name',
]


def normalize_title(t: str) -> str:
    return re.sub(r'\W+', ' ', (t or '').lower()).strip()[:80]


def _format_paper_id(paper: dict) -> str:
    """Choose the most stable external ID for cross-source dedup. Priority: DBLP > arxiv > DOI > S2 paperId."""
    ext = paper.get('externalIds') or {}
    if ext.get('DBLP'):
        return f'dblp:{ext["DBLP"]}'
    if ext.get('ArXiv'):
        return f'arxiv:{ext["ArXiv"]}'
    if ext.get('DOI'):
        return f'doi:{ext["DOI"]}'
    return f'semanticscholar:{paper.get("paperId", "")}'


def search(query: str, since_year: int, until_year: int | None = None,
           published_only: bool = False, max_results: int = 50) -> list[dict]:
    """Query Semantic Scholar paper search API. Returns list of normalized hit dicts.

    Date window expressed as year range — SS supports `year=YYYY-YYYY`.
    """
    api_key = os.environ.get('SEMANTICSCHOLAR_API_KEY', '')
    year_filter = f'{since_year}-{until_year}' if until_year else f'{since_year}-'

    params = {
        'query': query,
        'limit': min(max_results, 100),
        'fields': ','.join(FIELDS),
        'year': year_filter,
    }
    if published_only:
        # Restrict to formal venues; SS publicationTypes covers JournalArticle, Conference, Book, etc
        params['publicationTypes'] = 'JournalArticle,Conference'

    url = f'{API}?{urllib.parse.urlencode(params)}'
    headers = {'User-Agent': 'idea-spark/1.0'}
    if api_key:
        headers['x-api-key'] = api_key

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            # rate limited — back off and retry once
            time.sleep(5)
            with urllib.request.urlopen(req, timeout=45) as r:
                data = json.loads(r.read())
        else:
            raise

    out = []
    for paper in data.get('data', [])[:max_results]:
        title = paper.get('title') or ''
        abstract = paper.get('abstract') or ''
        venue = paper.get('venue') or ''
        if not venue:
            pv = paper.get('publicationVenue') or {}
            venue = pv.get('name', '')
        authors = [a.get('name', '') for a in (paper.get('authors') or [])][:6]
        oa = paper.get('openAccessPdf') or {}
        tldr_obj = paper.get('tldr') or {}
        tldr = tldr_obj.get('text', '') if isinstance(tldr_obj, dict) else ''
        ext = paper.get('externalIds') or {}

        out.append({
            'title': title,
            'title_norm': normalize_title(title),
            'abstract': abstract,
            'tldr': tldr,  # SS-exclusive: 1-sentence Allen-AI summary
            'year': paper.get('year'),
            'venue': venue,
            'publication_types': paper.get('publicationTypes') or [],
            'authors': authors,
            'citations': paper.get('citationCount'),
            'source': 'semanticscholar',
            'source_id': paper.get('paperId', ''),
            'paper_id': _format_paper_id(paper),
            'doi': ext.get('DOI', ''),
            'arxiv_id': ext.get('ArXiv', ''),
            'dblp_key': ext.get('DBLP', ''),
            'paper_url': oa.get('url', '') or f'https://www.semanticscholar.org/paper/{paper.get("paperId","")}',
            'published_iso': paper.get('publicationDate', ''),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--queries', required=True)
    ap.add_argument('--window-months', type=int, default=24, help='Window-max in months')
    ap.add_argument('--window-min-months', type=int, default=0, help='Window-min in months')
    ap.add_argument('--published-only', action='store_true',
                    help='Filter to JournalArticle + Conference (excludes preprints)')
    ap.add_argument('--as-of', default='', help='YYYY-MM-DD: backdate the window reference date (for forward-prediction evals); default = real now')
    ap.add_argument('--max-per-query', type=int, default=50)
    ap.add_argument('--max-results', type=int, default=0,
                    help='Final cap on output (0 = no cap)')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    from scripts._time_guard import resolve_now
    queries = json.loads(args.queries)
    now = resolve_now(args.as_of)
    since_year = (now - timedelta(days=30 * args.window_months)).year
    # Upper bound (year granularity): set when excluding recent months OR when backdating
    # (--as-of), else None = up to now. Under backdating the bound is the reference year, so
    # post-as-of papers do not leak in (year granularity means up to Dec of the as-of year).
    until_year = (now - timedelta(days=30 * args.window_min_months)).year \
        if (args.window_min_months > 0 or args.as_of) else None

    seen = set(); merged = []
    for q in queries:
        try:
            hits = search(q, since_year, until_year=until_year,
                          published_only=args.published_only, max_results=args.max_per_query)
        except Exception as e:
            print(f'  semanticscholar {q!r} failed: {e}', file=sys.stderr); continue
        for h in hits:
            key = h['title_norm']
            if not key or key in seen: continue
            seen.add(key); merged.append(h)
        # Rate limit: 1 req/sec cumulative (introductory key tier); anonymous tier ~0.3/sec.
        # Sleep 1.1s with key (safe margin); 3s without (anonymous tier is bursty).
        time.sleep(1.1 if os.environ.get('SEMANTICSCHOLAR_API_KEY') else 3.0)

    if args.max_results > 0:
        merged = merged[:args.max_results]
    Path(args.out).write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    print(f'wrote {args.out} with {len(merged)} unique papers', file=sys.stderr)


if __name__ == '__main__':
    main()
