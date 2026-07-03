#!/usr/bin/env python3
"""Search for academic papers using the Semantic Scholar API."""

import argparse
import os
import time

import requests


def search_papers_by_semantic_scholar(
    query: str,
    start_year: int,
    end_year: int,
    max_results: int = 10,
) -> list[dict]:
    """Search for papers on Semantic Scholar.

    Args:
        query: Search query string.
        start_year: Filter papers published from this year.
        end_year: Filter papers published up to this year.
        max_results: Maximum number of papers to return.

    Returns:
        List of paper dictionaries.
    """
    API_KEY = os.environ.get("SEMANTICSCHOLAR_API_KEY", "")
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    fields = "title,authors,year,abstract,citationCount,url,venue,publicationDate"

    papers: list[dict] = []
    offset = 0
    limit = min(100, max_results)  # API max per request is 100

    while len(papers) < max_results:
        params = {
            "query": query,
            "offset": offset,
            "limit": limit,
            "fields": fields,
            "year": f"{start_year}-{end_year}",
        }
        headers = {"x-api-key": API_KEY} if API_KEY else {}

        response = requests.get(url, params=params, headers=headers)

        if response.status_code == 429:
            print("Rate limited. Waiting 3 seconds...")
            time.sleep(3)
            continue

        response.raise_for_status()
        data = response.json()

        if not data.get("data"):
            break

        for item in data["data"]:
            authors = [
                a.get("name", "")
                for a in item.get("authors", [])
                if a.get("name")
            ]
            papers.append({
                "title": item.get("title", ""),
                "authors": authors,
                "year": item.get("year"),
                "abstract": item.get("abstract", "") or "",
                "url": item.get("url", ""),
                "venue": item.get("venue", "") or "",
                "citation_count": item.get("citationCount", 0),
                "publication_date": item.get("publicationDate", ""),
                "source": "semantic_scholar",
            })

        offset += limit

        if offset >= data.get("total", 0):
            break

        time.sleep(1)  # Be polite to the API

    return papers[:max_results]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search papers on Semantic Scholar")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--start-year", type=int, required=True, help="Start year")
    parser.add_argument("--end-year", type=int, required=True, help="End year")
    parser.add_argument("--max-papers", type=int, default=10, help="Max number of papers (default: 10)")
    args = parser.parse_args()

    papers = search_papers_by_semantic_scholar(args.query, args.start_year, args.end_year, args.max_papers)
    print(papers[0] if papers else "No papers found.")

# python search_papers_by_semantic_scholar.py --query "data efficacy for LM training" --start-year 2024 --end-year 2026 --max-papers 20
