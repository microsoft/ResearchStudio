"""OpenAlex search connector.

Why: OpenAlex (~250M works) is the most comprehensive open academic graph;
gives us full abstracts, citation counts, venue, year, and authors in one call.

API key in env (OPENALEX_API_KEY) — without key the polite-pool still works.

I/O:
  python -m scripts.search_openalex --queries '["..."]' --window-months 24 --out hits.json
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

API = 'https://api.openalex.org/works'


def normalize_title(t: str) -> str:
    return re.sub(r'\W+', ' ', (t or '').lower()).strip()[:80]


def reconstruct_abstract(inv_idx: dict | None) -> str:
    """OpenAlex stores abstracts as inverted indices to keep payloads small."""
    if not inv_idx: return ''
    positions: dict[int, str] = {}
    for word, idxs in inv_idx.items():
        for i in idxs: positions[i] = word
    return ' '.join(positions[k] for k in sorted(positions))


def search(query: str, since_date: str, until_date: str | None = None,
           published_only: bool = False, max_results: int = 50) -> list[dict]:
    api_key = os.environ.get('OPENALEX_API_KEY', '')
    # Build the OpenAlex filter string. Filters are comma-separated AND.
    filter_parts = [f'from_publication_date:{since_date}']
    if until_date:
        filter_parts.append(f'to_publication_date:{until_date}')
    if published_only:
        # Exclude preprints (posted-content), keep journal articles, conference proceedings, book chapters.
        # OpenAlex `type` field uses Crossref types; `posted-content` covers arxiv / SSRN / preprint servers.
        filter_parts.append('type:!posted-content')
    params = {
        'search': query,
        'filter': ','.join(filter_parts),
        'per_page': min(max_results, 25),
        'select': 'id,title,doi,publication_year,publication_date,abstract_inverted_index,authorships,primary_location,cited_by_count,best_oa_location,type',
        'sort': 'relevance_score:desc',
    }
    if api_key:
        params['api_key'] = api_key
    url = f'{API}?{urllib.parse.urlencode(params)}'
    # OpenAlex polite-pool: identifying email in User-Agent gets the higher
    # rate-limit tier (10 req/s vs 1 req/s anonymous). Set OPENALEX_MAILTO to
    # your real email; the placeholder works but yields no polite-pool benefit.
    mailto = os.environ.get('OPENALEX_MAILTO', 'novelty@local')
    req = urllib.request.Request(url, headers={'User-Agent': f'novelty-lit-search/1.0 (mailto:{mailto})'})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())

    out = []
    for work in data.get('results', [])[:max_results]:
        title = work.get('title') or ''
        abstract = reconstruct_abstract(work.get('abstract_inverted_index'))
        primary_loc = work.get('primary_location') or {}
        source = primary_loc.get('source') or {}
        venue = source.get('display_name', '')
        authors = [a.get('author', {}).get('display_name', '') for a in work.get('authorships', [])][:6]
        oa = work.get('best_oa_location') or {}
        out.append({
            'title': title,
            'title_norm': normalize_title(title),
            'abstract': abstract,
            'year': work.get('publication_year'),
            'venue': venue,
            'authors': authors,
            'citations': work.get('cited_by_count'),
            'source': 'openalex',
            'source_id': work.get('id', '').split('/')[-1],
            'doi': (work.get('doi') or '').replace('https://doi.org/', ''),
            'paper_url': oa.get('pdf_url') or work.get('id', ''),
            'published_iso': work.get('publication_date', ''),
        })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--queries', required=True)
    ap.add_argument('--window-months', type=int, default=24, help='Window-max in months')
    ap.add_argument('--window-min-months', type=int, default=0, help='Window-min in months (excludes the most recent N months)')
    ap.add_argument('--published-only', action='store_true', help='Filter out preprints (type:!posted-content); keep only journal/conference/proceedings papers')
    ap.add_argument('--max-per-query', type=int, default=50)
    ap.add_argument('--max-results', type=int, default=0, help='Final cap on output (0 = no cap; if set, take top by relevance)')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    from scripts._time_guard import assert_sane_now
    queries = json.loads(args.queries)
    now = assert_sane_now()
    since = (now - timedelta(days=30 * args.window_months)).strftime('%Y-%m-%d')
    until = (now - timedelta(days=30 * args.window_min_months)).strftime('%Y-%m-%d') if args.window_min_months > 0 else None

    seen = set(); merged = []
    for q in queries:
        try:
            hits = search(q, since, until_date=until, published_only=args.published_only,
                          max_results=args.max_per_query)
        except Exception as e:
            print(f'  openalex {q!r} failed: {e}', file=sys.stderr); continue
        for h in hits:
            key = h['title_norm']
            if not key or key in seen: continue
            seen.add(key); merged.append(h)
        time.sleep(0.1)  # generous-but-considerate

    if args.max_results > 0:
        # Already sorted by relevance per-query; merged ordering reflects relevance within each query
        merged = merged[:args.max_results]
    Path(args.out).write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    print(f'wrote {args.out} with {len(merged)} unique papers', file=sys.stderr)


if __name__ == '__main__':
    main()
