"""
Download paper PDFs from OpenReview and extract Introduction sections.
Enriches existing pattern JSONL files with introduction text.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import fitz  # pymupdf
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

_client = None


def get_client():
    global _client
    if _client is None:
        import openreview
        _client = openreview.api.OpenReviewClient(
            baseurl="https://api2.openreview.net",
            username=config.OPENREVIEW_USERNAME,
            password=config.OPENREVIEW_PASSWORD,
        )
    return _client


def download_pdf(openreview_id: str) -> bytes | None:
    """Download PDF from OpenReview. Try v2 first, fallback to v1."""
    # Try v2
    try:
        client = get_client()
        return client.get_pdf(openreview_id)
    except Exception:
        pass

    # Fallback: try v1
    try:
        import openreview
        client_v1 = openreview.Client(
            baseurl="https://api.openreview.net",
            username=config.OPENREVIEW_USERNAME,
            password=config.OPENREVIEW_PASSWORD,
        )
        return client_v1.get_pdf(openreview_id)
    except Exception:
        pass

    # Fallback: direct HTTP with PDF URL
    try:
        import requests
        url = f"https://openreview.net/pdf?id={openreview_id}"
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
    except Exception:
        pass

    return None


def extract_introduction(pdf_bytes: bytes, max_chars: int = 2000) -> str:
    """Extract Introduction section from PDF bytes."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = ""
        for page_num in range(min(5, len(doc))):
            text += doc[page_num].get_text()
        doc.close()
    except Exception:
        return ""

    lines = text.split("\n")
    intro_start = None
    intro_end = None

    for i, line in enumerate(lines):
        l = line.strip().lower()
        # Match "1. Introduction" or "1 Introduction" or just "Introduction"
        if re.match(r"^(1[\.\s]+)?introduction\s*$", l):
            intro_start = i
        elif intro_start and re.match(r"^(2[\.\s]|ii[\.\s]|related\s+work|background|preliminar)", l):
            intro_end = i
            break

    if intro_start is None:
        return ""

    intro = "\n".join(lines[intro_start : intro_end if intro_end else intro_start + 120])

    # Clean up
    intro = re.sub(r"\n{3,}", "\n\n", intro)

    if len(intro) > max_chars:
        intro = intro[:max_chars] + "..."

    return intro.strip()


def enrich_file_with_introductions(jsonl_path: str, max_papers: int = None):
    """Add introduction text to papers in a JSONL file."""
    papers = []
    with open(jsonl_path) as f:
        for line in f:
            if line.strip():
                papers.append(json.loads(line))

    if max_papers:
        papers = papers[:max_papers]

    enriched = 0
    failed = 0

    for paper in tqdm(papers, desc=f"Fetching intros for {os.path.basename(jsonl_path)}"):
        if paper.get("introduction"):
            enriched += 1
            continue

        oid = paper.get("openreview_id", "")
        if not oid:
            failed += 1
            continue

        pdf = download_pdf(oid)
        if pdf:
            intro = extract_introduction(pdf)
            if intro and len(intro) > 100:
                paper["introduction"] = intro
                enriched += 1
            else:
                paper["introduction"] = ""
                failed += 1
        else:
            paper["introduction"] = ""
            failed += 1

        time.sleep(0.5)  # Rate limit

    # Save back
    with open(jsonl_path, "w") as f:
        for p in papers:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"  Enriched: {enriched}, Failed: {failed}, Total: {len(papers)}")


def enrich_all():
    """Enrich all raw JSONL files."""
    for fname in sorted(os.listdir(config.RAW_DIR)):
        if not fname.endswith("_Oral.jsonl"):
            continue
        path = os.path.join(config.RAW_DIR, fname)
        print(f"\n{fname}")
        enrich_file_with_introductions(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--input", type=str)
    parser.add_argument("--max", type=int, default=None)
    args = parser.parse_args()

    if args.all:
        enrich_all()
    elif args.input:
        enrich_file_with_introductions(args.input, max_papers=args.max)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
