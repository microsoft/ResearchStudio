#!/usr/bin/env python3
"""Search for academic papers using Google Scholar."""

import argparse
import os
import time

from scholarly import scholarly, ProxyGenerator


_scholarly_proxy_initialized = False


def _init_scholarly_proxy():
    """Lazily initialize scholarly proxy; skip on incompatible httpx versions."""
    global _scholarly_proxy_initialized
    if _scholarly_proxy_initialized:
        return
    _scholarly_proxy_initialized = True
    API_KEY = os.environ.get("SCRAPER_API_KEY", "")
    if not API_KEY:
        return  # no ScraperAPI key configured; run scholarly without a proxy
    try:
        pg = ProxyGenerator()
        pg.ScraperAPI(API_KEY=API_KEY)
        scholarly.use_proxy(pg)
    except TypeError:
        # httpx >= 0.28 removed 'proxies' kwarg; fall back to no proxy
        pass


def search_papers_by_google_scholar(
    query: str,
    start_year: int,
    end_year: int,
    max_results: int = 10,
) -> list[dict]:
    """Search for papers on Google Scholar.

    Args:
        query: Search query string.
        start_year: Filter papers published from this year.
        end_year: Filter papers published up to this year.
        max_results: Maximum number of papers to return.

    Returns:
        List of paper dictionaries.
    """
    _init_scholarly_proxy()

    papers: list[dict] = []
    gen = scholarly.search_pubs(query, year_low=start_year, year_high=end_year, sort_by="relevance")

    for i, r in enumerate(gen):
        if i >= max_results:
            break
        bib = r.get("bib", {}) if isinstance(r, dict) else {}
        try:
            year = int(bib.get("pub_year"))
        except (TypeError, ValueError):
            continue
        if not (start_year <= year <= end_year):
            continue

        authors = bib.get("author", [])
        if not isinstance(authors, list):
            authors = [authors] if authors else []

        papers.append({
            "title": bib.get("title", ""),
            "authors": authors,
            "year": year,
            "abstract": bib.get("abstract", ""),
            "url": r.get("pub_url", "") if isinstance(r, dict) else "",
            "venue": bib.get("venue", "") or "",
            "citation_count": (r.get("num_citations", 0) if isinstance(r, dict) else 0) or 0,
            "publication_date": f"{year}-01-01",
            "source": "google_scholar",
        })

    return papers


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search papers on Google Scholar")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--start-year", type=int, required=True, help="Start year")
    parser.add_argument("--end-year", type=int, required=True, help="End year")
    parser.add_argument("--max-papers", type=int, default=10, help="Max number of papers (default: 10)")
    args = parser.parse_args()

    papers = search_papers_by_google_scholar(args.query, args.start_year, args.end_year, args.max_papers)
    print(papers[0] if papers else "No papers found.")

# python search_papers_by_google_scholar.py --query "data efficacy for LM training" --start-year 2024 --end-year 2026 --max-papers 20
