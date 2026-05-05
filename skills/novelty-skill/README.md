# novelty-skill

Generate ONE reviewer-defensible Oral-level ML research idea (top ~5% submission tier) from a user's research direction. **5 phases** from problem-bottleneck diagnosis to a structured idea card (PDF + Markdown + JSON). One-shot guarantee: one user input produces one of three outputs — an idea card, a `do_not_generate.md`, or a `phase_3_failed.md`.

The skill is grounded in the 1947-paper corpus (`paper/technical_report.pdf`) with **13 induced innovation patterns** and **47 sub-patterns** as its substrate.

## Install

### Claude Code

```bash
ln -s "$REPO/skills/novelty-skill"      ~/.claude/skills/novelty-skill
ln -s "$REPO/skills/novelty-lit-search" ~/.claude/skills/novelty-lit-search
```

Restart Claude Code; `novelty-skill` and `novelty-lit-search` appear under `/skills`.

### Claude Desktop / claude.ai

Zip and upload via Settings → Skills:

```bash
(cd skills && zip -r novelty-skill.zip novelty-skill && zip -r novelty-lit-search.zip novelty-lit-search)
```

### Other LLMs (OpenAI, Gemini, open-weights)

Model-agnostic. Most LLM-driven phases run as host-LLM prompt invocations (manual). Orchestrator-driven phases (Phase 0 retrieval, Phase 3.1 collision, Phase 4.2 PDF render, validators) are Python scripts. See [`docs/USAGE.md`](../../docs/USAGE.md) for full per-backend instructions.

## Configure

External secrets (read from environment by the lit-search sub-skill connectors):

```bash
export OPENALEX_MAILTO=<your-email>     # optional but recommended (OpenAlex polite-pool: 10 req/s vs 1 anonymous)
export OPENALEX_API_KEY=<your-key>      # optional, premium tier
export OPENREVIEW_USER=<your-user>      # required for OpenReview connector
export OPENREVIEW_PASS=<your-pass>
```

For dev workflow, copy the project's `.env.template` and fill it in (`.env` is gitignored):

```bash
cp ../../.env.template ../../.env  # at project root
$EDITOR ../../.env                 # fill in real values
set -a; source ../../.env; set +a
```

Never commit `.env` or embed keys in `config.yaml` / `SKILL.md` / any tracked file. `.env.template` is the canonical list of env vars the skill reads.

Python deps:

```bash
pip install feedparser openreview-py     # connectors
pip install jinja2                       # templating (optional; render_pdf.py works without it)
# tectonic for PDF compilation: install via your package manager
```

[`config.yaml`](config.yaml) controls per-phase capability profiles; defaults inherit `host_llm` everywhere — no overrides needed unless you want per-phase routing to different backends.

## Run

In Claude Code, ask in natural language:

```
> I want to speed up diffusion model sampling by distilling
  an EDM teacher (50 NFE) into a student via consistency loss
  targeting 4 NFE. I have 4×A100 for 3 weeks. Generate
  an Oral-grade idea.
```

Or invoke explicitly: `> /skills novelty-skill <your direction>`. The skill follows [SKILL.md](SKILL.md) with prompts in [references/system-prompts/](references/system-prompts/). Outputs land under `outputs/<runname>/` (skill-local convention).

## The 5 phases

```
Phase 0  retrieval         (orchestrator, ~30-40 papers across 4 sources)
Phase 1  bottleneck        (1 LLM call → state ∈ {proceed, do_not_generate})
Phase 2.1 pattern selection (1 LLM call → ranked top-3 compositions)
Phase 2.2 candidate gen     (1 LLM call → single candidate + signature_terms)
Phase 3.1 collision         (orchestrator, ~30-50 paper retrieval w/ signature_terms)
Phase 3.2 audit             (1 LLM call → verdict ∈ {advance, revise, abandon})
Phase 3.3 revise            (1 LLM call, only when verdict=revise)
Phase 4.1 expansion         (1 LLM call → full idea-card content)
Phase 4.2 render            (orchestrator, PDF + Markdown + LaTeX)
validators                  (orchestrator, kill_switch_integrity + expansion_completeness)
```

LLM calls per run: **5** (advance) or **6** (revise). Orchestrator-driven steps add ~30-60s for retrieval + a few seconds for templating.

## Output

| File | Type | Content |
|---|---|---|
| `idea_<ts>.pdf` | PDF | Human-readable idea card |
| `idea_<ts>.md`  | Markdown | Same content, agent / docs friendly |
| `idea_<ts>.tex` | LaTeX | Diagnostics / further editing |
| `phase4_expansion.json` | JSON | Full structured content (machine-readable) |
| `phase{0,1,2,3}_*.json` + `lit_table.md` | JSON / MD | Per-phase intermediate outputs |

The idea card contains:

