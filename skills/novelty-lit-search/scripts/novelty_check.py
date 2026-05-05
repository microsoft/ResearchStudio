"""Collision mode: classify the top retrieval hits against a candidate idea.

Why: after Phase 3 generates candidate ideas, Phase 5 must check whether each idea
collides with recent published work. A 7-class taxonomy gives the user actionable
recommendations (regenerate, narrow, change mechanism, etc.).

Capability profile: [CLASSIFY_FAST] for the per-paper classification call;
[EMBEDDING] for the cosine pre-filter that selects which papers to classify.

I/O:
  python -m scripts.novelty_check --idea idea.json --hits lit_collision.json --out report.json
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

CATEGORIES = {
    1: 'exact collision', 2: 'mechanism collision', 3: 'claim collision',
    4: 'evaluation collision', 5: 'terminology reframing only',
    6: 'weak domain transfer', 7: 'non-blocking related work',
}

ACTION_TABLE = {
    # (category, novelty_target) -> action
    (1, 'oral'): 'regenerate',           (1, 'publication'): 'regenerate',          (1, 'best_paper'): 'regenerate',
    (2, 'oral'): 'change_mechanism',      (2, 'publication'): 'narrow_claim',        (2, 'best_paper'): 'regenerate',
    (3, 'oral'): 'narrow_claim',          (3, 'publication'): 'narrow_claim',        (3, 'best_paper'): 'regenerate',
    (4, 'oral'): 'change_evaluation',     (4, 'publication'): 'reposition',          (4, 'best_paper'): 'change_evaluation',
    (5, 'oral'): 'regenerate',            (5, 'publication'): 'regenerate',          (5, 'best_paper'): 'regenerate',
    (6, 'oral'): 'change_mechanism',      (6, 'publication'): 'downgrade_l1',        (6, 'best_paper'): 'regenerate',
    (7, 'oral'): 'pass',                  (7, 'publication'): 'pass',                (7, 'best_paper'): 'pass',
}

SYSTEM = """You read a candidate research idea and a retrieved paper, and classify the paper into one of 7 collision categories.

Categories:
1 exact collision        — same core idea is already published.
2 mechanism collision    — same mechanism, different task.
3 claim collision        — same claim/theorem/bound, different experimental subject.
4 evaluation collision   — same setup or benchmark, similar usage.
5 terminology reframing  — existing idea relabeled.
6 weak domain transfer   — existing method ported, no new mechanism.
7 non-blocking related work — adjacent, with a clear delta.

Pick the strictest applicable category (lower number wins). Cite a quote from the paper's abstract.

Return JSON: {"category": <1-7>, "evidence_quote": "<verbatim>", "rationale": "<one sentence>"}."""


def call_llm(system: str, user: str) -> dict:
    cmd = os.environ.get('NOVELTY_LLM_CLASSIFY_FAST_CMD')
    if cmd:
        import subprocess
        full = f'<<SYSTEM>>\n{system}\n<<USER>>\n{user}'
        r = subprocess.run(cmd, input=full, shell=True, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[:200])
        return json.loads(r.stdout)
    raise RuntimeError('NOVELTY_LLM_CLASSIFY_FAST_CMD not set')


def classify(idea: dict, paper: dict) -> dict:
    user = json.dumps({
        'idea': {
            'title': idea.get('title', ''),
            'core_mechanism': idea.get('core_mechanism', ''),
            'novelty_claim': idea.get('novelty_claim', ''),
        },
        'paper': {
            'title': paper.get('title', ''),
            'abstract': (paper.get('abstract') or '')[:1500],
            'year': paper.get('year'),
            'venue': paper.get('venue', ''),
            'paper_url': paper.get('paper_url', ''),
        },
    }, ensure_ascii=False)
    res = call_llm(SYSTEM, user)
    res['paper_id'] = paper.get('paper_id') or paper.get('source_id')
    res['paper_title'] = paper.get('title', '')
    res['category_name'] = CATEGORIES.get(int(res.get('category', 7)), 'unknown')
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--idea', required=True, help='JSON file with the candidate idea')
    ap.add_argument('--hits', required=True, help='JSON file with the 6-month retrieval hits')
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--novelty-target', choices=['oral', 'publication', 'best_paper'], default='oral')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    idea = json.loads(Path(args.idea).read_text())
    hits = json.loads(Path(args.hits).read_text())
    if isinstance(hits, dict): hits = hits.get('papers', [])

    # Top N by simple BM25-ish overlap on signature words; in production, swap for
    # an EMBEDDING-based pre-filter via the configured embedding backend.
    sig_words = set((idea.get('core_mechanism', '') + ' ' + idea.get('novelty_claim', '')).lower().split())
    def overlap(p):
        text = (p.get('title', '') + ' ' + (p.get('abstract') or '')).lower()
        return sum(1 for w in sig_words if len(w) > 3 and w in text)
    ranked = sorted(hits, key=lambda p: -overlap(p))[:args.top]

    classifications = []
    for p in ranked:
        try:
            classifications.append(classify(idea, p))
        except Exception as e:
            print(f'  classify {p.get("title","")[:40]!r} failed: {e}', file=sys.stderr)

    blocking = [c for c in classifications if int(c.get('category', 7)) <= 6]
    worst = min((int(c.get('category', 7)) for c in blocking), default=7)
    action = ACTION_TABLE.get((worst, args.novelty_target), 'pass')

    out = {
        'candidate_idea_id': idea.get('id', idea.get('title', '')),
        'novelty_target': args.novelty_target,
        'hits': classifications,
        'blocking_count': len(blocking),
        'worst_category': worst,
        'recommended_action': action,
        'action_rationale': f'worst collision is category {worst} ({CATEGORIES.get(worst,"")}); under novelty_target={args.novelty_target} → {action}',
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f'wrote {args.out}; worst={worst}; action={action}')


if __name__ == '__main__':
    main()
