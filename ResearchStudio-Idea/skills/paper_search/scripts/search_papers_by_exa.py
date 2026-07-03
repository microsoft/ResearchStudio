#!/usr/bin/env python3
"""Search for academic papers using the Exa API."""

import argparse
import json
import os
import time
import urllib.parse
import urllib.request


def search_papers_by_exa(
    query: str,
    start_year: int,
    end_year: int,
    max_results: int = 10,
) -> list[dict]:
    """Search for papers using the Exa API.

    Args:
        query: Search query string.
        start_year: Filter papers published from this year.
        end_year: Filter papers published up to this year.
        max_results: Maximum number of papers to return.

    Returns:
        List of paper dictionaries.
    """
    EXA_API = "https://api.exa.ai/search"
    api_key = os.environ.get("EXA_API_KEY", "")
    if not api_key:
        raise ValueError("EXA_API_KEY environment variable is required.")

    payload = {
        "query": query,
        "numResults": max_results,
        "startPublishedDate": f"{start_year}-01-01T00:00:00.000Z",
        "endPublishedDate": f"{end_year}-12-31T23:59:59.000Z",
        "type": "auto",
        "category": "research paper",
        "contents": {
            "text": {"maxCharacters": 1000},
        },
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        EXA_API,
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "User-Agent": "PaperSearch/1.0",
        },
        method="POST",
    )

    max_retries = 1
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = 3 * (2 ** attempt)
                print(f"Rate limited, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise

    papers: list[dict] = []

    for item in result.get("results", []):
        published = item.get("publishedDate", "")
        year = None
        pub_date = ""
        if published:
            pub_date = published[:10]
            try:
                year = int(pub_date[:4])
            except (ValueError, IndexError):
                pass

        if year is not None and not (start_year <= year <= end_year):
            continue

        title = (item.get("title") or "").strip()
        abstract = (item.get("text") or "").strip()
        url = (item.get("url") or "").strip()
        authors = []  # Exa API does not return author metadata

        papers.append({
            "title": title,
            "authors": authors,
            "year": year,
            "abstract": abstract,
            "url": url,
            "venue": "",
            "citation_count": 0,
            "publication_date": pub_date,
            "source": "exa",
        })

    return papers


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search papers using Exa")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--start-year", type=int, required=True, help="Start year")
    parser.add_argument("--end-year", type=int, required=True, help="End year")
    parser.add_argument("--max-papers", type=int, default=10, help="Max number of papers (default: 10)")
    args = parser.parse_args()

    papers = search_papers_by_exa(args.query, args.start_year, args.end_year, args.max_papers)
    print(papers[0] if papers else "No papers found.")

# python search_papers_by_exa.py --query "data efficacy for LM training" --start-year 2024 --end-year 2026 --max-papers 10
