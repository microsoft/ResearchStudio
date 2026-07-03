#!/usr/bin/env python3
"""Search for academic papers using the Crossref API."""

import argparse
import time

import requests


def search_papers_by_crossref(
    query: str,
    start_year: int,
    end_year: int,
    max_results: int = 10,
) -> list[dict]:
    """Search for papers on Crossref.

    Args:
        query: Search query string.
        start_year: Filter papers published from this year.
        end_year: Filter papers published up to this year.
        max_results: Maximum number of papers to return.

    Returns:
        List of paper dictionaries.
    """
    url = "https://api.crossref.org/works"
    papers: list[dict] = []
    offset = 0
    limit = min(100, max_results)  # API max per request is 100

    while len(papers) < max_results:
        params = {
            "query": query,
            "offset": offset,
            "rows": limit,
            "filter": f"from-pub-date:{start_year},until-pub-date:{end_year}",
            "sort": "relevance",
            "order": "desc",
        }
        headers = {
            "User-Agent": "PaperSearch/1.0 (mailto:your-email@example.com)",
        }

        response = requests.get(url, params=params, headers=headers)

        if response.status_code == 429:
            print("Rate limited. Waiting 3 seconds...")
            time.sleep(3)
            continue

        response.raise_for_status()
        data = response.json()

        items = data.get("message", {}).get("items", [])
        if not items:
            break

        for item in items:
            # Extract authors
            authors = []
            for author in item.get("author", []):
                name_parts = []
                if author.get("given"):
                    name_parts.append(author["given"])
                if author.get("family"):
                    name_parts.append(author["family"])
                authors.append(" ".join(name_parts))

            # Extract publication date
            date_parts = item.get("published-print", item.get("published-online", {})).get("date-parts", [[None]])[0]
            year = date_parts[0] if date_parts else None
            publication_date = None
            if date_parts and date_parts[0]:
                publication_date = "-".join(str(d).zfill(2) for d in date_parts if d)

            papers.append({
                "title": item.get("title", [""])[0],
                "authors": authors,
                "year": year,
                "abstract": item.get("abstract", ""),
                "url": item.get("URL", ""),
                "venue": " ".join(item.get("container-title", [])),
                "citation_count": item.get("is-referenced-by-count", 0),
                "publication_date": publication_date,
                "source": "crossref",
            })

        offset += limit
        total_results = data.get("message", {}).get("total-results", 0)

        if offset >= total_results:
            break

        time.sleep(1)  # Be polite to the API

    return papers[:max_results]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search papers on Crossref")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--start-year", type=int, required=True, help="Start year")
    parser.add_argument("--end-year", type=int, required=True, help="End year")
    parser.add_argument("--max-papers", type=int, default=10, help="Max number of papers (default: 10)")
    args = parser.parse_args()

    papers = search_papers_by_crossref(args.query, args.start_year, args.end_year, args.max_papers)
    print(papers[0] if papers else "No papers found.")

# python search_papers_by_crossref.py --query "data efficiency for model training" --start-year 2024 --end-year 2026 --max-papers 20
