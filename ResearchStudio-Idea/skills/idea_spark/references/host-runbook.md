# Host runbook — driving IdeaSpark from an agent harness

Nothing here is optional for a
host: the three context-discipline rules and the consume-every-emit-whole rule each record
a live failure (backend timeouts from carried context; an audit that advanced on a grep-
filtered emit). Every stage after Phase 1 is a prepare → model call → record triple;
the rules below apply to each model call in that triple exactly as they applied to a phase.

## When to use

- "Give me a research idea in {area} I could pursue." / "What's the most impactful next step in this direction?"
- "Help me sharpen this vague direction into an Oral-level proposal."
- "What's the bottleneck of this problem?" / "Run a novelty audit on this idea."

## When NOT to use

- Code review, debugging, refactoring. Summarizing one paper. Cross-decade survey writing.
- Free-association brainstorming with no research context. Engineering integration tasks ("ship this feature in our system").
- Pure benchmark / dataset construction work — the 15-pattern vocabulary handles benchmark *audit* (controlled_diagnostic_design) but not benchmark *construction*.


## How to run: the `next` loop

The canonical way to drive a run is the **run-state navigator**:

```bash
python3 "$SKILL_DIR/scripts/run.py" next --dir "$RUN_DIR" --query "<user's research question>"
```

**Run-dir convention (one run = one directory, named by the host BEFORE the first command):** `$PWD/ideaspark_run/<topic-slug>` — a short kebab-case slug distilled from the user's direction (e.g. `ideaspark_run/diffusion-watermark`); if the slug is taken, append `_2`, not a timestamp. NEVER reuse a directory that already contains a `phase0/` — every phase writes into `$RUN_DIR` and would clobber the prior run. The skill itself never names the dir (any absolute path works); this convention exists so runs from different harnesses land in one predictable place instead of each agent improvising.

`next` inspects the artifacts already on disk and prints EXACTLY one next step — either a Bash command to run verbatim, or an LLM sub-agent spec (system-prompt path + input file paths + output path + the routing signal to report back). It is read-only and idempotent (safe to re-run anytime, including to resume an interrupted run) — including on a run dir that does not exist yet, which it reports as a fresh run and answers with the Phase 0 step rather than an error. You never need to create the directory before calling it. The host loop is:

1. Run `next`.
2. Do what it says (`bash` → run the command; `llm_subagent` → execute in an ISOLATED context per the Context discipline rules below).
3. Run `next` again. Repeat until it reports a terminal state (`DONE`, `do_not_generate`, or `phase_3_failed`).

**Consume every emit WHOLE — never grep/filter/truncate the block.** INPUT lists span unlabeled continuation lines; a label-keyed grep (`grep -E "STEP|INPUT|..."`) silently drops them. This exact failure occurred in a live run: the navigator listed the coherence gate's blocking findings as an audit input, the host's grep dropped the line, and the audit issued a false `advance` without ever seeing the executed evidence. If the emit must be captured into a bounded tool result, `head -c 4000` the WHOLE block — never filter by line labels.

`next` encodes the full phase graph — the mandatory full-text gate, the citation gate, the abandon-retry branch, the bounded revision and repair loops, and the Phase 4 path for the run's depth — so you do not need to memorize the reference table below; it exists for debugging.

If your host exposes a task/todo tool (e.g., TodoWrite), seed it with this checklist and tick phases as `next` moves past them:

```
- [ ] Phase 0: Literature grounding → lit_table.md, then Phase 0+ full-text fetch (MANDATORY — Phase 1 hard-gates on it)
- [ ] Phase 1: Bottleneck identification → phase1_output.json (routing: proceed | do_not_generate)
- [ ] Phase 2: Gap×pattern selection + candidate generation (ONE isolated context, TWO output files) → citation gate → coherence gate (dry-run trace, fresh context)
- [ ] Phase 3: Collision retrieval (signature@10mo + alias@48mo — launchable in parallel with 2.3) → audit (5 checks) → [revise → merge → re-audit if falsification rewritten] | [abandon → information-gain retry: regenerate while each failure yields NEW binding lessons, ≤3 candidate cycles; repeated subsumption lesson → 1 bottleneck re-diagnosis + 1 attempt; no new information or cap → phase_3_failed]
- [ ] Phase 4: skeleton → fill (technical) → assemble partial → derive (plain, fast-tier) → assemble final + method view → implementability audit → validate → render → return 3 cards inline
```

