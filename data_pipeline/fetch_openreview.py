"""
Fetch papers and reviews from OpenReview API.
Supports ICLR (2020-2025) and NeurIPS (2023-2025).
Handles both API v1 (older conferences) and v2 (newer ones).
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import openreview
from tqdm import tqdm

# Add parent dir to path so we can import config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# Years that use API v2 (Submission invitation)
V2_YEARS = {
    "ICLR": [2024, 2025],
    "NeurIPS": [2023, 2024, 2025],
    "ICML": [2023, 2024, 2025],
}


def get_client_v2() -> openreview.api.OpenReviewClient:
    """Connect to OpenReview API v2."""
    return openreview.api.OpenReviewClient(
        baseurl="https://api2.openreview.net",
        username=config.OPENREVIEW_USERNAME,
        password=config.OPENREVIEW_PASSWORD,
    )


def get_client_v1() -> openreview.Client:
    """Connect to OpenReview API v1."""
    return openreview.Client(
        baseurl="https://api.openreview.net",
        username=config.OPENREVIEW_USERNAME,
        password=config.OPENREVIEW_PASSWORD,
    )


def get_client():
    """Backward compat: return v2 client."""
    return get_client_v2()


def _val(field):
    """Extract value from OpenReview v2 content field (may be dict with 'value' key or plain)."""
    if isinstance(field, dict):
        return field.get("value", field)
    return field


def parse_rating_number(rating_str) -> float | None:
    """Extract numeric rating from strings like '8: accept, good paper'."""
    if rating_str is None:
        return None
    s = str(rating_str)
    m = re.match(r"(\d+)", s)
    return float(m.group(1)) if m else None


def classify_venue(venue_str: str) -> str:
    """Classify a venue string into Oral/Spotlight/Poster/Rejected/Withdrawn/Unknown."""
    v = venue_str.lower()
    # Explicit oral/spotlight
    if "oral" in v:
        return "Oral"
    if "spotlight" in v:
        return "Spotlight"
    # ICLR 2023 style: "notable top 5%" = Oral, "notable top 25%" = Spotlight
    if "notable top 5%" in v:
        return "Oral"
    if "notable top 25%" in v:
        return "Spotlight"
    if "poster" in v:
        return "Poster"
    if "withdrawn" in v:
        return "Withdrawn"
    if "desk rejected" in v or "desk reject" in v:
        return "Desk Rejected"
    if "submitted to" in v:
        return "Rejected"
    # Accept variants (e.g. "Accept (Oral)", "Accept (Talk)", "Accept (Poster)")
    if "accept" in v:
        if "oral" in v or "talk" in v:
            return "Oral"
        if "spotlight" in v:
            return "Spotlight"
        return "Poster"
    if "reject" in v:
        return "Rejected"
    return "Unknown"


def parse_review(reply: dict) -> dict | None:
    """Parse a single review reply dict into structured data."""
    invitations = reply.get("invitations", [])
    if not any("Official_Review" in inv for inv in invitations):
        return None

    content = reply.get("content", {})
    sigs = reply.get("signatures", [])
    reviewer_id = sigs[0] if sigs else "Unknown"

    rating = parse_rating_number(_val(content.get("rating")))
    confidence = parse_rating_number(_val(content.get("confidence")))

    return {
        "reviewer_id": reviewer_id,
        "rating": rating,
        "confidence": confidence,
        "soundness": parse_rating_number(_val(content.get("soundness"))),
        "presentation": parse_rating_number(_val(content.get("presentation"))),
        "contribution": parse_rating_number(_val(content.get("contribution"))),
        "strengths": _val(content.get("strengths", "")),
        "weaknesses": _val(content.get("weaknesses", "")),
        "questions": _val(content.get("questions", "")),
        "summary": _val(content.get("summary", "")),
    }


def parse_meta_review(reply: dict) -> str | None:
    """Extract meta-review text from an AC reply."""
    invitations = reply.get("invitations", [])
    if not any("Meta_Review" in inv for inv in invitations):
        return None
    content = reply.get("content", {})
    # Different fields: metareview, recommendation, etc.
    for field in ["metareview", "recommendation", "summary"]:
        val = _val(content.get(field, ""))
        if val:
            return str(val)
    return None


def parse_submission(note, conference: str, year: int) -> dict:
    """Parse an OpenReview Note into our standard paper dict."""
    c = note.content
    venue_str = _val(c.get("venue", ""))
    decision = classify_venue(venue_str)

    # Extract reviews and meta-review from directReplies
    replies = (note.details or {}).get("directReplies", [])
    reviews = []
    meta_review = None
    for r in replies:
        rev = parse_review(r)
        if rev:
            reviews.append(rev)
        mr = parse_meta_review(r)
        if mr and meta_review is None:
            meta_review = mr

    ratings = [r["rating"] for r in reviews if r["rating"] is not None]
    avg_rating = sum(ratings) / len(ratings) if ratings else 0.0

    # PDF url
    pdf_val = _val(c.get("pdf", ""))
    if pdf_val and not pdf_val.startswith("http"):
        pdf_url = f"https://openreview.net{pdf_val}"
    else:
        pdf_url = pdf_val or ""

    return {
        "paper_id": f"{conference.lower()}{year}_{note.id}",
        "openreview_id": note.id,
        "title": _val(c.get("title", "")),
        "abstract": _val(c.get("abstract", "")),
        "authors": _val(c.get("authors", [])),
        "keywords": _val(c.get("keywords", [])),
        "pdf_url": pdf_url,
        "decision": decision,
        "venue": venue_str,
        "year": year,
        "conference": conference,
        "reviews": reviews,
        "meta_review": meta_review or "",
        "avg_rating": round(avg_rating, 2),
        "max_rating": max(ratings) if ratings else 0,
        "min_rating": min(ratings) if ratings else 0,
        "num_reviews": len(reviews),
    }


def _is_v2(conference: str, year: int) -> bool:
    return year in V2_YEARS.get(conference, [])


def parse_review_v1(reply) -> dict | None:
    """Parse a review from API v1 Note object."""
    inv = getattr(reply, "invitation", "") or ""
    if "Official_Review" not in inv:
        return None

    c = reply.content or {}
    sigs = reply.signatures or []

    # v1 may have "review" (older) or "strengths"/"weaknesses" (newer)
    strengths = c.get("strengths", c.get("strength", ""))
    weaknesses = c.get("weaknesses", c.get("weakness", ""))
    summary = c.get("summary", c.get("review", ""))

    return {
        "reviewer_id": sigs[0] if sigs else "Unknown",
        "rating": parse_rating_number(c.get("rating", c.get("recommendation"))),
        "confidence": parse_rating_number(c.get("confidence")),
        "soundness": parse_rating_number(c.get("soundness")),
        "presentation": parse_rating_number(c.get("presentation")),
        "contribution": parse_rating_number(c.get("contribution")),
        "strengths": strengths or "",
        "weaknesses": weaknesses or "",
        "questions": c.get("questions", ""),
        "summary": summary or "",
    }


def parse_meta_review_v1(reply) -> str | None:
    inv = getattr(reply, "invitation", "") or ""
    if "Meta_Review" not in inv and "Decision" not in inv:
        return None
    c = reply.content or {}
    for field in ["metareview", "recommendation", "decision", "comment"]:
        val = c.get(field, "")
        if val:
            return str(val)
    return None


def classify_decision_v1(note) -> str:
    """Classify decision for v1 notes using directReplies or venue field."""
    c = note.content or {}

    # Check venue field first (if present)
    venue = c.get("venue", "")
    if venue:
        return classify_venue(venue)

    # Check decision in directReplies
    replies = []
    if hasattr(note, "details") and note.details:
        replies = note.details.get("directReplies", [])

    for r in replies:
        inv = ""
        if isinstance(r, dict):
            inv = r.get("invitation", "")
            content = r.get("content", {})
        else:
            inv = getattr(r, "invitation", "")
            content = getattr(r, "content", {}) or {}

        if "Decision" in inv:
            decision_text = content.get("decision", "")
            if isinstance(decision_text, dict):
                decision_text = decision_text.get("value", "")
            return classify_venue(str(decision_text))

    return "Unknown"


def parse_submission_v1(note, conference: str, year: int) -> dict:
    """Parse an API v1 Note into our standard paper dict."""
    c = note.content or {}
    decision = classify_decision_v1(note)

    replies = []
    if hasattr(note, "details") and note.details:
        replies_raw = note.details.get("directReplies", [])
        for r in replies_raw:
            # v1 directReplies can be dicts or Note objects
            if isinstance(r, dict):
                # Convert to a mock object-like access
                class _N:
                    def __init__(self, d):
                        self.invitation = d.get("invitation", "")
                        self.content = d.get("content", {})
                        self.signatures = d.get("signatures", [])
                replies.append(_N(r))
            else:
                replies.append(r)

    reviews = []
    meta_review = None
    for r in replies:
        rev = parse_review_v1(r)
        if rev:
            reviews.append(rev)
        mr = parse_meta_review_v1(r)
        if mr and meta_review is None:
            meta_review = mr

    ratings = [r["rating"] for r in reviews if r["rating"] is not None]
    avg_rating = sum(ratings) / len(ratings) if ratings else 0.0

    pdf_val = c.get("pdf", "")
    if pdf_val and not pdf_val.startswith("http"):
        pdf_url = f"https://openreview.net{pdf_val}"
    else:
        pdf_url = pdf_val or ""

    return {
        "paper_id": f"{conference.lower()}{year}_{note.id}",
        "openreview_id": note.id,
        "title": c.get("title", ""),
        "abstract": c.get("abstract", ""),
        "authors": c.get("authors", []),
        "keywords": c.get("keywords", []),
        "pdf_url": pdf_url,
        "decision": decision,
        "venue": c.get("venue", ""),
        "year": year,
        "conference": conference,
        "reviews": reviews,
        "meta_review": meta_review or "",
        "avg_rating": round(avg_rating, 2),
        "max_rating": max(ratings) if ratings else 0,
        "min_rating": min(ratings) if ratings else 0,
        "num_reviews": len(reviews),
    }


def fetch_conference_papers(
    client,
    conference: str,
    year: int,
    decision_filter: list[str] | None = None,
) -> list[dict]:
    """
    Fetch all papers for a conference/year, optionally filtered by decision.
    Automatically selects v1 or v2 API based on conference/year.
    """
    venue_id = config.TARGET_CONFERENCES[conference]["venue_ids"].get(year)
    if not venue_id:
        print(f"  [SKIP] No venue_id configured for {conference} {year}")
        return []

    use_v2 = _is_v2(conference, year)

    if use_v2:
        invitation = f"{venue_id}/-/Submission"
        print(f"  [v2] Fetching from {invitation} ...")
        all_notes = client.get_all_notes(invitation=invitation, details="directReplies")
        parse_fn = parse_submission
    else:
        # v1: try Blind_Submission first, then Submission
        # Use the passed client if it's v1, otherwise create a new one
        if isinstance(client, openreview.Client):
            client_v1 = client
        else:
            client_v1 = get_client_v1()
        all_notes = []
        for suffix in ["Blind_Submission", "Submission"]:
            invitation = f"{venue_id}/-/{suffix}"
            print(f"  [v1] Trying {invitation} ...")
            try:
                all_notes = client_v1.get_all_notes(invitation=invitation, details="directReplies")
                if all_notes:
                    break
            except Exception as e:
                print(f"    Failed: {str(e)[:80]}")
        parse_fn = parse_submission_v1

    print(f"  Total submissions fetched: {len(all_notes)}")

    papers = []
    for note in tqdm(all_notes, desc=f"  Parsing {conference} {year}"):
        paper = parse_fn(note, conference, year)
        if decision_filter is None or paper["decision"] in decision_filter:
            papers.append(paper)

    print(f"  Papers after filtering: {len(papers)}")
    if decision_filter:
        from collections import Counter
        counts = Counter(p["decision"] for p in papers)
        for d, cnt in sorted(counts.items()):
            print(f"    {d}: {cnt}")

    return papers


def save_papers(papers: list[dict], filepath: str):
    """Save papers to JSONL file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for p in papers:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"  Saved {len(papers)} papers to {filepath}")


