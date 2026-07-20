#!/usr/bin/env python3
"""Unified interface to search for academic papers across multiple sources.

Supported sources: arXiv, DBLP, OpenAlex, OpenReview, Semantic Scholar,
Crossref. (Google Scholar exists as an optional connector but is disabled by
default — it needs `scholarly`; see _SOURCE_MODULE.)

Post-processing (default ON, see postprocess.py): cross-source dedup with a
`found_in` provenance column, lexical relevance ranking against the query,
survey tagging (sunk, never dropped), and an opt-in --min-score filter that
prints exactly what it dropped. --raw restores the legacy per-source view.
"""

import argparse
import concurrent.futures
import importlib
import sys
from datetime import date, datetime
from typing import Optional

# Load .env (credentials for openreview etc.) before any source runs, so the aggregator works
# when invoked via bash without a shell-sourced .env. No-op if no .env is found.
try:
    from _env import load_env_once
    load_env_once()
except Exception:
    pass

# Map source name -> module that defines `search_papers_by_<source>`. Modules are imported
# LAZILY (only when a source is actually queried, see _load_source_func) so that a missing
# optional dependency for ONE source — e.g. `scholarly` for google_scholar — no longer crashes
# the whole aggregator at import time. By convention the function name equals the module name.
_SOURCE_MODULE = {
    "arxiv": "search_papers_by_arxiv",
    "dblp": "search_papers_by_dblp",
    # "google_scholar": "search_papers_by_google_scholar",  # needs `scholarly`; disabled by default
    "open_alex": "search_papers_by_open_alex",
    "openreview": "search_papers_by_openreview",
    "semantic_scholar": "search_papers_by_semantic_scholar",
    "crossref": "search_papers_by_crossref",
}
ALL_SOURCES = list(_SOURCE_MODULE.keys())


def _load_source_func(source: str):
    """Lazily import and return the search function for one source.

    Raises ImportError (with the underlying missing-module message) if the source's
    optional dependency is not installed — callers catch this and skip just that source."""
    module_name = _SOURCE_MODULE[source]
    module = importlib.import_module(module_name)
    return getattr(module, module_name)

def _parse_date(value, field_name: str) -> Optional[date]:
    """Parse a YYYY-MM-DD string (or pass through date/None) for the post-filter."""
    if value is None or isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError) as e:
        raise ValueError(f"{field_name} must be YYYY-MM-DD, got {value!r}") from e


