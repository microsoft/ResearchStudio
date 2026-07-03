"""OpenAlex search connector.

Why: OpenAlex (~250M works) is the most comprehensive open academic graph;
gives us full abstracts, citation counts, venue, year, and authors in one call.

API key in env (OPENALEX_API_KEY) — without key the polite-pool still works.

I/O:
  python3 -m scripts.search_openalex --queries '["..."]' --window-months 24 --out hits.json
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


_SELECT = ('id,title,doi,publication_year,publication_date,abstract_inverted_index,'
           'authorships,primary_location,cited_by_count,best_oa_location,type,primary_topic')


def _api_get(params: dict, timeout: int = 30) -> dict:
    """Issue one OpenAlex GET. Adds api_key. Raises on HTTP error."""
    api_key = os.environ.get('OPENALEX_API_KEY', '')
    if api_key:
        params = {**params, 'api_key': api_key}
    url = f'{API}?{urllib.parse.urlencode(params)}'
    # OpenAlex polite-pool: identifying email in User-Agent gets the higher
    # rate-limit tier (10 req/s vs 1 req/s anonymous).
    req = urllib.request.Request(url, headers={'User-Agent': f'idea-spark/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def work_to_record(work: dict, semantic_recall: bool = False) -> dict:
    """Convert one OpenAlex Work into our flat record schema. `semantic_recall`
    tags records that came from the semantic recall-booster pass rather than BM25."""
    title = work.get('title') or ''
    abstract = reconstruct_abstract(work.get('abstract_inverted_index'))
    primary_loc = work.get('primary_location') or {}
    source = primary_loc.get('source') or {}
    venue = source.get('display_name', '')
    authors = [a.get('author', {}).get('display_name', '') for a in work.get('authorships', [])][:6]
    oa = work.get('best_oa_location') or {}
    # OpenAlex Work.ids has cross-source IDs when available — extract arxiv
    # specifically so downstream full-text fetch can prefer the arxiv path
    # (HTML version available for ~85% of post-2024 ML preprints) rather
    # than the IEEE / Elsevier paywall the DOI typically resolves to.
    ids = work.get('ids') or {}
    arxiv_raw = ids.get('arxiv') or ''
    # Normalize: "https://arxiv.org/abs/2412.14171" → "2412.14171"
    parsed_arxiv = urllib.parse.urlparse(arxiv_raw)
    arxiv_host = (parsed_arxiv.hostname or '').lower()
    arxiv_path = parsed_arxiv.path or ''
    if arxiv_host in {'arxiv.org', 'www.arxiv.org'} and re.match(r'^/(?:abs|pdf|html)/', arxiv_path):
        arxiv_id = re.sub(r'^/(?:abs|pdf|html)/', '', arxiv_path).rstrip('.pdf').strip()
    else:
        arxiv_id = arxiv_raw.rstrip('.pdf').strip()
    pt = work.get('primary_topic') or {}
    oa_field = ((pt.get('field') or {}).get('display_name')) or ''
    return {
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
        'arxiv_id': arxiv_id or None,
        'paper_url': oa.get('pdf_url') or work.get('id', ''),
        'published_iso': work.get('publication_date', ''),
        'oa_field': oa_field,                 # OpenAlex primary_topic field — used for the semantic relevance gate
        'semantic_recall': semantic_recall,   # True iff retrieved by the search.semantic recall booster
    }


def search(query: str, since_date: str, until_date: str | None = None,
           published_only: bool = False, max_results: int = 50) -> list[dict]:
    """BM25 keyword search over OpenAlex within a day-granular publication-date window."""
    # Build the OpenAlex filter string. Filters are comma-separated AND.
    filter_parts = [f'from_publication_date:{since_date}']
    if until_date:
        filter_parts.append(f'to_publication_date:{until_date}')
    if published_only:
        # Exclude preprints (posted-content), keep journal articles, conference proceedings, book chapters.
        # OpenAlex `type` field uses Crossref types; `posted-content` covers arxiv / SSRN / preprint servers.
        filter_parts.append('type:!posted-content')
    data = _api_get({
        'search': query,
        'filter': ','.join(filter_parts),
        'per_page': min(max_results, 25),
        'select': _SELECT,
        'sort': 'relevance_score:desc',
    })
    return [work_to_record(w) for w in data.get('results', [])[:max_results]]


def search_semantic(query: str, start_year: int, end_year: int,
                    published_only: bool = False, max_results: int = 50) -> list[dict]:
    """Semantic (vector) search over OpenAlex. CONSTRAINTS (verified against the live API):
      - only year-granular filters are supported (publication_year), NOT from/to_publication_date;
      - rate-limited to 1 request/second (separate from the polite pool);
      - returns a fixed top-K semantic neighborhood (~50-70), not a full enumeration.
    The day-level window and the relevance gate are applied client-side by the caller, because
    semantic search can be derailed by polysemy on short jargon queries (e.g. 'group relative
    advantage' → group-decision-theory papers)."""
    filter_parts = [f'publication_year:{start_year}-{end_year}']
    if published_only:
        filter_parts.append('type:!posted-content')
    data = _api_get({
        'search.semantic': query,
        'filter': ','.join(filter_parts),
        'per_page': min(max_results, 100),
        'select': _SELECT,
    })
    if 'results' not in data:   # error payload (rate limit / unsupported filter)
        raise RuntimeError(data.get('message', 'semantic search returned no results key'))
    return [work_to_record(w, semantic_recall=True) for w in data.get('results', [])]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--queries', required=True)
    ap.add_argument('--window-months', type=int, default=24, help='Window-max in months')
    ap.add_argument('--window-min-months', type=int, default=0, help='Window-min in months (excludes the most recent N months)')
    ap.add_argument('--published-only', action='store_true', help='Filter out preprints (type:!posted-content); keep only journal/conference/proceedings papers')
    ap.add_argument('--as-of', default='', help='YYYY-MM-DD: backdate the window reference date (for forward-prediction evals); default = real now')
    ap.add_argument('--max-per-query', type=int, default=50)
    ap.add_argument('--max-results', type=int, default=0, help='Final cap on output (0 = no cap; if set, take top by relevance)')
    ap.add_argument('--with-semantic', action='store_true',
                    help='Add a semantic (vector) recall-booster pass alongside BM25. Catches conceptually-'
                         'adjacent papers BM25 misses by terminology, gated to the BM25 pool\'s field(s) to '
                         'reject polysemy false-positives, and client-side day-window filtered. Off by default '
                         '(year-granular + 1 req/s + top-K; see search_semantic docstring).')
    ap.add_argument('--semantic-per-query', type=int, default=6,
                    help='Per-query fairness cap on semantic recall papers (default 6), so one query cannot eat the whole budget.')
    ap.add_argument('--semantic-total', type=int, default=15,
                    help='Total cap on semantic recall papers across ALL queries (default 15). With BM25 capped at '
                         '--max-results, this bounds OpenAlex output and prevents the semantic booster from dominating the pool.')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    from scripts._time_guard import resolve_now
    queries = json.loads(args.queries)
    now = resolve_now(args.as_of)
    since = (now - timedelta(days=30 * args.window_months)).strftime('%Y-%m-%d')
    # Upper bound: needed when window_min_months > 0 (exclude most-recent N months) OR when
    # backdating (--as-of), where the bound IS the reference date — without it, openalex would
    # return papers published AFTER the as-of date and defeat the forward-prediction eval.
    until = (now - timedelta(days=30 * args.window_min_months)).strftime('%Y-%m-%d') \
        if (args.window_min_months > 0 or args.as_of) else None

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

    # Apply the BM25 cap HERE (before the semantic booster) so the recall papers are
    # additive on top of the capped BM25 pool rather than being truncated away by it.
    if args.max_results > 0:
        merged = merged[:args.max_results]

    # --- semantic recall booster (opt-in) -----------------------------------
    # Runs AFTER BM25 so the BM25 pool defines the "home field(s)" used as the relevance gate.
    # This catches conceptually-adjacent papers BM25 misses on terminology, while the field gate
    # rejects the polysemy false-positives that pure semantic search pulls in on short jargon queries.
    if args.with_semantic:
        # Anchor field(s): fields appearing >= twice in the BM25 pool, else the single modal field.
        # Self-calibrating (no hardcoded 'Computer Science'), so it adapts to the query's actual area.
        from collections import Counter
        fc = Counter(h.get('oa_field') for h in merged if h.get('oa_field'))
        anchor_fields = {f for f, n in fc.items() if n >= 2} or ({fc.most_common(1)[0][0]} if fc else set())
        start_year = int(since[:4]); end_year = int((until or now.strftime('%Y-%m-%d'))[:4])
        n_added = 0
        for q in queries:
            if n_added >= args.semantic_total: break   # total budget across all queries reached
            try:
                cand = search_semantic(q, start_year, end_year,
                                       published_only=args.published_only, max_results=50)
            except Exception as e:
                print(f'  openalex[semantic] {q!r} failed: {e}', file=sys.stderr)
                time.sleep(1.2); continue
            kept = 0
            for h in cand:
                if kept >= args.semantic_per_query or n_added >= args.semantic_total: break
                key = h['title_norm']
                if not key or key in seen: continue
                # Relevance gate: when we have a home field anchor, keep ONLY papers whose
                # field is known AND in the anchor set. Empty/unknown-field papers are rejected
                # under a strong anchor because they cannot be verified in-domain (they are a
                # frequent source of semantic tangents, e.g. cognitive-science 'reasoning' papers).
                if anchor_fields and h.get('oa_field') not in anchor_fields: continue
                # Day-window gate: semantic only filters by year; enforce the exact window client-side.
                iso = h.get('published_iso') or ''
                if iso and not (since <= iso <= (until or '9999-12-31')): continue
                seen.add(key); merged.append(h); kept += 1; n_added += 1
            time.sleep(1.2)  # semantic endpoint is rate-limited to 1 req/s
        print(f'  openalex[semantic] added {n_added} recall-booster papers '
              f'(anchor fields: {sorted(anchor_fields) or "none"})', file=sys.stderr)

    Path(args.out).write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    print(f'wrote {args.out} with {len(merged)} unique papers', file=sys.stderr)


if __name__ == '__main__':
    main()