Three outcomes per run: the rendered idea cards (intermediates left under `$RUN_DIR`), cards marked FAILED VALIDATION when the run's validation ended in failure, or a `do_not_generate.md` (Phase 1 OOD). **Never ask the user mid-flow** — missing intake fields are inferred; revision, repair and the bounded candidate retries all run without user re-invocation.

### Invocation contract

**No `cd` is required.** `scripts/run.py` self-locates its skill root, so every orchestrator command can be invoked from ANY working directory by absolute script path: `python3 "$SKILL_DIR/scripts/run.py" <subcommand> --out "$RUN_DIR/<phase>/" ...`. The module form `cd "$SKILL_DIR" && python3 -m scripts.run <subcommand> ...` works identically. Do NOT use relative script or `--out` paths — CWD is not stable across host-LLM Bash invocations, and the orchestrator rejects a relative `--out` outright.

**Exit codes 10 and 11 are NOT errors — they are sentinel handshakes.** When the orchestrator can't call an LLM itself (no `NOVELTY_LLM_CLASSIFY_FAST_CMD`), it writes a sentinel JSON describing what the host LLM should do, then exits rc=10 (intent / pattern-summary) or rc=11 (signature_terms). Read the sentinel (`$RUN_DIR/<phase>/.<step>_pending`), read the file at its `rubric_file` field (absolute path), produce the expected output, re-invoke per its `re_invocation` field. Do not stop on these codes. (The default Phase 0 flow below avoids the rc=10 intent sentinel entirely by passing `--queries` up front.)

### Context discipline (read BEFORE running any LLM-driven phase)

A full run accumulates ~180-250k tokens of intermediate state. If the host LLM carries that in its own conversation context across phases, the Phase 1 / 2.2 / 4.fill calls routinely hit the backend request timeout (`[API Error · Request timed out · Retrying...]`) and the retry times out again. Apply ALL three rules on every run:

**Rule 1 — Run every LLM-driven phase in an ISOLATED context.** Phases 1 / 2 (2.1+2.2) / 2.3 / 3.2 / 3.3 / 4.fill / 4.1.5 each have file-path inputs and one JSON output; no phase needs the conversation that produced an earlier one. Use the FIRST isolation mechanism your harness supports:

- **(a) Subprocess LLM** — set `NOVELTY_LLM_REASONING_LARGE_CMD` / `NOVELTY_LLM_CLASSIFY_FAST_CMD` (see § Configuration); each phase runs as its own subprocess, fresh context by construction, on any harness.
- **(b) Sub-agent tool** (Claude Code `Agent` or equivalent) — spawn one per phase, passing ONLY the file paths the phase prompt lists — not conversation history, not file contents inline. The sub-agent reads from disk, `Write`s to disk, returns ≤ 250 words (output path + routing signal). Exception by design: Phase 2.1 and 2.2 run in ONE sub-agent writing both output files — both are generation-side; the adversarial separations (3.2 vs 3.3, 4.fill vs 4.1.5) must stay separate calls.
- **(c) Manual context reset** — run inline but clear/compact at the four points in Rule 3.

Whichever mechanism, the parent context stays ≤ ~30k tokens for the whole run because it never holds a phase's structured output.

