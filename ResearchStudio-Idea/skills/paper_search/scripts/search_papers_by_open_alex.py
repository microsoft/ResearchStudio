#!/usr/bin/env python3
"""Search for academic papers using the OpenAlex API."""

import argparse
import os
import time

import requests


def search_papers_by_open_alex(
    query: str,
    start_year: int,
    end_year: int,
    max_results: int = 10,
) -> list[dict]:
    """Search for papers on OpenAlex.

    Args:
        query: Search query string.
        start_year: Filter papers published from this year.
        end_year: Filter papers published up to this year.
        max_results: Maximum number of papers to return.

    Returns:
        List of paper dictionaries.
    """
    API_KEY = os.environ.get("OPENALEX_API_KEY", "")
    url = "https://api.openalex.org/works"
    papers: list[dict] = []
    page = 1
    per_page = min(200, max_results)  # API max per request is 200

    while len(papers) < max_results:
        params = {
            "search.semantic": query,
            "filter": f"publication_year:{start_year}-{end_year}",
            "sort": "relevance_score:desc",
            "page": page,
            "per-page": per_page,
            #"mailto": "your_email@example.com",  # OpenAlex polite pool
        }
        headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}

        response = requests.get(url, params=params, headers=headers)

        if response.status_code == 429:
            print("Rate limited. Waiting 3 seconds...")
            time.sleep(3)
            continue

        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        if not results:
            break

        for work in results:
            papers.append({
                "title": work.get("title", ""),
                "authors": [
                    authorship["author"]["display_name"]
                    for authorship in work.get("authorships", [])
                    if authorship.get("author", {}).get("display_name")
                ],
                "year": work.get("publication_year"),
                "abstract": _reconstruct_abstract(work.get("abstract_inverted_index")),
                "url": work.get("doi") or work.get("id", ""),
                "venue": (work.get("primary_location", {}).get("source") or {}).get("display_name", ""),
                "citation_count": work.get("cited_by_count", 0),
                "publication_date": work.get("publication_date", ""),
                "source": "openalex",
            })

        page += 1
        total_count = data.get("meta", {}).get("count", 0)

        if page * per_page >= total_count:
            break

        time.sleep(1)  # Be polite to the API

    return papers[:max_results]


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """Reconstruct abstract text from OpenAlex inverted index format."""
    if not inverted_index:
        return ""
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(word for _, word in word_positions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search papers on OpenAlex")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--start-year", type=int, required=True, help="Start year")
    parser.add_argument("--end-year", type=int, required=True, help="End year")
    parser.add_argument("--max-papers", type=int, default=10, help="Max number of papers (default: 10)")
    args = parser.parse_args()

    papers = search_papers_by_open_alex(args.query, args.start_year, args.end_year, args.max_papers)
    print(papers[0] if papers else "No papers found.")

# python search_papers_by_open_alex.py --query "data efficacy for LM training" --start-year 2024 --end-year 2026 --max-papers 20
