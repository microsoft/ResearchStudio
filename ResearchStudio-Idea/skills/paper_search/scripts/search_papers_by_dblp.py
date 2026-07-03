#!/usr/bin/env python3
"""Search for academic papers using the DBLP API."""

import argparse
import re
import time

import requests


def search_papers_by_dblp(
    query: str,
    start_year: int,
    end_year: int,
    max_results: int = 10,
) -> list[dict]:
    """Search for papers on DBLP.

    Args:
        query: Search query string.
        start_year: Filter papers published from this year.
        end_year: Filter papers published up to this year.
        max_results: Maximum number of papers to return.

    Returns:
        List of paper dictionaries.
    """
    url = "https://dblp.org/search/publ/api"
    papers: list[dict] = []
    offset = 0
    limit = min(1000, max_results)  # DBLP max per request is 1000

    while len(papers) < max_results:
        params = {
            "q": query,
            "format": "json",
            "h": limit,
            "f": offset,
        }

        response = requests.get(url, params=params)

        if response.status_code == 429:
            print("Rate limited. Waiting 3 seconds...")
            time.sleep(3)
            continue

        response.raise_for_status()
        data = response.json()

        hits = data.get("result", {}).get("hits", {})
        total = int(hits.get("@total", 0))
        hit_list = hits.get("hit", [])

        if not hit_list:
            break

        for hit in hit_list:
            info = hit.get("info", {})
            year = int(info.get("year", 0))

            # Filter by year range
            if year < start_year or year > end_year:
                continue

            # Normalize authors
            authors_info = info.get("authors", {}).get("author", [])
            if isinstance(authors_info, dict):
                authors_info = [authors_info]
            authors = [a.get("text", "") if isinstance(a, dict) else a for a in authors_info]

            papers.append({
                "title": info.get("title", ""),
                "authors": authors,
                "year": year,
                "abstract": "",
                "url": info.get("ee", info.get("url", "")),
                "venue": info.get("venue", ""),
                "citation_count": 0,
                "publication_date": f"{year}-01-01",
                "source": "dblp",
            })

        offset += limit

        if offset >= total:
            break

        time.sleep(1)  # Be polite to the API

    # Fetch abstracts for papers that have a DOI
    papers = papers[:max_results]
    for paper in papers:
        abstract = _fetch_abstract_from_doi(paper.get("url", ""))
        if abstract:
            paper["abstract"] = abstract
        time.sleep(0.5)  # Be polite to the Crossref API

    return papers


def _fetch_abstract_from_doi(url: str) -> str:
    """Try to fetch abstract from Crossref using a DOI extracted from the URL."""
    if not url:
        return ""
    # Extract DOI from URL like https://doi.org/10.xxxx/yyyy or direct DOI
    match = re.search(r'(10\.\d{4,9}/[^\s]+)', url)
    if not match:
        return ""
    doi = match.group(1)
    try:
        resp = requests.get(
            f"https://api.crossref.org/works/{doi}",
            headers={"Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            abstract = data.get("message", {}).get("abstract", "")
            # Strip JATS/XML tags if present
            if abstract:
                abstract = re.sub(r'<[^>]+>', '', abstract).strip()
            return abstract
    except Exception:
        pass
    return ""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search papers on DBLP")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--start-year", type=int, required=True, help="Start year")
    parser.add_argument("--end-year", type=int, required=True, help="End year")
    parser.add_argument("--max-papers", type=int, default=10, help="Max number of papers (default: 10)")
    args = parser.parse_args()

    papers = search_papers_by_dblp(args.query, args.start_year, args.end_year, args.max_papers)
    print(papers[0] if papers else "No papers found.")

# python search_papers_by_dblp.py --query "data efficiency for model training" --start-year 2024 --end-year 2026 --max-papers 20
