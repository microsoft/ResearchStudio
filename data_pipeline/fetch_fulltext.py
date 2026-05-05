"""
Enrich filtered papers with full-text content from arXiv.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

try:
    import arxiv
except ImportError:
    arxiv = None


def fetch_arxiv_abstract_and_url(title: str) -> dict | None:
    """
    Search arXiv by title, return metadata if found.
    We use the arxiv package for search.
    """
    if arxiv is None:
        return None

    # Use first 10 words of title for search
    query = " ".join(title.split()[:10])
    try:
        search = arxiv.Search(query=query, max_results=3)
        client = arxiv.Client()
        for result in client.results(search):
            # Check title similarity
            if _title_similar(result.title, title):
                return {
                    "arxiv_id": result.entry_id,
                    "arxiv_url": result.pdf_url,
                    "arxiv_abstract": result.summary,
                    "categories": [c for c in result.categories],
                }
        return None
    except Exception as e:
        print(f"  [arXiv error] {e}")
        return None


def _title_similar(a: str, b: str) -> bool:
    """Check if two titles are similar enough (simple word overlap)."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    overlap = len(wa & wb) / max(len(wa | wb), 1)
    return overlap > 0.6


def enrich_papers_with_fulltext(filtered_file: str):
    """Add arXiv info to filtered papers. Updates the JSONL file in-place."""
    papers = []
    with open(filtered_file) as f:
        for line in f:
            if line.strip():
                papers.append(json.loads(line))

    enriched = 0
    for paper in tqdm(papers, desc="Enriching with arXiv"):
        if paper.get("arxiv_url"):
            enriched += 1
            continue
        info = fetch_arxiv_abstract_and_url(paper["title"])
        if info:
            paper.update(info)
            enriched += 1
        time.sleep(1)  # Rate limit

    with open(filtered_file, "w") as f:
        for p in papers:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"Enriched: {enriched}/{len(papers)} papers with arXiv data")


def enrich_all():
    """Enrich all filtered files."""
    for fname in sorted(os.listdir(config.FILTERED_DIR)):
        if fname.endswith(".jsonl"):
            path = os.path.join(config.FILTERED_DIR, fname)
            print(f"\nProcessing {fname}")
            enrich_papers_with_fulltext(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--input", type=str)
    args = parser.parse_args()

    if args.all:
        enrich_all()
    elif args.input:
        enrich_papers_with_fulltext(args.input)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
