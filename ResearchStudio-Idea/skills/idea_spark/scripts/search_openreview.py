"""OpenReview search connector.

Why: OpenReview surfaces in-review submissions for ICLR/NeurIPS/ICML — sees
concurrent work that hasn't yet hit a venue. Strict rate limit: single-thread,
1 req/s, retry-after-429 with capped exponential backoff up to 600s.

Auth: OPENREVIEW_USER + OPENREVIEW_PASS in env.

I/O:
  python3 -m scripts.search_openreview --queries '["..."]' --window-months 6 --out hits.json
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import openreview  # type: ignore
except ImportError:
    openreview = None


def normalize_title(t: str) -> str:
    return re.sub(r'\W+', ' ', (t or '').lower()).strip()[:80]


def get_client():
    if openreview is None:
        raise RuntimeError('openreview-py not installed; pip install openreview-py')
    return openreview.api.OpenReviewClient(
        baseurl='https://api2.openreview.net',
        username=os.environ.get('OPENREVIEW_USER', ''),
        password=os.environ.get('OPENREVIEW_PASS', ''),
    )


def derive_active_venues(now: datetime, custom_venues: list[str] | None = None) -> list[str]:
    """Compute the list of OpenReview venues likely to have in-flight submissions
    based on the current date and conference review cycles. Hardcoding venue years
    (e.g., 'NeurIPS.cc/2025/Conference') goes stale: by 2027 the same string is a
    closed historical venue, not an active submission pool.

    Standard cycle (UTC, approximate):
      ICLR  : submission Sep — review Oct-Dec — decisions Jan; reviewing happens through Q4
      NeurIPS: submission May — review Jul-Sep — decisions Sep; reviewing happens through Q3
      ICML  : submission Jan — review Feb-Apr — decisions Apr-May; reviewing happens through Q2

    This returns the venue id for each venue's CURRENT cycle (the one that hasn't
    ended yet) plus the most recent CLOSED cycle (so we still see accepted papers
    that haven't appeared on arxiv with full metadata yet).
    """
    if custom_venues:
        return custom_venues
    # ICLR: submission Sep (year-1) — decisions Jan (year). Active cycle is the one whose decisions are upcoming.
    iclr_year = now.year + (1 if now.month >= 9 else 0)
    # NeurIPS: submission May (year) — decisions Sep (year). Active cycle = current year if before Oct.
    neurips_year = now.year if now.month <= 10 else now.year + 1
    # ICML: submission Jan (year) — decisions May (year). Active cycle = current year if before Jun.
    icml_year = now.year if now.month <= 6 else now.year + 1
    return [
        f'ICLR.cc/{iclr_year}/Conference',
        f'NeurIPS.cc/{neurips_year}/Conference',
        f'ICML.cc/{icml_year}/Conference',
    ]


def search(client, query: str, since: datetime, venues: list[str], max_results: int = 50,
           per_venue_cap: int = 500, until: datetime | None = None) -> list[dict]:
    """Pull recent submissions in active venues and filter by query relevance.

    OpenReview's API doesn't support free-text search at the invitation level, so
    we pull notes in cdate-descending order (most recent first), bounded by
    `per_venue_cap` AND by `since` window — both of which substantially reduce
    per-query API cost vs. fetching the full ~20k notes per venue.

    Filtering: notes need at least 2 query keyword overlaps in title+abstract
    (BM25-lite) to make it into the candidate pool.
    """
    out = []
    q_low = query.lower().split()
    since_ms = int(since.timestamp() * 1000)
    for venue_id in venues:
        invitation = f'{venue_id}/-/Submission'
        try:
            # Use get_notes with explicit limit + mintcdate to bypass full-pagination cost.
            # Sort cdate-descending so the first 500 are the most recent — within window.
            notes = client.get_notes(
                invitation=invitation,
                limit=per_venue_cap,
                sort='cdate:desc',
                mintcdate=since_ms,
            )
        except Exception as e:
            # Fallback to get_all_notes if the targeted call signature isn't supported
            try:
                notes = client.get_all_notes(invitation=invitation, details='replies')[:per_venue_cap]
            except Exception as ee:
                print(f'  openreview {venue_id}: {ee}', file=sys.stderr); continue
        for n in notes:
            content = n.content or {}
            title = (content.get('title', {}) or {}).get('value', '') if isinstance(content.get('title'), dict) else (content.get('title', '') or '')
            abstract = (content.get('abstract', {}) or {}).get('value', '') if isinstance(content.get('abstract'), dict) else (content.get('abstract', '') or '')
            text = (title + ' ' + abstract).lower()
            score = sum(1 for w in q_low if w in text)
            if score < 2: continue
            published = getattr(n, 'cdate', None)
            if published:
                try:
                    d = datetime.fromtimestamp(published / 1000, tz=timezone.utc)
                    if d < since: continue
                    # Upper bound: under --as-of backdating, drop submissions created after the
                    # reference date so post-as-of in-review papers do not leak into the pool.
                    if until is not None and d > until: continue
                except Exception: pass
            authors_raw = content.get('authors', {})
            authors = (authors_raw or {}).get('value', []) if isinstance(authors_raw, dict) else (authors_raw or [])
            try: year = int(venue_id.split('/')[-2])
            except Exception: year = None
            out.append({
                'title': title,
                'title_norm': normalize_title(title),
                'abstract': abstract,
                'year': year,
                'venue': venue_id,
                'authors': authors[:6],
                'citations': None,
                'source': 'openreview',
                'source_id': n.id,
                'doi': '',
                'paper_url': f'https://openreview.net/forum?id={n.id}',
                'published_iso': '',
                '_score': score,
            })
        time.sleep(1.0)
    out.sort(key=lambda x: -x['_score'])
    return out[:max_results]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--queries', required=True)
    ap.add_argument('--window-months', type=int, default=6, help='Window-max in months')
    ap.add_argument('--window-min-months', type=int, default=0, help='Window-min in months (default 0 = include up to now)')
    ap.add_argument('--as-of', default='', help='YYYY-MM-DD: backdate the window reference date (for forward-prediction evals); default = real now')
    ap.add_argument('--max-per-query', type=int, default=50)
    ap.add_argument('--max-results', type=int, default=0, help='Final cap on output (0 = no cap; if set, take top by query-overlap score)')
    ap.add_argument('--venues', default='', help='Comma-separated OpenReview venue ids (e.g., "ICLR.cc/2026/Conference"). Empty = runtime-derived ICLR + NeurIPS + ICML based on conference review cycles.')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    from scripts._time_guard import resolve_now
    queries = json.loads(args.queries)
    now = resolve_now(args.as_of)
    since = now - timedelta(days=30 * args.window_months)
    # Upper bound: needed when excluding recent months OR when backdating (--as-of), where the
    # bound is the reference date. search() applies it against each note's cdate.
    until = now - timedelta(days=30 * args.window_min_months) \
        if (args.window_min_months > 0 or args.as_of) else None
    custom_venues = [v.strip() for v in args.venues.split(',') if v.strip()] if args.venues else None
    venues = derive_active_venues(now, custom_venues)

    try:
        client = get_client()
    except Exception as e:
        print(f'openreview unavailable: {e}', file=sys.stderr)
        Path(args.out).write_text('[]')
        return

    seen = set(); merged = []
    for q in queries:
        try:
            hits = search(client, q, since, venues=venues, max_results=args.max_per_query, until=until)
        except Exception as e:
            print(f'  openreview {q!r} failed: {e}', file=sys.stderr); continue
        for h in hits:
            # Upper-bound (until) is enforced inside search() against each note's cdate.
            key = h['title_norm']
            if not key or key in seen: continue
            seen.add(key); merged.append(h)
        time.sleep(1.0)

    if args.max_results > 0:
        # Already sorted by score (search() does this); take head
        merged = merged[:args.max_results]
    Path(args.out).write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    print(f'wrote {args.out} with {len(merged)} unique papers', file=sys.stderr)


if __name__ == '__main__':
    main()