1. **Title + hook** (one-sentence "wait, really?" framing)
2. **Abstract draft** (150-250 words: problem → bottleneck → contribution → falsification → expected outcome)
3. **Motivation** (problem framing + why now + ≥ 2 *why prior stopped* entries citing specific papers + what changes when the gap closes)
4. **Core claim + sub-claims**
5. **Method flow** (numbered steps each linked to leg + failure mode + preservation argument)
6. **Theorem / algorithm / system design statement**
7. **Theoretical + engineering legs**
8. **Falsification prediction** (what we run / success threshold / failure_a numerical / failure_b mechanistic / compute budget / decision rule)
9. **Mechanism probe** (the experiment that distinguishes failure_a from failure_b)
10. **Feasibility validation** (5 axes: compute / data / theoretical / engineering / falsification + overall verdict — all user-relative, no absolute compute cap)
11. **Differentiation from ≥ 2 closest_adjacent papers** (substantive deltas, not "we use a different methodology")
12. **Reviewer concerns + responses** (derived from Phase 3.2 audit findings, anchored in candidate fields)
13. **Innovation pattern landscape** (this area's pattern distribution + which patterns this candidate uses; informational)

Three forbidden sections by design: experiment matrix / ablation plan / baseline table (user's experimental engineering); calendar projection ("week N", "first month"); degraded fallback PDFs (failure → `phase_3_failed.md`, not a tiered/half-baked artifact).

## Validators

Run after Phase 4 to verify contracts:

```bash
# advance path (no Phase 3.3 ran)
python -m scripts.run validate \
  --phase2 outputs/<run>/phase2_generate/phase2_generate_output.json \
  --phase3 outputs/<run>/phase3_critique/phase3_critique_output.json \
  --phase4 outputs/<run>/phase4/phase4_expansion.json

# revise path (Phase 3.3 produced final_candidate)
python -m scripts.run validate \
  --phase2 outputs/<run>/phase2_generate/phase2_generate_output.json \
  --phase3 outputs/<run>/phase3_revise/phase3_revise_output.json \
  --phase4 outputs/<run>/phase4/phase4_expansion.json
```

| Validator | Severity | Check |
|---|---|---|
| `kill_switch_integrity` | fail (hard) | `falsification_prediction.what_we_run`, `.compute_budget`, `mechanism_probe_proposal` byte-identical Phase 2 → 4 (advance) or Phase 2 → 3.3 → 4 (revise) |
| `expansion_completeness` | warn (soft) | Phase 4 has all required structural sections (motivation w/ ≥ 2 why_prior_stopped, method_flow.steps[] with linked_component+linked_falsification, feasibility 5 sub-verdicts + overall, abstract_draft, core_claim, sub_claims) |

## Skill anatomy

```
novelty-skill/
├── SKILL.md                              ← entry point, 5-phase workflow
├── README.md                             ← this file
├── config.yaml                           ← per-phase capability profile routing
├── references/
│   ├── innovation-patterns/              ← 13 7-panel pattern cards (success / failure modes / examples / etc.)
│   ├── innovation-sub-patterns/          ← 47 4-panel sub-pattern cards (tactical-pattern / failure mode / examples)
│   ├── domains/                          ← 28 induced domains + 28×13 distribution
│   ├── anti-patterns.md                  ← 3 reject-favored 2-way compositions w/ required mitigations
│   ├── intake-routing.md                 ← OOD triggers
│   ├── collision-categories.md           ← collision taxonomy reference
│   ├── system-prompts/                   ← 6 LLM-call prompts:
│   │   ├── bottleneck_identify.txt       ← Phase 1
│   │   ├── ideate_select.txt             ← Phase 2.1
│   │   ├── ideate_generate.txt           ← Phase 2.2
│   │   ├── critique.txt                  ← Phase 3.2 audit
│   │   ├── revise.txt                    ← Phase 3.3 revise
│   │   └── expand.txt                    ← Phase 4.1 expansion
│   └── templates/
│       └── idea_card.tex.j2              ← LaTeX template (only template; no degraded fallback)
└── scripts/
    ├── run.py                            ← orchestrator: phase0 / phase3_collision / phase4_render / validate
    ├── render_pdf.py                     ← Phase 4.2 templating + PDF/MD/TeX rendering
    ├── render_references.py              ← rebuild reference cards from corpus data (run when dataset updates)
    └── validators/
        ├── kill_switch_integrity.py      ← hard fail validator
        └── expansion_completeness.py     ← soft warn validator
```

## Three outcomes

```
Phase 1 state=do_not_generate  →  do_not_generate.md       (OOD: too broad / no anchor / engineering integration / etc.)
Phase 3.2 verdict=abandon      →  phase_3_failed.md        (corpus-anchored hard floor fired; concrete user-side fixes given)
Phase 4.2 renders successfully →  idea_<ts>.pdf + .md + .json + .tex  (advance path or revise→3.3 path)
```

One user input → one of these three. No mid-flow clarification questions.

## Best-practices compliance

This skill follows [Anthropic's agent-skill best practices](https://docs.claude.com/en/api/agent-skills):

- **SKILL.md under 500 lines**; references chunked by topic with progressive disclosure.
- **Composition-scoped corpus reads** — Phase 3.2 audit reads exactly 1 sub-pattern card (the candidate's `sub_pattern_id`) + 1 pattern card per secondary, not the full directories.
- **Schema-validated JSON at every phase boundary**; validators run as final mechanical checks.
- **Anti-substitution mechanically enforced** — `kill_switch_integrity` validator catches kill-switch drift between Phase 2 and Phase 4 byte-for-byte.
- **Real retrieval enforced** — Phase 0 + 3.1 use connectors via the orchestrator, not WebSearch fallback. `lit_grounding_mode` sentinel records the mode; Phase 1 entry assertion catches bypass.
- **Two-layer verdict (audit)** — corpus-anchored hard floor LLM cannot override, plus LLM soft judgment within the safe zone.
- **No auto-revise inside audit** — audit (3.2) and revise (3.3) are separate LLM calls; eliminates self-answering bias.

## See also

- [`SKILL.md`](SKILL.md) — full prompt-level workflow
- [`docs/USAGE.md`](../../docs/USAGE.md) — per-LLM deployment guide (Claude Code / Claude Desktop / OpenAI / Gemini / open-weights)
- [`paper/technical_report.pdf`](../../paper/technical_report.pdf) — corpus analysis + skill design rationale (~130 pages)
- [`../novelty-lit-search/`](../novelty-lit-search/) — sub-skill called at Phase 0 + 3.1
