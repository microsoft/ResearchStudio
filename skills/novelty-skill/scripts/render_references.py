"""Render the JSON cards (built once from the data pipeline) into per-file markdown
references that the skill loads on-demand.

Why: progressive disclosure — SKILL.md is short; details live in references/*.md and
are read only when the relevant phase needs them. We render once at install time.

Run from the skill root:
  python scripts/render_references.py
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent       # skills/novelty-skill/
DATA_ROOT = ROOT.parent.parent / 'data' / 'clustering'
OUT_M = ROOT / 'references' / 'innovation-patterns'
OUT_T = ROOT / 'references' / 'innovation-sub-patterns'
OUT_M.mkdir(parents=True, exist_ok=True)
OUT_T.mkdir(parents=True, exist_ok=True)


# --- methodology cards -------------------------------------------------------

def render_methodologies():
    data = json.load((DATA_ROOT / 'cards' / 'methodology_cards.json').open())
    tax = data['taxonomy']
    cards = data['cards']

    overview = ['# Methodologies — overview', '',
                'The 13 induced methodologies. Each row shows the official name, a plain-language alias to surface in user-facing output, and the empirical sample sizes. Each methodology has a full 7-panel card in this directory.',
                '', '| ID | Name | Plain alias | Confidence | n_Oral | n_HC | n_Reject |',
                '| --- | --- | --- | --- | --- | --- | --- |']
    for t in tax:
        mid = t['id']; c = cards[mid]
        s = c['meta']['sample_sizes']
        alias = t.get('plain_alias', '')
        overview.append(f'| `{mid}` | {c["methodology_name"]} | _{alias}_ | {c["card"]["confidence"]} | {s["oral"]} | {s["hc"]} | {s["reject"]} |')
    overview += ['', '## Use', '',
                 'In Phase 4 (audit), load the relevant methodology cards based on the candidate\'s composition.',
                 'In Phase 3 (ideate), the system prompt embeds short summaries; full cards are loaded only when audit needs them.']
    (OUT_M / 'overview.md').write_text('\n'.join(overview))

    for t in tax:
        mid = t['id']; c = cards[mid]; card = c['card']; meta = c['meta']
        s = meta['sample_sizes']; cov = meta['meta_coverage']
        alias = t.get('plain_alias', '')
        out = [f'# {c["methodology_name"]}',
               f'_id: `{mid}` · confidence: **{card["confidence"]}** · '
               f'O{s["oral"]}/H{s["hc"]}/R{s["reject"]} · meta cov O{cov["oral"]}, H{cov["hc"]}, R{cov["reject"]}_',
               '', f'**Plain alias**. _{alias}_', '',
               f'**Definition**. {t["definition"]}', '',
               f'**Operational signature**. {t.get("operational_signature","")}', '',
               f'**When to apply**. {t.get("when_to_apply","")}', '',
               f'**Sample note**. {card["sample_note"]}', '']
        if card.get('step_by_step'):
            out += ['## Step-by-Step']
            for i, step in enumerate(card['step_by_step'], 1):
                out.append(f'{i}. {step}')
            out += ['']
        out += ['## Success conditions (from Oral)']
        for x in card['success_conditions']:
            out.append(f'- **{x["condition"]}**')
            out.append(f'  - evidence: {", ".join("`"+p+"`" for p in x["evidence_papers"])}')
            out.append(f'  - {x["rationale"]}')
        out += ['', '## Failure modes (from Reject)']
        for x in card['failure_modes']:
            out.append(f'- **{x["mode"]}**')
            out.append(f'  - evidence: {", ".join("`"+p+"`" for p in x["evidence_papers"])}')
            out.append(f'  - {x["rationale"]}')
        out += ['', '## Oral vs Reject gap', f'> {card["oral_reject_gap"]}']
        out += ['', '## Oral vs HC gap', f'> {card["oral_hc_gap"]}']
        out += ['', '## Reviewer expectations']
        for e in card['reviewer_expectations']:
            out.append(f'- _[{e["evidence_source"]}]_ {e["expectation"]}')
        out += ['', '## Cognitive barriers']
        for b in card['cognitive_barriers']:
            out.append(f'- {b}')
        out += ['', '## Representative examples']
        for ex in card['representative_examples']['oral']:
            out.append(f'- **[Oral]** `{ex["paper_id"]}` — {ex["one_sentence_why"]}')
            if ex.get('lesson'):
                out.append(f'  - _Lesson_: {ex["lesson"]}')
        for ex in card['representative_examples']['reject']:
            out.append(f'- **[Reject]** `{ex["paper_id"]}` — {ex["one_sentence_why"]}')
            if ex.get('lesson'):
                out.append(f'  - _Lesson_: {ex["lesson"]}')
        (OUT_M / f'{mid}.md').write_text('\n'.join(out))
    print(f'wrote {len(tax)} methodology cards in {OUT_M}')


# --- tactical cluster cards --------------------------------------------------

def render_tactical():
    data = json.load((DATA_ROOT / 'tactical_cards' / 'tactical_cards.json').open())
    cards_by = data['cards_by_cluster_id']

    overview = ['# Tactical clusters — overview', '',
                f'47 fine-grained clusters under 13 parent methodologies. Use in Phase 2 routing for "which specific tactic to use" disambiguation.',
                '', '| Cluster | Label | Parent methodology | Confidence |',
                '| --- | --- | --- | --- |']
    for cid in sorted(cards_by.keys(), key=int):
        c = cards_by[cid]
        overview.append(f'| C{int(cid):02d} | {c["cluster_label"]} | `{c["parent_methodology_id"]}` | {c["card"]["confidence"]} |')
    (OUT_T / 'overview.md').write_text('\n'.join(overview))

    for cid_s, c in cards_by.items():
        cid = int(cid_s); card = c['card']; meta = c['meta']; s = meta['sample_sizes']
        out = [f'# C{cid:02d}: {c["cluster_label"]}',
               f'_parent: **{c["parent_methodology_name"]}** (`{c["parent_methodology_id"]}`) · '
               f'O{s["oral"]}/H{s["hc"]}/R{s["reject"]} · confidence: **{card["confidence"]}**_',
               '', f'**Description**. {c["cluster_description"]}', '',
               f'## Tactical pattern\n\n{card["tactical_pattern"]}', '',
               f'## Differentiation within parent\n\n{card["differentiation_within_parent"]}', '',
               f'## When to pick this one\n\n{card["when_to_pick_this_one"]}', '',
               f'## Tactical failure mode\n\n{card["tactical_failure_mode"]}', '',
               '## Examples']
        for ex in card['representative_oral']:
            out.append(f'- **[Oral]** `{ex["paper_id"]}` — {ex["one_sentence_why"]}')
            if ex.get('lesson'):
                out.append(f'  - _Lesson_: {ex["lesson"]}')
        for ex in card['representative_reject']:
            out.append(f'- **[Reject]** `{ex["paper_id"]}` — {ex["one_sentence_why"]}')
            if ex.get('lesson'):
                out.append(f'  - _Lesson_: {ex["lesson"]}')
        (OUT_T / f'C{cid:02d}.md').write_text('\n'.join(out))
    print(f'wrote {len(cards_by)} tactical cards in {OUT_T}')


if __name__ == '__main__':
    render_methodologies()
    render_tactical()