def load_papers(filepath: str) -> list[dict]:
    """Load papers from JSONL file."""
    papers = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                papers.append(json.loads(line))
    return papers


def fetch_and_save(
    conference: str,
    year: int,
    decisions: list[str],
    client=None,
):
    """Fetch papers for specific decisions and save each decision to a separate file."""
    if client is None:
        if _is_v2(conference, year):
            client = get_client_v2()
        else:
            client = get_client_v1()

    # Check which files already exist
    needed = []
    for d in decisions:
        filepath = os.path.join(config.RAW_DIR, f"{conference}_{year}_{d}.jsonl")
        if os.path.exists(filepath):
            count = sum(1 for _ in open(filepath))
            print(f"  [SKIP] {filepath} already exists ({count} papers)")
        else:
            needed.append(d)

    if not needed:
        return

    # Fetch all at once (one API call), then split by decision
    all_papers = fetch_conference_papers(client, conference, year, decision_filter=needed)

    for d in needed:
        subset = [p for p in all_papers if p["decision"] == d]
        if subset:
            filepath = os.path.join(config.RAW_DIR, f"{conference}_{year}_{d}.jsonl")
            save_papers(subset, filepath)


def fetch_and_save_all():
    """Fetch all configured conferences and years."""
    client = get_client()

    for conf, conf_cfg in config.TARGET_CONFERENCES.items():
        for year in conf_cfg["years"]:
            print(f"\n{'='*60}")
            print(f"Processing {conf} {year}")
            print(f"{'='*60}")
            decisions = ["Oral", "Spotlight", "Poster", "Rejected"]
            try:
                fetch_and_save(conf, year, decisions, client)
            except Exception as e:
                print(f"  [ERROR] {conf} {year}: {e}")
            time.sleep(1)  # Rate limiting between conferences