**Rule 2 — `Write` every phase artifact directly to disk; never paraphrase it into chat.** Output convention: `$RUN_DIR/<phase>/<phase>_output.json`. Use your harness's file-write tool (Claude Code: `Write`) — no Bash heredocs (permission prompts + silent truncation), no `echo`, no pasting JSON into replies. Bound tool-result captures from large files to ≤ 4 KB (`head -c 4000` / `jq` / `sed`); never `Read` a >10 KB intermediate dump into the parent context — the dump gets cached into every subsequent turn (this exact anti-pattern caused prior timeout runs).

**Rule 3 — Compact between phases.** Natural compact points: after Phase 0+, after Phase 1, after Phase 2, after Phase 3.2. Every phase re-reads its disk inputs, so compacting loses nothing. With `/compact`, use it there; Rule 1 mechanisms (a)/(b) achieve the same on their own.

**Diagnostic for "Request timed out" mid-phase:** inspect your harness's session transcript/log (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`, look for `isApiErrorMessage: true`; other harnesses: their session-log equivalent); the prior tool call shows which prompt got too big. The fix is one of the three rules — usually Rule 1.

---


## Phase reference

`next` prints each of these steps at the right moment with concrete paths; the tables below are the full contract for deviation/debugging.

### Orchestrator entry points

