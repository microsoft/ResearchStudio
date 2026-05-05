# NoveltySkill

A data-driven research-idea generator for ML, built on a 1947-paper corpus of ICLR / ICML / NeurIPS submissions (2020-2025). Two deliverables:

- **The dataset + analyses** — 13 induced **innovation patterns**, 47 **innovation sub-patterns**, 28 induced research domains, paper-level multi-label pattern assignments, plus seven figure-grade analyses (acceptance bias, pattern adjacency, per-domain temporal trends, multi-label *k* distributions, top compositions, etc.). Documented in [`paper/technical_report.pdf`](paper/technical_report.pdf) (~130 pages).
- **The skill** — a model-agnostic Claude / GPT / Gemini skill that converts an under-specified research direction into one reviewer-defensible Oral-grade research proposal in **5 phases**. Lives in [`skills/novelty-skill/`](skills/novelty-skill/) with literature grounding via [`skills/novelty-lit-search/`](skills/novelty-lit-search/).

Key naming: in the paper and this README we say **innovation pattern** (13) and **innovation sub-pattern** (47); the codebase still uses field names like `pattern_id` / `sub_pattern_id` and file paths like `references/innovation-patterns/` / `references/innovation-sub-patterns/`.

## Quick navigation

| Path | Contents |
|---|---|
| `skills/novelty-skill/` | Parent skill: 5-phase ideation workflow with corpus-anchored audit. |
| `skills/novelty-lit-search/` | Sub-skill: 4-source literature retrieval (DBLP / OpenAlex / OpenReview / arXiv). |
| `paper/technical_report.pdf` | The empirical analysis behind the cards (~130 pages). |
| `data/dataset/all_records_full.json` | The cleaned dataset: 1947 papers with abstract, reviews, meta-reviews, pattern assignments. |
| `data/clustering/` | Analysis scripts and JSON outputs (cards, sub_pattern cards, domains, multilabel). |
| `docs/USAGE.md` | End-to-end usage for Claude Code / Claude Desktop / OpenAI / Gemini / open-weights. |

## What the skill does (one paragraph)

Given a research direction (e.g., *"distill an EDM diffusion teacher to 4 NFE via consistency loss"*), the skill (a) retrieves real recent literature via 4 connectors, (b) writes a literature-grounded bottleneck statement, (c) selects 1-3 of 13 innovation patterns by structural fit and generates one candidate idea, (d) runs a corpus-anchored audit (3 checks against tactical-card Reject lessons, anti-pattern compositions, and lit_table ∪ collision_hits paper-pointed threats), (e) optionally applies revisions when audit verdict is `revise`, (f) expands into a structured idea card and renders it as PDF + Markdown.

Three possible outcomes per run: an L3 idea card (advance / revise→3.3 paths), a `do_not_generate.md` (Phase 1 OOD), or a `phase_3_failed.md` (audit abandons). One user input → one outcome. The skill never asks the user mid-flow.

## Quick start (Claude Code)

```bash
# 1. Install both skills
ln -s "$(pwd)/skills/novelty-skill"      ~/.claude/skills/novelty-skill
ln -s "$(pwd)/skills/novelty-lit-search" ~/.claude/skills/novelty-lit-search

# 2. Set environment for the lit-search sub-skill
export OPENALEX_MAILTO=<your-email>     # optional but recommended (polite-pool: 10 req/s vs 1)
export OPENALEX_API_KEY=<your-key>      # optional, premium rate (https://openalex.org/about)
export OPENREVIEW_USER=<your-user>      # required for OpenReview connector
export OPENREVIEW_PASS=<your-pass>

# 3. Install Python deps for the connectors
pip install feedparser openreview-py
```

For dev workflow, copy `.env.template` to `.env`, fill in your values, and source it (`.env` is in `.gitignore`):

```bash
cp .env.template .env
$EDITOR .env                  # fill in your values
set -a; source .env; set +a   # load into current shell
```

**Never commit `.env`**, embed keys in `config.yaml` / `SKILL.md` / any tracked file, or share keys in issues. `.env.template` is the canonical list of env vars the skill reads.

In Claude Code, ask in natural language:

```
I'm working on speeding up diffusion sampling by distilling
an EDM teacher (50 NFE) to a 4-NFE consistency-loss student.
I have 4×A100×3 weeks. Generate one Oral-grade idea.
```