def _filter_by_date_range(
    papers: list[dict],
    start_date: Optional[date],
    end_date: Optional[date],
) -> list[dict]:
    """Drop papers whose publication_date falls outside [start_date, end_date].

    Papers without a parseable publication_date are KEPT (we can't prove they're
    out of range, and dropping them would silently lose otherwise relevant results)."""
    if not start_date and not end_date:
        return papers
    kept: list[dict] = []
    for p in papers:
        pub_str = p.get("publication_date")
        if not pub_str:
            kept.append(p)
            continue
        try:
            pub = datetime.strptime(pub_str[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            kept.append(p)
            continue
        if start_date and pub < start_date:
            continue
        if end_date and pub > end_date:
            continue
        kept.append(p)
    return kept


def search_papers(
    query: str,
    start_year: int,
    end_year: int,
    max_results: int = 10,
    sources: Optional[list[str]] = None,
    parallel: bool = True,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict[str, list[dict]]:
    """Search for papers across multiple academic sources.

    Args:
        query: Search query string.
        start_year: Filter papers published from this year (used in source queries).
        end_year: Filter papers published up to this year (used in source queries).
        max_results: Maximum number of papers to return per source.
        sources: List of source names to search. Defaults to all sources.
            Valid values: arxiv, dblp, google_scholar, open_alex, openreview,
            semantic_scholar, crossref.
        parallel: Whether to query sources in parallel (default: True).
        start_date: Optional YYYY-MM-DD lower bound applied as a post-filter to all
            returned papers (finer-grained than start_year). Papers without a
            parseable publication_date are kept.
        end_date: Optional YYYY-MM-DD upper bound applied as a post-filter (inclusive).

    Returns:
        Dictionary mapping source name to list of paper dictionaries.
        Each paper dict contains: title, authors, year, abstract, url,
        venue, citation_count, publication_date, source.
    """
    sources = sources or ALL_SOURCES
    invalid = set(sources) - set(ALL_SOURCES)
    if invalid:
        raise ValueError(f"Unknown sources: {invalid}. Valid: {ALL_SOURCES}")
    # Multi-query union: `query` may be a list (or a single string). Each query
    # runs against every source; per-source results are unioned in query order.
    queries = [q for q in (query if isinstance(query, (list, tuple)) else [query]) if q]
    if not queries:
        raise ValueError("query must be a non-empty string or list of strings")

    start_d = _parse_date(start_date, "start_date")
    end_d = _parse_date(end_date, "end_date")
    if start_d and end_d and start_d > end_d:
        raise ValueError(f"start_date {start_d} is after end_date {end_d}")

    results: dict[str, list[dict]] = {}

    def _search(source: str) -> tuple[str, list[dict]]:
        try:
            func = _load_source_func(source)
        except Exception as e:
            # Missing optional dependency for this source — skip it, keep the others working.
            print(f"[{source}] unavailable (import failed: {e}); skipping this source.", file=sys.stderr)
            return source, []
        papers: list[dict] = []
        for q in queries:
            try:
                papers.extend(func(q, start_year, end_year, max_results))
            except Exception as e:
                print(f"[{source}] Error on query {q!r}: {e}", file=sys.stderr)
        return source, papers

    if parallel:
        gathered: dict[str, list[dict]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(sources)) as executor:
            futures = {executor.submit(_search, s): s for s in sources}
            for future in concurrent.futures.as_completed(futures):
                source, papers = future.result()
                gathered[source] = papers
        # Re-key in the REQUESTED order: as_completed yields in finish order,
        # which made both the dict and the CLI printout nondeterministic.
        results = {s: gathered.get(s, []) for s in sources}
    else:
        for source in sources:
            _, papers = _search(source)
            results[source] = papers

    if start_d or end_d:
        results = {s: _filter_by_date_range(ps, start_d, end_d) for s, ps in results.items()}

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Search papers across multiple academic sources",
    )
    parser.add_argument("--query", default=None, help="Search query")
    parser.add_argument(
        "--queries", default=None,
        help="Pipe-separated multi-query union (e.g. 'a|b|c'); alternative to --query",
    )
    parser.add_argument("--start-year", type=int, required=True, help="Start year")
    parser.add_argument("--end-year", type=int, required=True, help="End year")
    parser.add_argument(
        "--max-papers", type=int, default=10,
        help="Max number of papers per source (default: 10)",
    )
    parser.add_argument(
        "--sources", nargs="+", default=None,
        choices=ALL_SOURCES,
        help=f"Sources to search (default: all). Choices: {', '.join(ALL_SOURCES)}",
    )
    parser.add_argument(
        "--no-parallel", action="store_true",
        help="Disable parallel querying of sources",
    )
    parser.add_argument(
        "--start-date", default=None,
        help="Optional YYYY-MM-DD lower bound; applied as a post-filter (finer than --start-year)",
    )
    parser.add_argument(
        "--end-date", default=None,
        help="Optional YYYY-MM-DD inclusive upper bound; applied as a post-filter",
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="Legacy per-source view: no dedup, no ranking (full raw output)",
    )
    parser.add_argument(
        "--min-score", type=int, default=None,
        help="OPT-IN noise filter: drop papers with relevance score below N "
             "(the number dropped is always printed; default: keep everything)",
    )
    args = parser.parse_args()
    if not args.query and not args.queries:
        parser.error("one of --query / --queries is required")
    query_list = ([q.strip() for q in args.queries.split("|") if q.strip()]
                  if args.queries else [args.query])

    results = search_papers(
        query=query_list,
        start_year=args.start_year,
        end_year=args.end_year,
        max_results=args.max_papers,
        sources=args.sources,
        parallel=not args.no_parallel,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    if args.raw:
        total = 0
        for source, papers in results.items():
            print(f"\n{'='*60}")
            print(f"  {source}: {len(papers)} papers found")
            print(f"{'='*60}")
            for i, p in enumerate(papers, 1):
                print(f"  [{i}] {p['title']}")
                print(f"      Authors: {', '.join(p['authors'][:3])}{'...' if len(p['authors']) > 3 else ''}")
                print(f"      Year: {p['year']}  Citations: {p['citation_count']}  Venue: {p['venue']}")
                print(f"      URL: {p['url']}")
                print()
            total += len(papers)
        print(f"\nTotal: {total} papers from {len(results)} sources.")
    else:
        from postprocess import dedup, rank
        per_source = {s_: len(ps) for s_, ps in results.items()}
        merged = dedup(results)
        ranked, n_dropped = rank(merged, query_list, min_score=args.min_score)
        n_dup = sum(per_source.values()) - len(merged)
        print(f"\nper-source hits: " + ", ".join(f"{k}={v}" for k, v in per_source.items()))
        print(f"unique papers: {len(merged)} ({n_dup} cross-source duplicate records merged)")
        if n_dropped:
            print(f"DROPPED {n_dropped} paper(s) below --min-score {args.min_score} "
                  f"(opt-in filter; omit --min-score for full recall)")
        print(f"{'='*60}")
        for i, p in enumerate(ranked, 1):
            tag = " [survey]" if p.get("is_survey") else ""
            srcs = ",".join(p.get("found_in") or [])
            ids = " ".join(x for x in (f"doi:{p['doi']}" if p.get("doi") else "",
                                       f"arXiv:{p['arxiv_id']}" if p.get("arxiv_id") else "") if x)
            print(f"  [{i}] (score {p.get('relevance_score', 0)}){tag} {p['title']}")
            print(f"      Authors: {', '.join(p['authors'][:3])}{'...' if len(p['authors']) > 3 else ''}")
            print(f"      Year: {p['year']}  Citations: {p['citation_count']}  Venue: {p['venue']}")
            print(f"      Sources: {srcs}" + (f"  {ids}" if ids else ""))
            print(f"      URL: {p['url']}")
            print()
        print(f"Total: {len(ranked)} unique papers (ranked; surveys sunk to the bottom).")

# Example usage:
# python search_papers.py --query "data efficacy for LM training" --start-year 2024 --end-year 2026 --max-papers 20
# python search_papers.py --query "transformers" --start-year 2023 --end-year 2025 --sources arxiv semantic_scholar