| Phase | Entry point (`python3 "$SKILL_DIR/scripts/run.py" ...`, any CWD) |
|---|---|
| navigator | `next --dir "$RUN_DIR" [--query "..."]` |
| Phase 0 | `phase0 --query "<user text>" --queries "q1\|q2\|q3\|q4" [--named-papers "Title A\|Title B"] --out $RUN_DIR/phase0/` |
| user-ref registration (title-named anchor papers; BEFORE phase0_fulltext) | `add_user_ref --out $RUN_DIR/phase0/ --title "<full title>" [--raw-match "<user phrasing>"] [--id <arxiv/DOI/URL>]` |
| relevance partition apply (Phase 0.4; archives off_topic + stamps core/adjacent, BEFORE tagging) | `apply_partition --out $RUN_DIR/phase0/ --partition <relevance_partition.json>` |
| host-ref resolution (Phase 0.5 coverage check; verifies + merges host-nominated missing papers) | `add_host_refs --out $RUN_DIR/phase0/ --refs <noms.json>` |
| Phase 0+ full-text (**mandatory**, the moment lit_table.md lands) | `phase0_fulltext --out $RUN_DIR/phase0/` |
| Phase 1 anchor top-up (optional, when the #1 closest_adjacent fell outside the fulltext pool **or came back method-thin**) | `phase1_fulltext_topup --out $RUN_DIR/phase0/ --paper-id <anchor paper_id> [--min-method-chars 4000]` |
| Phase 2 prep (deterministic; `next` emits it with the Phase 2 step) | `phase2_prepare --dir $RUN_DIR` |
| lit_table shard assembly (deterministic; after parallel pattern tagging) | `lit_table_merge --out $RUN_DIR/phase0/ --shards <rows1.md> <rows2.md> ...` |
| Phase 3.1 collision | `phase3_collision --idea-json <canonical candidate> --out $RUN_DIR/phase3_collision/` |

The LLM-driven steps have no orchestrator subcommand (a `cat prompt | llm` wrapper would add fragility without determinism): read the prompt at `references/system-prompts/<phase>.txt`, gather the inputs listed at its top, `Write` the JSON described under `Output:` to `$RUN_DIR/<phase>/<phase>_output.json`. Run each under the Context discipline rules — Phase 4.fill is the largest output and the most timeout-prone; never in the parent context.


(The entry points above are the deterministic commands; the navigator wraps the
LLM-driven ones in `quality_prepare` / `quality_record` and adds `quality_materialize`,
`quality_collision`, `quality_retry`, `quality_needs_work`, `quality_publish` — see
[quality-flow.md](quality-flow.md). The Phase 0/1 sub-flow is in [retrieval-runbook.md](retrieval-runbook.md).)

## Validators

```bash
# advance path: --phase3 = phase3_critique_output.json; revise path: --phase3 = phase3_revise_output.json
# --phase2 = the CANONICAL candidate (refined_candidate.json when 2.3 patched, else the 2.2 output)
python3 "$SKILL_DIR/scripts/run.py" validate \
  --phase1 $RUN_DIR/phase1/phase1_output.json \
  --phase2-select $RUN_DIR/phase2_select/phase2_select_output.json \
  --phase2 <canonical candidate file> \
  --phase3 <see comment> \
  --phase4 $RUN_DIR/phase4/phase4_expansion.json \
  --phase4-impl $RUN_DIR/phase4/phase4_implementability.json   # optional; enables implementability checks
```

| Validator | Check | Severity |
|---|---|---|
| **subpattern_citation_consistency** | each `gap_closure[].sub_pattern` resolves to a real C## cluster in overview.md whose true parent == the cited `main_pattern` and whose parenthetical == that cluster's parent display name. Primary use: the Phase 2.2 citation gate; re-runs harmlessly here. | fail (hard) |
| **alias_collateral_coverage** | `alias_terms[]` actually queries the cross-community families Phase 1 pinned as `is_collateral` nodes in `method_lineage`. Needs BOTH phase1 and phase2 paths. Runs in the Phase 2.2 citation gate — i.e. BEFORE 3.1 collision, which consumes `alias_terms[]` verbatim, so a miss caught later is a wasted retrieval budget. Zero coverage = fail; partial = warn naming the unqueried families (a family can be genuinely unreachable, and a forced fabricated term would evict real ones from a channel that truncates by lexical relevance — `composition_note` carries the skip defense, the 3.2 audit weighs it). | fail (zero) / warn (partial) |
| **kill_switch_integrity** | `falsification_prediction` + `compute_budget` byte-identical along Phase 2.2 → [3.3 final_candidate →] 4. After an audited falsification rewrite (`falsification_rewritten` marker + matching applied `rewrite_falsification` entry — disagreement fails), the anchor for `falsification_prediction` re-bases at the 3.3 final_candidate (3.3 → 4 must match); `compute_budget` stays full-chain always. | fail (hard) |
| **expansion_completeness** | motivation (≥2 `why_prior_stopped`), `method_flow.steps[]` (each with `linked_component` + `linked_falsification`), `feasibility_validation` (5 sub-verdicts + `overall`), non-empty `abstract_draft` + `core_claim` + `sub_claims[]` — missing sections would render as silent blanks. | fail (hard) |
| **implementability_completeness** | `enriched_steps[]` one-per-step (same ids/order, EN+ZH), `underspecified_points[]` present (`[]` allowed), NO kill-switch field in the file. | fail (hard) |
| **user_direction** | when `intake.user_direction` is set, `phase2_select` must carry a `user_direction_disposition` (adopted/departed, `why_departed` required on departed), and both quoted spans must appear in `phase0/user_query.txt`. Hard rule 10 keeps a user-named solution OUT of gap selection on purpose; this only forbids dropping it silently. | fail (hard) |
| **chinese_word_order** | no `_zh` field puts more than 18 characters in front of 的 without a break (an English relative clause left in pre-nominal position — the reader cannot tell what is being described until the end), and no known calque (`保留任务` for held-out, `两个位` for the two bits). | warn |
| **motivation_opener** | the first sentence of `plain_motivation_en` states a claim (what is wrong, missing or assumed), not a definition — `X means`, `X is a system that`, a parenthetical gloss, or `X speeds up Y by` in sentence one is flagged; glosses belong in sentence two. | warn |
| **implementability_readability** | std-register fields: no `占位`/`placeholder` leak, no bare English jargon dropped into Chinese prose. | warn |

**Retry budget on `fail` (cap = 2).** Fix only the named contract, re-validate; still failing after the 2nd retry → stop revising, render as-is, and append a short note listing the failing validators (a flagged-imperfect card beats a watchdog-killed run with zero output). Never "fix" `kill_switch_integrity` or `subpattern_citation_consistency` by editing a guarded field — surface them as the headline caveat instead.

## Configuration

By default every model-driven phase runs on the host LLM. To route phases to a different backend (Gemini, open-weights, custom):

- `NOVELTY_LLM_REASONING_LARGE_CMD` — Phase 1 / 2.1 / 2.2 / 3.2 / 3.3 / 4.fill (needs ≥ 200k context, JSON output)
- `NOVELTY_LLM_CLASSIFY_FAST_CMD` — Phase 0 intent extraction + per-paper pattern tagging (smaller context, JSON output)

**Which tier a step tolerates — the split is by TASK KIND, not by cost** (both directions measured; see design-notes):

- **Mechanical classification against a written rubric** — per-item independent, "which of these N named categories", criteria already in the rubric. *Pattern tagging is the whole of this class.* **Cheapest tier is correct here**, and shardable across parallel sub-agents.
- **Open-ended judgement with no enumerated answer set** — "is this paper on-topic", "what load-bearing work is MISSING", "is this candidate subsumed". *Phase 0.4 partition, Phase 0.5 coverage check, and every gauntlet phase are this class.* **Do NOT downgrade these**, which is why their emits say so explicitly — a cheap tier's over-strict drop is an unrecoverable recall loss, while an over-inclusion costs one row the next stage can still catch.

With no separate cheap model, lower the REASONING EFFORT for the mechanical class rather than reaching for the largest configuration everywhere; reserve full effort for the open-ended class.

Each is a CLI taking a stdin prompt (`<<SYSTEM>>...<<USER>>...`) and emitting JSON on stdout. When unset (the default when running inside any host LLM), the orchestrator emits sentinel files and the host LLM handles those steps natively.

- `IDEASPARK_POOL` — per-job Phase 0 retrieval caps, `job=N,...` (jobs: arxiv, ss_recent, oa_recent, openalex, semanticscholar, openreview). A job at 0 is skipped (this is how oa_recent stays off; set `oa_recent=6` for journal-heavy fields). Malformed values fail-fast.
- `IDEASPARK_RETRIEVAL_CACHE` — cross-run Phase 0 retrieval cache (default `~/.cache/ideaspark/retrieval`, 24h TTL via `IDEASPARK_RETRIEVAL_CACHE_TTL_S`); set to `off` to bypass, or to a path to relocate. Keyed on connector + queries + window + caps + `--as-of`, so any real change to the request misses; successful non-empty results only. Exists because re-running Phase 0 otherwise re-hammers every API — three runs in ~15 min rate-limited arXiv and Semantic Scholar into returning zero records.
- `IDEASPARK_RETRY_PAUSE_S` — pause before the single bounded per-job retry (default 45s). A failed job also hands its cap to the surviving job covering the same window (≤2x).
- `IDEASPARK_RELEVANCE_PARTITION` — set to `off` to disable the Phase 0.4 host relevance-partition (default: on). When off, retrieval's wide net flows straight to tagging with no core/adjacent/off_topic gate (the old `outside_taxonomy`-only behavior); deep-read then falls back to on-topic (non-`outside_taxonomy`) rather than `core`-gated.
- `IDEASPARK_COVERAGE_CHECK` — set to `off` to disable the Phase 0.5 host-recall coverage check (default: on).
- `IDEASPARK_CROSS_RUN_DEDUP` — set to `off` to disable the sibling-run soft-negative-anchor scan in the Phase 2 emit (default: on).
- `IDEASPARK_DEFAULT_COMPUTE` — optional standing compute profile for the user (free text, e.g. `"8×H100 node, ~300 GPU-days, $50k API budget"`). Put it in `.env` (auto-loaded); `next` surfaces it to Phase 1 as intake context. Precedence: compute stated in the user's query > this value > the factory default (80GB-class GPUs, ≤8 concurrent, ≈150 GPU-days / 5 months, ~$10k API campaign). Use this instead of editing the factory default — the default is the feasibility yardstick for users who state nothing.