def print_stats(filepath: str):
    """Print statistics about a JSONL file."""
    papers = load_papers(filepath)
    if not papers:
        print("No papers found.")
        return

    total = len(papers)
    with_reviews = sum(1 for p in papers if p["num_reviews"] > 0)
    all_review_counts = [p["num_reviews"] for p in papers if p["num_reviews"] > 0]
    avg_reviews = sum(all_review_counts) / len(all_review_counts) if all_review_counts else 0
    all_ratings = [p["avg_rating"] for p in papers if p["avg_rating"] > 0]
    avg_rating = sum(all_ratings) / len(all_ratings) if all_ratings else 0

    print(f"\n{'='*60}")
    print(f"Statistics for: {filepath}")
    print(f"{'='*60}")
    print(f"成功获取：{total} 篇")
    print(f"有审稿意见：{with_reviews} 篇")
    print(f"平均审稿数量：{avg_reviews:.1f} 条/篇")
    print(f"平均评分：{avg_rating:.1f} 分")

    # Sample
    sample = papers[0]
    print(f"示例论文标题：{sample['title']}")
    if sample["reviews"]:
        rev = sample["reviews"][0]
        strengths = rev.get("strengths", "")
        if isinstance(strengths, str) and len(strengths) > 200:
            strengths = strengths[:200] + "..."
        print(f"示例审稿意见（前200字）：{strengths}")


def main():
    parser = argparse.ArgumentParser(description="Fetch OpenReview papers")
    parser.add_argument("--conference", type=str, default=None, help="Conference name (ICLR/NeurIPS)")
    parser.add_argument("--year", type=int, default=None, help="Year")
    parser.add_argument("--decision", type=str, default=None, help="Decision filter (Oral/Spotlight/Poster/Rejected)")
    parser.add_argument("--all", action="store_true", help="Fetch all configured conferences/years")
    parser.add_argument("--stats", type=str, default=None, help="Print stats for a JSONL file")
    args = parser.parse_args()

    if args.stats:
        print_stats(args.stats)
        return

    if args.all:
        fetch_and_save_all()
        return

    if args.conference and args.year:
        decisions = [args.decision] if args.decision else ["Oral", "Spotlight", "Poster", "Rejected"]
        fetch_and_save(args.conference, args.year, decisions)
        # Print stats for what we just fetched
        for d in decisions:
            fp = os.path.join(config.RAW_DIR, f"{args.conference}_{args.year}_{d}.jsonl")
            if os.path.exists(fp):
                print_stats(fp)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