The skill drives the 5 phases and writes outputs under `outputs/`. End-to-end takes ~5-15 minutes with frontier reasoning model.

## What you get back

For a successful run:

| File | Type | Use |
|---|---|---|
| `idea_<timestamp>.pdf` | PDF | Reading / sharing |
| `idea_<timestamp>.md`  | Markdown | AI context / docs / GitHub |
| `idea_<timestamp>.tex` | LaTeX | Diagnostics / further editing |
| `phase4_expansion.json` | JSON | Machine-readable, all data |
| `phase{0,1,2,3,4}_*.json` | JSON | Per-phase intermediate outputs |

The idea card contains: title + hook, 250-word abstract, motivation (with ≥ 2 cited prior papers explaining why they stopped), core claim + sub-claims, method flow (numbered steps each linked to a leg + falsification mode), theorem/algorithm/system-design statement, theoretical + engineering legs, falsification block (what we run / success / failure_a numerical / failure_b mechanistic / compute budget / decision rule), mechanism probe, 5-axis feasibility validation (compute / data / theoretical / engineering / falsification + overall), differentiation from ≥ 2 specific recent papers, reviewer concerns + responses anchored in candidate fields, and an **innovation pattern landscape** showing the area's pattern saturation alongside which patterns this candidate uses.

## How phases run

| Phase | Type | Purpose |
|---|---|---|
| 0. Literature retrieval | orchestrator (no LLM call) | 4-connector role-based retrieval, ~30-40 deduped papers + tagging |
| 1. Bottleneck identification | 1 LLM call | Multi-paper-grounded bottleneck statement + closest_adjacent + state {proceed, do_not_generate} + domain pattern distribution |
| 2.1 Pattern selection | 1 LLM call | Top-3 ranked compositions by structural fit; anti-pattern flag |
| 2.2 Candidate generation | 1 LLM call | Single candidate (K=1) with full schema + signature_terms |
| 3.1 Collision retrieval | orchestrator (no LLM call) | Mechanism-specific real retrieval over 6mo, dedup |
| 3.2 Audit | 1 LLM call | 3 corpus-anchored checks + 2-layer verdict {advance, revise, abandon} |
| 3.3 Revise (if verdict=revise) | 1 LLM call | Apply revision targets, kill-switch byte-identical preserved |
| 4.1 Expansion | 1 LLM call | Idea-card content (motivation, method_flow, feasibility, etc.) |
| 4.2 PDF/MD render | orchestrator (no LLM call) | Templating only, deterministic |
| Validators | orchestrator (no LLM call) | `kill_switch_integrity` (hard) + `expansion_completeness` (soft) |

LLM calls per run: **5** (advance path) or **6** (revise path).

## Reproducing the analysis

```bash
# 1. Build the dataset (assumes you have OpenReview credentials)
python data_pipeline/fetch_openreview.py --all
# 2. Run the extraction + clustering pipeline
python data/clustering/embed.py
python data/clustering/cluster.py
python data/clustering/label.py
python data/clustering/taxonomy.py
# 3. Build the pattern + sub-pattern + domain + multilabel cards
python data/clustering/cards/step1_build_input.py
python data/clustering/cards/step2_run_cli.py
python data/clustering/cards/step3_merge.py
# (similar for sub_pattern_cards/, domains/, multilabel/)
# 4. Render figures + tech report
python paper/make_figures.py
python paper/render_cards.py
python paper/render_tactical.py        # renders sub-pattern excerpts
python paper/render_methodologies_app.py
cd paper && tectonic technical_report.tex
# 5. Refresh the skill's reference cards from the corpus data
python skills/novelty-skill/scripts/render_references.py
```

## Citation

If you use NoveltySkill in your research, please cite the technical report.

```bibtex
@misc{noveltyskill2026,
  title={NoveltySkill: Innovation Patterns and Idea Generation in Top-Tier ML Research},
  author={...},
  year={2026},
  url={https://github.com/...}
}
```

## License

Code: MIT.
Data: each paper's metadata is owned by its publisher; we redistribute only what is permissible under OpenReview / arXiv terms of use.

## Status

- Dataset: 1947 papers, ICLR / ICML / NeurIPS, 2020-2025.
- Skill: end-to-end runs validated on diffusion-sampling and RLHF-overoptimization queries; both produce L3 idea cards passing both validators (`kill_switch_integrity` + `expansion_completeness`).
- See `paper/technical_report.pdf` §12 for design rationale of every choice.
