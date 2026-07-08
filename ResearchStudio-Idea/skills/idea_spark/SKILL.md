---
name: idea-spark
description: Generate ONE reviewer-defensible, implementable research idea — with a concrete method and a falsification plan, calibrated against the patterns of Oral-accepted papers — from a user's research direction. Diagnoses the bottleneck against retrieved literature, selects 1-3 of 15 induced ideation patterns that structurally fit the bottleneck (with corpus-derived anti-pattern guard), generates a single candidate, runs collision check + critique, and expands into a structured idea card. **One-shot guarantee**: one user input produces one of three outputs — the rendered idea-card markdown (returned inline as the run's final response, with the LaTeX side artifact + per-phase JSON left under the run directory), a `do_not_generate.md` (Phase 1 OOD), or a `phase_3_failed.md` (audit abandons) — never asking the user mid-flow. Use when the user asks for a research idea, novelty analysis, or paper-shape suggestion within a stated direction. Skip for code review, debugging, or pure brainstorming without research context.
---

# Idea Spark Skill

Convert an under-specified research direction into ONE reviewer-defensible Oral-level research proposal — grounded in 1947 ICLR/ICML/NeurIPS papers (2021-2025) — by running a 5-phase workflow that retrieves recent literature, diagnoses the bottleneck, selects + generates a candidate using corpus-derived ideation pattern cards, and runs it through a single quality gauntlet.

## Design principles

1. **Innovation Patterns are diagnostic vocabulary judged per-gap, not classification labels OR generative templates.** The 15 induced ideation patterns (reframe-as-solvable-object, assumption-audit-and-pivot, algebraic-equivalence-unification, heterogeneous-decomposition, architectural-operator-substitution, structural-prior-encoding, characterize-limit-then-surpass, self-supervised-signal-engineering, targeted-self-supervised-objective, controlled-diagnostic-design, unify-into-shared-representation, adapt-via-conditioning, generative-process-redesign, decompose-and-delegate, relax-discrete-search-to-continuous) are how the corpus describes productive research moves. Phase 2.1 reads each pattern's **Definition + Operational signature + When to apply** panels and judges per-pattern per-gap whether the pattern's move closes the gap. Phase 2.2 picks ONE sub-pattern under each chosen main pattern by reading its `tactical_pattern` + `Step-by-Step` + `when_to_pick_this_one` + `differentiation_within_parent` panels at generation. The sub-pattern's Step-by-Step is 5 abstract steps distilled from the cluster's [Accept] examples — domain-agnostic structural moves with [Reject]-derived boundaries embedded, written WITHOUT paper-ID citations so the candidate-author applies the abstract pattern to their own gap rather than mimicking specific papers. Treating patterns as generative templates (verbatim recipe execution + siblings_considered + lock-in rules) converged generation toward corpus-validated incremental work; the cognitive-tool framing avoids that.

2. **Novelty comes from gap-coverage + saturation-aware pattern picking, not from pattern aesthetics.** Phase 2.1 picks 2-4 gaps from `phase1.what_phase_0_did_not_address[]` (1 anchor + 1-3 randomly-sampled siblings + coherence filter — siblings that cannot be coherently closed under the anchor's machinery move to deferred_gaps) and matches each sibling gap to one main pattern by judgment ("does this pattern's operational signature close this gap?") — the anchor gap instead carries 1-3 ranked candidates whose binding is deferred to Phase 2.2 — with saturation-aware preference (avoid both saturated and untested patterns; prefer mid-frequency in lit_table; saturated patterns require novel-angle defense at audit). Multi-gap closure with shape-diverse patterns naturally pulls paper-role coverage (mechanism / measurement / theory / diagnostic) — single-gap closure produces system-architecture sketches. Phase 2.2 enforces substantive novelty via `differentiation_from_lit[].delta` (what we derive/claim/construct/measure that closest_adjacent did not — not "we use a different ideation pattern").

3. **Theory + Engineering legs are both required, but signature-agnostic.** Both legs must be non-trivial. Each leg can be theorem OR observable regime OR scaling exponent OR measurement primitive OR architectural property — the audit doesn't prefer one Oral signature (theory + reframing-first) over others (scaling-law, empirical-reveal, surgical-fix, benchmark-validity). All Oral shapes the corpus contains can score 5.

4. **Mechanism-aware falsification.** Every candidate's `falsification_prediction` is a single paragraph (3-5 sentences) that visibly contains (a) the minimal experiment, (b) which metric moves and in which direction if the candidate works (name the metric + qualitative direction; the experiment establishes the magnitude), and (c) a mechanism distinguisher pivoting on ONE NAMED LOAD-BEARING VARIABLE — the single quantity (e.g., a gradient norm, an information-gain term, a logit divergence, a learned threshold, a representational direction) whose behavior carries the mechanism claim — plus a negative-control intervention on that variable that should drive the DOWNSTREAM OUTCOME METRIC back to baseline. The negative control's predicted effect MUST be the task-outcome metric that defines the mechanism's value (accuracy, regret slope, refusal pass-rate trajectory) — NOT the load-bearing variable's own value or any quantity analytically derived from it (a control of the form "intervene on X → X becomes 0" tests a definition, not a mechanism). A positive control (a stripped-down model using only the load-bearing variable that recovers most of the downstream effect) is recommended when feasible. Without the load-bearing-variable-plus-non-tautological-negative-control structure, "metric moved" remains consistent with calibration improvements / estimator quality / data shifts / many other non-mechanism explanations — and the candidate is the dominant Reject signal in the corpus. `compute_budget` is a separate flat field, **user-relative** (no absolute cap) — Phase 4 feasibility_validation compares to `intake.compute`. **Default `intake.compute = 1×A100 × 3 months ≈ 90 A100-day`** (canonical "single researcher with cloud access" scale) when the user does not state compute; user-supplied intake overrides. Both `falsification_prediction` and `compute_budget` are kill-switch fields: byte-identical preserved across Phase 2.2 → Phase 3.3 (when revise runs) → Phase 4.

5. **Anti-pattern is empirical negative knowledge — audit-only.** The corpus identifies 3 reject-favored 2-way compositions (audit + auxiliary_signal, audit + invariance, audit + surgical_fix), each with a specific required_mitigation; rates and mitigations live in `references/anti-patterns.md`. **Phase 2 does NOT load anti-patterns.md** — naming reject-prone compositions during generation creates Streisand-effect priors that bias selection. Phase 3.2 audit's `anti_pattern_check` reads anti-patterns.md, detects matching compositions via the SET of `gap_closure[].main_pattern` values, and verifies substantive mitigation delivery (not keyword presence). Failed audit → Phase 3.3 revise rewrites the candidate's affected fields with the corpus-grounded fix.

6. **Cheap kills first, expensive expansion last.** Phase 3 runs collision retrieval (real, ~30s, no LLM) before audit (single LLM call replacing earlier 4-attacker simulation). Heavy expansion of the candidate into motivation + method_flow + claims + abstract happens only in Phase 4, after the candidate clears the gauntlet.

7. **Phase 3.2 is judgment, not modification.** The audit reports what corpus evidence triggered which signals; it does NOT auto-revise the candidate. When revision is needed, the audit emits `revision_targets[]` and Phase 3.3 (a separate LLM call) applies them — keeping audit and modification on different surfaces avoids the self-answering bias of cherry-picking attacks one can already answer.

## When to use

- "Give me a research idea in {area} I could pursue."
- "What's the most impactful next step in this direction?"
- "Help me sharpen this vague direction into an Oral-level proposal."
- "What's the bottleneck of this problem?"
- "Run a novelty audit on this idea."

## When NOT to use

- Code review, debugging, refactoring (use a coding skill).
- Summarizing one paper.
- Cross-decade survey writing.
- Free-association brainstorming with no research context.
- Engineering integration tasks ("ship this feature in our system").
- Pure benchmark / dataset construction work — current 15-ideation pattern vocabulary handles benchmark *audit* (controlled_diagnostic_design) but not benchmark *construction*.

## Setup (before first use)

The skill's Phase 0 + Phase 3.1 retrieval needs API credentials for 2 of the 4 connectors. Without them the affected connectors are skipped and the orchestrator continues with whichever connectors are available — but it now prints a prominent **CONNECTORS DEGRADED** banner and writes a `.connectors_degraded` marker so a partial run is never mistaken for a full one.

0. **Set two shell variables once per session** — where this skill is installed, and where run outputs should go. Neither depends on the harness:
   ```bash
   SKILL_DIR=~/.claude/skills/idea-spark            # Claude Code default; Codex CLI: ~/.codex/skills/idea_spark; else wherever this folder lives
   RUN_DIR="$PWD/idea_run" && mkdir -p "$RUN_DIR"   # ANY absolute directory you want the per-phase outputs in
   ```
   `RUN_DIR` is purely an output anchor — the orchestrator only ever sees the absolute `--out` paths you pass, so the variable *name* does not matter (Claude Code sessions can reuse the injected `CLAUDE_PROJECT_DIR` as their `RUN_DIR`). The orchestrator hard-fails early with an actionable message when a path argument contains an unexpanded `$variable`, collapses to filesystem root (empty expansion, e.g. `/phase0`), or is a relative `--out` — instead of a confusing `FileNotFoundError` mid-run.
1. **Install the skill**: `idea-spark` — Phase 0 literature search runs from its bundled connector scripts (no separate sub-skill).
2. **Install Python deps** (cross-platform — macOS & Linux): `python3 -m pip install feedparser openreview-py beautifulsoup4 pymupdf`. Four lean packages (`feedparser`, `openreview-py`, `beautifulsoup4`, `pymupdf`). Skipping this is the most common first-run failure: `arxiv` errors with `package not installed`, and missing `pymupdf`/`beautifulsoup4` silently degrades every full-text fetch to abstract-only.
   - **PEP 668 systems** (recent macOS/Homebrew & Ubuntu 23.04+) reject a bare `pip install` with `externally-managed-environment`. Two safe options:
     - **venv (recommended):** `python3 -m venv .venv && source .venv/bin/activate && pip install feedparser openreview-py beautifulsoup4 pymupdf` — then launch every phase **from this same activated shell** (see the connector-degradation note below).
     - **user install:** `python3 -m pip install --user --break-system-packages feedparser openreview-py beautifulsoup4 pymupdf`.
   - **Use the SAME interpreter everywhere.** `check_connectors` and the phase commands must run under the one Python that has these packages. A package installed for `pip3` but launched under a different `python3` (or a background/non-login shell that drops `--user` site-packages) will pass `check_connectors` yet skip `arxiv`/`openreview` at runtime — the run now prints a loud **CONNECTORS DEGRADED** banner and drops a `.connectors_degraded` marker when that happens.
   - **Optional deps (only if you want the extras):** PDF compilation of the idea card needs **xelatex** *or* **tectonic** (macOS `brew install --cask mactex-no-gui` or `brew install tectonic`; Ubuntu `sudo apt-get install texlive-xetex` or `cargo install tectonic`). Without either, the `.md`/`.tex` cards are still written and only the PDF is skipped (with a hint). The optional pipeline-diagram image needs the `azure-*` packages; absent, it is skipped silently.
3. **Copy** the env template at the project root: `cp .env.template .env`.
4. **Fill in keys** (priority order — by impact on retrieval quality):

| Key | Required for | How to get |
|---|---|---|
| `OPENREVIEW_USER` + `OPENREVIEW_PASS` | OpenReview connector (in-review forward signal). Without these, openreview is silently skipped — you lose the 0-6mo in-review window unique to it. | Free signup at https://openreview.net |
| `SEMANTICSCHOLAR_API_KEY` | Semantic Scholar connector at usable rate. Anonymous tier (~100 req/5min) hits 429 on Phase 0 multi-query batches; with key it's stable at 1 req/s. | Free apply at https://www.semanticscholar.org/product/api#api-key-form (≈24h review). Connector still runs anonymously without it but will frequently 429. |
| `OPENALEX_API_KEY` | Optional, premium rate. Polite-pool already works for typical Phase 0 load. | Apply at openalex.org if you exceed polite limits. |

5. **Verify** (from the SAME shell/venv you will launch phases from): `python3 "$SKILL_DIR/scripts/run.py" check_connectors` — should show ✅ for all 4 connectors AND the two full-text fetch deps (`pymupdf`, `beautifulsoup4`). If you verify in one shell but run phases in another, the package set can differ — keep it one shell.
6. **The orchestrator auto-loads `.env`** at runtime (walks up from skill dir to find `.env`), so you do NOT need to `source .env` in your shell. Shell-set env vars take precedence over `.env` values, so you can override on the fly.

If a connector shows ❌, it's either missing creds (fix in `.env`) or missing the pip package (the error message tells you which `pip install` to run). If a full-text dep shows ⚠️, run `pip install feedparser openreview-py beautifulsoup4 pymupdf`.

---

## The 5-phase workflow

```
Run progress:
- [ ] Phase 0: Literature grounding (in-skill connectors, role-based retrieval) → lit_table.md
- [ ] Phase 0+: Full-text fetch (orchestrator, runs immediately after lit_table.md) → fulltext_cache.json  ← MANDATORY; Phase 1 hard-gates on it
- [ ] Phase 1: Bottleneck identification (single LLM call) → bottleneck statement + closest_adjacent
- [ ] Phase 2.1: Gap × main-pattern selection (1 LLM call — judgment-per-pattern + saturation-aware + anchor + random sibling + coherence filter) → selected_gaps[]
- [ ] Phase 2.2: Sub-pattern picking + candidate generation (1 LLM call — read tactical_pattern + Step-by-Step per gap, write 12-flat-field candidate)
- [ ] Phase 3: Quality gauntlet (retrieval + audit + revise-when-needed; Phase 3.3 emits a patch + deterministic merger writes `final_candidate.json`)
- [ ] Phase 4: Skeleton (orchestrator) → fill (1 LLM call, prose-only) → assemble (orchestrator) → render → idea-card markdown + LaTeX
```

If your host exposes a task/todo tool (e.g., Claude Code's TodoWrite), seed it with the phases above and mark each one completed as you finish it; otherwise just re-emit this checklist with `[x]` as you progress.

**Context discipline (REQUIRED — see the "Context discipline" section below for full rules).** Every LLM-driven phase (1 / 2.1 / 2.2 / 3.2 / 3.3 / 4.fill / 4.1.5) must run in a fresh sub-agent (or compacted host context) with file-path inputs only, `Write`-to-disk outputs, and no inline JSON paraphrase. Running these phases inline in the parent context routinely hits the API request timeout once cumulative state exceeds ~150-180k tokens.

Three outcomes per run: the rendered idea-card markdown returned inline (advance OR revise→3.3 path; LaTeX side artifact + per-phase JSON left under the run directory), a `do_not_generate.md` (Phase 1 OOD), or a `phase_3_failed.md` (audit abandons). The user gets one of these three from one input — no mid-flow clarification. **One-shot guarantee preserved** even when audit triggers revise: Phase 3.3 mechanically applies the revision_targets and Phase 4 proceeds without user re-invocation.

### How phases run (orchestrator vs. host LLM)

Two phases need real external retrieval and run via `scripts/run.py`:

### Invocation contract (host LLMs read this first)

**No `cd` is required.** `scripts/run.py` self-locates its skill root (it inserts the skill directory into `sys.path` at startup), so every orchestrator command can be invoked from ANY working directory by absolute script path:

```bash
python3 "$SKILL_DIR/scripts/run.py" <subcommand> --out "$RUN_DIR/<phase>/" ...
```

The legacy form `cd "$SKILL_DIR" && python3 -m scripts.run <subcommand> ...` still works identically. Do NOT use relative script or `--out` paths — CWD is not stable across host-LLM Bash invocations, and the orchestrator rejects a relative `--out` outright.

**Exit codes 10 and 11 are NOT errors — they are sentinel handshakes.** When the orchestrator can't call an LLM itself (no `NOVELTY_LLM_CLASSIFY_FAST_CMD` env var), it writes a sentinel JSON file describing what the host LLM should do next, then exits with rc=10 (intent / pattern-summary) or rc=11 (signature_terms). The host LLM:

1. `cat $RUN_DIR/<phase>/.<step>_pending` to read the sentinel
2. Read the file at the sentinel's `rubric_file` field (an absolute path)
3. Produce the expected output per the rubric
4. Re-invoke per the sentinel's `re_invocation` field

If the host LLM treats rc=10/11 as failure and stops, the run stalls. Do not stop on these codes — continue per the sentinel.

### Context discipline (host LLMs read this BEFORE running any LLM-driven phase)

A full Idea-Spark run accumulates ~180-250k tokens of intermediate state (lit_table, fulltext_cache, per-phase JSONs, audit reports). If the host LLM carries that state in its own conversation context across phases, the Phase 1 / Phase 2.2 / Phase 4.fill calls — each of which produces a multi-kilobyte structured JSON on top of an already-large prompt — routinely hit the backend request timeout and surface as `[API Error · Request timed out · Retrying...]` to the user. The retry runs against the same context and tends to time out again, producing a stuck run with zero artifact output. Three rules together prevent this; apply all three on every run, not "if the run feels heavy":

**Rule 1 — Run every LLM-driven phase in an ISOLATED context.** Phase 1 / 2.1 / 2.2 / 3.2 / 3.3 / 4.fill / 4.1.5 are independent JSON-producing steps with well-defined inputs (a system prompt + 1-3 disk artifacts) and a well-defined output (one JSON written to disk), so no phase needs the conversation that produced an earlier one. Three interchangeable isolation mechanisms — use the FIRST one your harness supports:

- **(a) Subprocess LLM — harness-agnostic, the skill's native mode.** Set `NOVELTY_LLM_REASONING_LARGE_CMD` (and `NOVELTY_LLM_CLASSIFY_FAST_CMD`) to any CLI that reads a `<<SYSTEM>>...<<USER>>` prompt on stdin and emits JSON on stdout (see § Configuration). The orchestrator then runs each LLM-driven phase as its own subprocess — a fresh context per phase by construction, on any harness (Codex CLI, cron, plain shells).
- **(b) Sub-agent tool — Claude Code and harnesses with an equivalent.** Spawn an `Agent` per phase, passing ONLY the file paths the phase prompt lists at its top — not the conversation history, not the lit_table contents inline, not prior phase outputs as prose. The sub-agent reads from disk, writes back to disk, and returns ≤ 250 words confirming the output path + the routing/verdict signal the parent needs.
- **(c) Manual context reset — any interactive harness with neither (a) nor (b).** Run the phase inline, but clear/compact the conversation at the four compact points named in Rule 3 before starting the next phase. Every phase re-reads its inputs from disk, so clearing loses nothing; what it costs is discipline, not information.

Whichever mechanism you use, the parent context stays ≤ ~30k tokens for the whole 5-phase run because it never holds a phase's structured output in its own turns.

**Rule 2 — `Write` every phase artifact directly to disk; never paraphrase it into chat.** The output schema for each LLM-driven phase is fixed (see the `Output:` section of the matching `references/system-prompts/<phase>.txt`) and the convention is `$RUN_DIR/<phase>/<phase>_output.json`. Use the `Write` tool with that exact path; do NOT `cat <<EOF > file` (a Bash heredoc with a multi-KB JSON triggers permission prompts and can be silently truncated), do NOT `echo` the JSON, and crucially do NOT paste the JSON into your reply for the parent to read — `Write` to disk and report the path. Downstream phases re-read from that path. Tool-result captures from large extraction commands (e.g. printing every paper's abstract for inspection) should also go through `head -c 4000` / `jq` / `sed` to bound the captured payload to ≤ 4 KB; never `Read` a >10 KB intermediate dump back into the prompt — that was the specific anti-pattern that pushed prior runs into timeout (the dump itself is small, but `Read`ing it caches it into every subsequent turn).

**Rule 3 — Compact between phases.** Each phase's output is persisted under `$RUN_DIR/<phase>/`, so the conversation that produced it carries no information the next phase needs. The natural compact points are: **after Phase 0+** (drops lit_table + fulltext exploration), **after Phase 1** (drops bottleneck reasoning), **after Phase 2.2** (drops sub-pattern reading), **after Phase 3.2** (drops audit reasoning). Each phase re-reads its disk inputs and proceeds. If your harness exposes `/compact`, invoke it at those four points; otherwise the same effect is achieved by Rule 1 alone (each sub-agent is already a fresh context).

**Diagnostic if you see "Request timed out" mid-phase.** Inspect your harness's session transcript/log (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`, look for `isApiErrorMessage: true`; other harnesses: their session-log equivalent). The context just above the error (the prior tool call and its result) tells you which prompt got too big to inference inside the request budget. The fix is always one of the three rules above — usually Rule 1: re-issue the timed-out step in an isolated context with only the file paths it needs.

### Phase entry points

| Phase | Entry point (`python3 "$SKILL_DIR/scripts/run.py" ...`, any CWD) | Why orchestrator |
|---|---|---|
| Phase 0 (literature grounding) | `python3 "$SKILL_DIR/scripts/run.py" phase0 --query "..." --out $RUN_DIR/phase0/` | probes 4 connectors (arxiv, openalex, semanticscholar, openreview), runs role-based retrieval, dedups; auto-loads `.env` for OPENREVIEW_USER/PASS + SEMANTICSCHOLAR_API_KEY |
| Phase 0+ (full-text fetch — **mandatory**, run right after `lit_table.md` is written) | `python3 "$SKILL_DIR/scripts/run.py" phase0_fulltext --out $RUN_DIR/phase0/` | caps the on-topic pool to the most relevant ~15 (+U user refs), fetches intro+method concurrently into `fulltext_cache.json`; Phase 1 hard-gates on this output |
| Phase 3.1 (collision check) | `python3 "$SKILL_DIR/scripts/run.py" phase3_collision --idea-json <p2.2-output> --out $RUN_DIR/phase3_collision/` | re-uses all 4 connectors with the candidate's signature_terms |
| Phase 3.3 merger (after the LLM emits the revise patch) | `python3 "$SKILL_DIR/scripts/run.py" phase3_merge_revisions --phase2 <p2.2-output> --revisions <p3.3-patch> --out $RUN_DIR/phase3_revise/` | applies the LLM's `applied_revisions[]` patch deterministically; refuses kill-switch writes; writes `final_candidate.json`; back-injects `final_candidate` into the patch file so the legacy `kill_switch_integrity` chain-check still works |
| Phase 4 skeleton (runs BEFORE the Phase 4 LLM call) | `python3 "$SKILL_DIR/scripts/run.py" phase4_skeleton --candidate <final_candidate-or-p2.2> --phase1 ... --phase2-select ... --phase3-critique ... [--phase3-revise ...] --phase0-dir $RUN_DIR/phase0/ [--collision ...] --out $RUN_DIR/phase4/` | populates every mechanical field of the expansion (kill-switch echoes, venue_year lookups, lit_table group-by, candidate_uses, reviewer_concerns lifts, compute verdict); leaves prose fields as `<TODO[path]>` placeholders for the LLM to author |
| Phase 4 assembler (runs AFTER the Phase 4 LLM call) | `python3 "$SKILL_DIR/scripts/run.py" phase4_assemble --skeleton $RUN_DIR/phase4/phase4_skeleton.json --fill-map $RUN_DIR/phase4/fill_map.json --out $RUN_DIR/phase4/` | merges the LLM's flat `{path: value}` fill_map into the skeleton; refuses any fill_map key whose root is `falsification_prediction` or `compute_budget`; writes `phase4_expansion.json` |
| Phase 4.render (idea-card rendering) | `python3 "$SKILL_DIR/scripts/run.py" phase4_render --expansion $RUN_DIR/phase4/phase4_expansion.json --out $RUN_DIR/phase4/` | templating only — writes `idea.std.{en,zh}.md` + `idea.detail.en.md` (returned inline) + `idea.std.{en,zh}.tex` side artifacts, and auto-compiles `.pdf` when `xelatex`/`tectonic` is on PATH (skipped with a hint otherwise) |
| Validators | `python3 "$SKILL_DIR/scripts/run.py" validate ...` | static contract checks |

The remaining phases — **Phase 1 bottleneck identification, Phase 2.1 ideation pattern selection, Phase 2.2 candidate generation, Phase 3.2 critique, Phase 3.3 revise (patch-only — the merger then turns it into `final_candidate.json`), Phase 4.fill (prose-only, on top of the skeleton), Phase 4.1.5 implementability audit** — are LLM-driven and run *manually* by the host LLM (or user) reading the corresponding system prompt under `references/system-prompts/`, providing the listed inputs, and writing the JSON output to the conventional `$RUN_DIR/<phase>/...` location. There is no orchestrator subcommand for these because adding one would just be a thin `cat <prompt> + <inputs> | llm` wrapper — no validation work happens between input assembly and the LLM call. Wrapping it in Bash would add fragility (env vars, CLI shape, JSON post-processing) without buying determinism.

**Each of these phases MUST be run under the "Context discipline" rules above** — fresh sub-agent, `Write`-to-disk output, no inline JSON paraphrase. Phase 4.fill is the largest single output and the most timeout-prone; do not run it in the parent context.

The convention each manual phase follows: read the prompt at `references/system-prompts/<phase>.txt`, gather inputs listed at the top of the prompt, produce the JSON described under `Output:`, save it to `$RUN_DIR/<phase>/<phase>_output.json`. Downstream phases read that filename.

### CRITICAL: Literature grounding mode

Phase 0 and Phase 3.1 collision require **real external retrieval** via the in-skill connector scripts (`scripts/search_*.py`, bundled in this skill). Two states (simplified from earlier 4-state design): `lit_grounding_mode = real` (any connector worked, including webfallback with per-paper retrieved_via tagging) vs `connector_failure` (no connector, no fallback flag — orchestrator halts with diagnostic). Without at least one working connector, the skill halts cleanly rather than degrading silently.

Install the skill in your harness's skill directory (Claude Code: `idea-spark`; Codex CLI / others: clone or copy this folder anywhere and point `SKILL_DIR` at it); Phase 0 retrieval runs from its bundled connector scripts (no separate sub-skill to install).

---

### Phase 0 — Literature Grounding

Phase 0 runs via a single Bash command — the orchestrator at `scripts/run.py`. This physically narrows tool choice to one path; alternative paths (WebSearch, ad-hoc fetch) produce unstructured output that downstream phases reject.

```bash
python3 "$SKILL_DIR/scripts/run.py" phase0 --query "<user's research question>" --out $RUN_DIR/phase0/
```

**What the orchestrator does internally**:

1. Asserts system clock is sane (≥ 2024-01, ≤ 2027-01).
2. Intent extraction: turn the user's free-text query into 4-6 search queries (including one ESCAPE-MECHANISM query phrased in solution vocabulary, which recalls papers that already fixed the bottleneck and title themselves by their fix — problem-keyed queries miss exactly those). Without an external LLM CLI configured, emits `.intent_extraction_pending` sentinel and exits — the host LLM produces queries per `references/intent-recognition.md`, then re-invokes with `--queries "q1|q2|q3"`.
3. Probes 4 connectors (arXiv, OpenAlex, Semantic Scholar, OpenReview) and reports availability. Auto-loads `.env` for OPENREVIEW_USER/PASS + SEMANTICSCHOLAR_API_KEY.
4. **Role-based retrieval** (each connector used where it's most informative):

   | Connector | Window | Cap | Role |
   |---|---|---|---|
   | arxiv | 0-6 mo | 10 | preprint pool — recent active work (sortBy=relevance) |
   | openalex | 6-24 mo | 12 | published proceedings + journals (`--published-only`); broad academic graph |
   | semanticscholar | 6-24 mo | 13 | published CS-focused; returns TLDR (Allen-AI 1-sentence summary) + ArXiv/DOI cross-IDs in one record |
   | openreview | 0-6 mo | 10 | in-review submissions (forward signal); venues runtime-derived; `get_notes(limit=500, sort='cdate:desc', mintcdate=since)` for fast retrieval (~7s/query); 600s connector timeout |

   Target: ~40-45 papers. Gracefully degrades when a connector is unavailable. Windows are non-overlapping (0-6mo arxiv vs 6-24mo openalex+SS vs 0-6mo openreview), so a paper that's both a recent preprint and an in-review submission doesn't double-count via cross-source dedup on (title_norm, externalIds).
5. Dedups across sources with file-order priority (semanticscholar > openalex > openreview > arxiv) — SS first because its `externalIds` (DOI + ArXiv + DBLP keys) makes it the highest-quality cross-source anchor.
6. **pattern_summary** (LLM step) tags each paper with ideation pattern + bottleneck + open_issue + retrieved_via, producing `lit_table.md`. Without an external LLM CLI, emits `.pattern_summary_pending` sentinel for the host LLM to fill.
7. Writes one gate sentinel: `.lit_grounding_mode = real`.
8. **User-reference extraction** (regex on query string at phase0 entry): scans the user query for arxiv URLs / arxiv IDs (`arxiv:2401.12345`) / OpenReview URLs / DOIs and writes them to `$RUN_DIR/phase0/user_refs.json`. The intent-extraction sentinel also asks the host LLM to append paper-title references (e.g., "based on the LoRA paper") to the same file. These become the **U tier** of the full-text fetch pool used in step 9.

9. **Full-text fetch for the candidate pool** — **MANDATORY, not optional**. This is a separate orchestrator subcommand, but it is *bound to the moment `lit_table.md` is written*: the instant step 6's `lit_table.md` lands on disk, run this command before touching Phase 1. It is its own subcommand (not folded into `phase0`) only because it depends on the host-LLM-produced `lit_table.md` to know which papers are on-topic — that dependency is why it cannot run inside the same `phase0` Bash call. Phase 1 **hard-gates** on `fulltext_cache.json` (stops with `error: fulltext_not_fetched` if it is missing), so skipping this step halts the pipeline rather than silently degrading to abstract-only reasoning — which was the previous failure mode.

   ```bash
      python3 "$SKILL_DIR/scripts/run.py" phase0_fulltext --out $RUN_DIR/phase0/
   ```

   This selects a small candidate pool — **U** (user refs from `user_refs.json`, always included, never capped) + **T2** (papers from OpenAlex/Semantic Scholar where lit_table tag ≠ `outside_taxonomy`, up to `--t2-top` = 10, method-first with cross-source round-robin) + **T3** (arxiv on-topic papers, method-first, up to `--t3-top` = 5) — with a hard ceiling of `--max-pool` = 15 total fetches **excluding** user refs, so the pool stays at the most relevant ~15 (+U) papers rather than the full on-topic set. Ordering is **method-first**: papers whose only innovation tag is `controlled_diagnostic_design` (eval/benchmark-only, low fulltext value) sink below method-bearing papers, and within each tier sources are interleaved round-robin so a single high-`DEDUP_PRIORITY` source (e.g. Semantic Scholar) cannot crowd out OpenAlex; same-paper duplicates retrieved from two sources are collapsed via `title_norm`. All papers are fetched **concurrently** (ThreadPoolExecutor, ≤15 workers) with a per-paper budget (`pdf_timeout` 30s, `per_paper_budget_s` 75s) so a few slow/unreachable PDFs cannot stall the whole step. Because the fetch is concurrent, this budget caps the **wall-clock** at roughly the slowest single paper rather than the sum, so it is set generously to avoid dropping fetchable content. It fetches intro + method sections for each. The HTML path (`arxiv.org/html/<id>`) is tried first (works for ~85% of 2024+ ML preprints); for papers without HTML or non-arxiv sources, the PDF is downloaded and parsed via pymupdf. Section extraction targets headings Introduction / Method / Methodology / Approach / Model Architecture / Main Results (positional fallback handles theory papers where the canonical "Method" name is absent). Limitations is intentionally not extracted — author-written limitation paragraphs are often weaker than what the audit synthesizes from method + experiments.

   Output: `$RUN_DIR/phase0/fulltext_cache.json` — keyed by paper_id, each entry `{tier, intro, method, source_used, warning}`. Fetch failures degrade gracefully to abstract + warning; the pipeline never halts on a fetch error. Phase 1 reads the full cache when writing `bottleneck_statement` + `closest_adjacent[]`; Phase 2.2 reads only the closest_adjacent entries when writing `differentiation_from_lit[].delta` and `core_mechanism`'s quantitative claims (which must cross-check against any disagreeing values in the cache).

**Host-LLM handshake** (when `NOVELTY_LLM_CLASSIFY_FAST_CMD` is unset — typical when running inside a host LLM): the orchestrator emits sentinel files in a common schema rather than silently substituting model knowledge. Three sentinel sites in Phase 0 + 3.1:

| Sentinel | Trigger | Host LLM action |
|---|---|---|
| `.intent_extraction_pending` | rc=10, no `--queries` and no LLM env | Read `references/intent-recognition.md` (Map mode), produce queries, re-invoke `phase0 --queries "q1\|q2\|q3"` |
| `.pattern_summary_pending` | informational | Read `references/pattern-summary-rubric.md`, classify each paper into 1-3 of the 15 ideation patterns, write lit_table.md |
| `.signature_extraction_pending` | rc=11 in Phase 3.1 | Read `references/intent-recognition.md` (Collision mode), produce 3-5 signature_terms, re-invoke phase3_collision |

The sentinel JSON itself carries the absolute `rubric_file` path that the orchestrator wrote, so the host LLM does not need to guess where the rubric lives — it should read from the sentinel's `rubric_file` field directly. The relative paths in this table are documentation hints; the canonical path is whatever the sentinel records.

`lit_table.md` schema (consumed by Phase 1):

```markdown
| paper_id | year_month | venue | title | ideation pattern tags | bottleneck this paper targets | open issue / unresolved gap | resolves_problem | retrieved_via |
```

---

### Phase 1 — Bottleneck Identification

Single LLM call. Use [references/system-prompts/bottleneck_identify.txt](references/system-prompts/bottleneck_identify.txt).

Phase 1 does one substantive thing: read user query + lit_table.md + intake, write a literature-grounded bottleneck statement plus the routing decision.

**Inputs**: user query, intake context, `$RUN_DIR/phase0/lit_table.md`, `$RUN_DIR/phase0/fulltext_cache.json` (intro+method for the candidate pool — read BEFORE writing bottleneck/closest_adjacent; the entry assertion **hard-gates** on this file: missing → stop `fulltext_not_fetched`, all-failed → continue with `fulltext_degraded: true` + abstract-level residue confidence), `$RUN_DIR/phase0/lit_results.json` (for abstract-level grounding when needed).

**Output schema**: see `bottleneck_identify.txt`. Key fields:
- `intake` (with `_inferred_fields[]` listing fields not stated by user)
- `bottleneck_statement` — one paragraph citing ≥ 2 paper_id from lit_table inline
- `closest_adjacent[]` — list of `{paper_id, summary_and_residue}`
- `what_phase_0_did_not_address[]`
- `state ∈ {proceed, do_not_generate}`

**No-ask guarantee**: missing intake fields are inferred from user query + Phase 0 retrieval; if hopelessly missing, route to `do_not_generate` with concrete remedial_steps rather than asking.

**Routing**:
- **proceed** — bottleneck is literature-groundable AND no OOD trigger fires
- **do_not_generate** — OOD (too-broad direction / no-anchor) OR lit_table too sparse (< 5 truly-relevant papers) OR genuinely blank-space (no adjacent literature) OR benchmark/system construction (current vocab doesn't cover) → emit `do_not_generate.md` with redirect

---

### Phase 2 — Idea Generation (2 LLM calls)

#### Step 2.1 — Gap × Main-Pattern Selection

Use [references/system-prompts/ideate_select.txt](references/system-prompts/ideate_select.txt).

**Inputs**:
- `$RUN_DIR/phase1/phase1_output.json` — `what_phase_0_did_not_address[]` is the load-bearing field (2-4 collective gaps no retrieved paper closes); `bottleneck_statement` + `closest_adjacent[]` + `intake` for context.
- `references/ideation-patterns/overview.md` — read each of the 15 patterns' **Definition + Operational signature + When to apply** panels. Selection at WHAT/WHEN level, not HOW.
- `$RUN_DIR/phase0/lit_table.md` — to compute pattern frequency for saturation-aware selection.

**Selection process**:
1. **Pick anchor gap** — the single most important gap from `what_phase_0_did_not_address[]`.
2. **Sample 1-3 sibling gaps** randomly + apply coherence filter (siblings that cannot be coherently closed under anchor's machinery → deferred_gaps).
3. **For each selected gap**, judge each of the 15 patterns directly: does this pattern's move, applied to this gap, actually close it? Saturation is recorded (joined from Phase 1's `domain_pattern_distribution`) for audit transparency, NOT used as a selection filter (saturated ≥50% / untested ≤1 paper / mid_frequency between). Saturated/untested choices require novel-angle defense at Phase 3.2 audit.

**Output**: `selected_gaps[]` (each entry: `gap` verbatim from phase1 + `chosen_pattern_id` + `selection_rationale`; index 0 is anchor, rest are siblings) + `coherence_thread_type` + top-level `pattern_saturation` dict (keyed by pattern_id) + `deferred_gaps[]`.

#### Step 2.2 — Sub-Pattern Picking + Candidate Generation

Use [references/system-prompts/ideate_generate.txt](references/system-prompts/ideate_generate.txt).

**Inputs**:
- `$RUN_DIR/phase2_select/phase2_select_output.json` — the gap × pattern spec.
- `$RUN_DIR/phase1/phase1_output.json` — bottleneck + closest_adjacent + intake.
- `$RUN_DIR/phase0/lit_results.json` — abstracts of closest_adjacent for substantive comparison.
- `references/ideation-sub-patterns/<cluster>.md` — for each picked sub-pattern, read **`tactical_pattern` + `Step-by-Step` + `when_to_pick_this_one` + `differentiation_within_parent`**. The Step-by-Step is your tactical recipe (5 abstract structural-move steps; not paper-mimicry).

**Sub-step a — pick sub-pattern under each gap's main pattern**: open `ideation-sub-patterns/overview.md` to find candidates per parent; compare `when_to_pick_this_one + differentiation_within_parent` panels; pick ONE per gap; then read picked sub-pattern's `tactical_pattern + Step-by-Step`.

**Sub-step b — write candidate**: apply each picked sub-pattern's Step-by-Step to its specific gap; write candidate JSON.

**Output**: ONE candidate with flat fields (0 nesting):
- `title` / `hook` / `core_mechanism` / `core_mechanism_reasoning` / `core_mechanism_steps`
- `gap_closure[]` — per-gap entry mirrors `selected_gaps[]` one-for-one: `{gap, main_pattern, sub_pattern, how_closed}`. `sub_pattern` is emitted as `C## (parent pattern name)` — e.g. `C12 (Substitute the Operator or Representation)` — so the opaque code is always spelled out; consumers that open the card file strip to the leading `C##`.
- `falsification_prediction` (single paragraph: minimal experiment + metrics-that-move; mechanism distinguisher optional)
- `compute_budget` (user-relative, concrete number) — kill-switch with `falsification_prediction`
- `differentiation_from_lit[]` ({paper_id, substantive delta})
- `almost_prior_paper_id` + `what_step_was_missed` (single closest paper + substantive missed step)
- `signature_terms[]` (Phase 3.1 collision retrieval keys)

**Two hard rules** (the rest is in schema descriptions):
1. **Substantive > methodological** in `differentiation_from_lit[].delta` and `what_step_was_missed`.
2. **`falsification_prediction` names the experiment + metric that moves (qualitative direction) + a mechanism distinguisher that pivots on ONE named load-bearing variable with a negative-control intervention that should drive the effect back to baseline if the variable is the mechanism** — the experiment establishes magnitude; the load-bearing variable + intervention is what makes the prediction Popper-testable rather than consistent with "calibration improved" / "estimator quality" alternatives.

**Why 2 stages with judgment, not lock-in.** A lock-in alternative would demand verbatim quotes from cards + enforced siblings_considered + sub-pattern recipe execution + many hard rules; cumulatively that converges generation toward corpus-validated incremental work and kitchen-sink mechanism stacks. The judgment-based 2-stage design (Phase 2.1 = judgment per pattern at Operational-signature level; Phase 2.2 = sub-pattern as descriptive vocabulary not recipe) produces paper-shape candidates while preserving audit anchors via `gap_closure[].main_pattern + sub_pattern`.

**K=1, not K=2/3.** Single candidate goes through critique. (Earlier K=3/K=2 design had no auto-selection downstream — overhead without quality win.)

**Citation gate (deterministic, MANDATORY before Phase 3).** The instant the candidate JSON is written, run the `subpattern_citation_consistency` validator. It is a hard gate: a fabricated `gap_closure[].sub_pattern` (a hallucinated parent slug, a C## whose real parent differs from the cited `main_pattern`, or an invented parenthetical name) must be caught here, before any retrieval / audit / expansion work is spent on it.

```bash
python3 "$SKILL_DIR/scripts/run.py" validate --phase2 $RUN_DIR/phase2_generate/phase2_generate_output.json
```

If it reports any `fail`, the citation was written from the parent pattern's gist rather than read from `overview.md`. Do NOT proceed to Phase 3. Re-open `references/ideation-sub-patterns/overview.md`, fix the `main_pattern` / `sub_pattern` to a real cluster row (or regenerate Step 2.2 with the card actually open), and re-run the gate until it passes. This guard proves only parent-consistency; whether `core_mechanism` performs the cluster's actual tactic is judged later by Phase 3.2's `recipe_application_check`.

---

### Phase 3 — Quality Gauntlet (1 retrieval + 1-2 LLM calls)

#### Step 3.1 — Mechanism-specific collision retrieval

Run via the orchestrator:

```bash
python3 "$SKILL_DIR/scripts/run.py" phase3_collision --idea-json $RUN_DIR/phase2_generate/phase2_generate_output.json --out $RUN_DIR/phase3_collision/
```

Orchestrator probes all 4 connectors (arXiv / OpenAlex / Semantic Scholar / OpenReview) and runs each available one with a 6-month window using the candidate's `signature_terms[]`, dedups across sources, writes `collision_hits.json`.

If candidate lacks `signature_terms[]`, orchestrator emits `.signature_extraction_pending` sentinel — host LLM reads the path in the sentinel's `rubric_file` field (resolves to `references/intent-recognition.md`, Collision mode rubric), produces 3-5 terms, edits the candidate JSON, re-invokes.

3.1's sole job: **expand the paper pool that 3.2 will search** with mechanism-specific recent retrieval that Phase 0's broad-domain queries miss. No classification step here — Phase 3.2 does substantive subsumption judgment over `lit_table.md ∪ collision_hits.json`.

#### Step 3.2 — Audit-and-Verdict (4 corpus-anchored checks)

Single LLM call. Use [references/system-prompts/critique.txt](references/system-prompts/critique.txt).

Phase 3.2 produces an audit report with four corpus-anchored checks. It does **NOT** auto-revise the candidate — when revision is needed, Phase 3.2 emits `revision_targets[]` and Phase 3.3 (separate LLM call) applies them. Audit and modification on different surfaces avoids self-answering bias.

**Precondition (deterministic, runs before the LLM call):** the `subpattern_citation_consistency` validator must pass on the Phase 2.2 candidate (see the Phase 2.2 citation gate). It confirms each `gap_closure[].sub_pattern` resolves to a real C## cluster under its cited `main_pattern` parent. It proves only parent-consistency, not that the cluster card was read — in this taxonomy the `sub_pattern` string carries the PARENT display name, so a clean citation cannot prove the C##.md card was opened. That harder question is `recipe_application_check` below.

The four checks each anchor on specific corpus content the LLM cannot fabricate:

| Step | Corpus anchor | Question |
|---|---|---|
| **1. gap_closure_reject_check** | each `gap_closure[]` entry's sub-pattern card (`ideation-sub-patterns/<C##>.md`, where `<C##>` is the leading cluster code of the entry's `sub_pattern` value `C## (parent pattern name)` — `## Tactical failure mode` + ALL bullets under `### Reject lessons`). Total reads = number of gap_closure entries (typically 1-3 cards). Other ~28 sub-pattern cards NOT loaded. | For each gap_closure entry, does the candidate fall into the Reject patterns documented in that sub-pattern card? Aggregate verdict is the worst across all entries. |
| **2. recipe_application_check** | each `gap_closure[]` entry's sub-pattern card `## Tactical pattern` (the cluster's signature move, NOT the parent's gist) + the candidate's `core_mechanism`. | Does `core_mechanism` actually perform the cited C## cluster's signature operation, or only the parent pattern's generic idea? `bypassed` when the distinctive move is absent — the leading cause of incremental output, and the one failure the deterministic citation guard cannot catch (the citation string only names the parent). |
| **3. anti_pattern_check** | `references/anti-patterns.md` — 3 reject-favored compositions with required mitigations | Detect via the SET of `gap_closure[].main_pattern` values. If composition matches an anti-pattern, is the mitigation **substantively delivered** in core_mechanism / theoretical_leg (not keyword-present)? |
| **4. paper_pointed_threat** | `lit_table.md ∪ collision_hits.json` (unified pool) | Most specific paper subsuming or competing with the candidate's claim. `no_threat_found` is a valid clearance signal — fabricating a generic threat is forbidden. |

(Earlier design had a check `almost_prior_factcheck`. Removed: low fire rate, redundant with paper_pointed_threat. A `saturation_defense_check` was also tried and removed: it was the one purely advisory check — soft signal only, never a hard floor, and unlike the four above it consulted no retrieved related work — so its concern now folds into Phase 4's `reviewer_concerns_and_responses` instead of gating Phase 3.2. Saturation metadata still flows: Phase 1 computes the band, Phase 2.1 records it, Phase 4 echoes it into `domain_landscape`. `recipe_application_check` is the newest — added because the deterministic citation guard can only prove parent-consistency, so a recipe built from the parent's gist while citing a real cluster passes the guard yet bypasses the cluster's actual tactic; this check is the semantic backstop.)

**Verdict is two-layer**: hard floor (mechanical, LLM cannot override) + soft judgment (LLM weighs within safe zone):

- **Layer 1 hard floor** — `abandon` if any of: gap_closure_reject_check=triggered (documented Reject pattern matches) / anti_pattern unmitigated-and-uninsertable / exact-mechanism collision. These are corpus-anchored facts; LLM has no override authority.
- **Layer 2 soft judgment** — when hard floor didn't fire, LLM picks `advance` or `revise` by weighing how severe each borderline/partial finding is. Trivial borderlines (non-load-bearing fields) → advance with concern surfaced for Phase 4 to fold into reviewer_concerns_and_responses. Borderlines hitting load-bearing structural properties (e.g., an ideation pattern's success condition) → revise with concrete revision_targets[]. `recipe_application_check = bypassed` → revise: either swap `sub_pattern` to the sibling whose tactical move core_mechanism actually performs, or rework core_mechanism to instantiate the cited move (if no sibling under the parent fits and core_mechanism cannot be reshaped to the cited move, the gap-level mismatch routes back to regenerate Phase 2.1+2.2 — Phase 3.3 cannot change the parent). LLM can also demote clear→revise if holistic reading reveals a concern individual checks missed.

The `verdict_rationale` must cite specific check findings (lesson_quoted / failure_mode_quoted / sub-block verdict). "All checks pass" without naming which is a process error.

Why two-layer: pure mechanical aggregation over-triggers revise (treats 1 trivial borderline same as 3 severe). Pure LLM verdict introduces agreeable-bias and loses audit trail. Hard floor preserves non-negotiable corpus facts; soft layer uses context to distinguish "must fix" from "noted concern, advance".

Routing on verdict:
- **advance** → Phase 4 reads Phase 2.2 candidate directly.
- **revise** → Phase 3.3 (single LLM call) emits the `applied_revisions[]` patch → orchestrator merger writes `final_candidate.json` → Phase 4 skeleton reads it.
- **abandon** → orchestrator emits `phase_3_failed.md` with verdict_rationale + triggering check. No automatic retry.

#### Step 3.3 — Apply Revision Targets (only when 3.2 verdict = revise)

Phase 3.3 is **patch-only**: one LLM call emits the `applied_revisions[]` patch list, then a deterministic Python merger (`scripts/merge_revisions.py`) applies the patch against the Phase 2.2 candidate and writes `final_candidate.json`. The LLM does NOT echo the full candidate back — previous versions of this contract did, and a single ~25k-token candidate echo caused a real backend inference timeout (the kill-switch fields, the largest, were re-typed verbatim).

LLM step: use [references/system-prompts/revise.txt](references/system-prompts/revise.txt). Reads Phase 2.2 candidate + Phase 3.2's revision_targets[]; emits one patch entry per revision_target. Does not re-judge the verdict, does not propose new attacks. The split (audit in 3.2, revise in 3.3, separate LLM calls) ensures the LLM that proposes attacks is not the LLM that answers them — eliminating self-answering bias.

Merger step (mandatory, runs immediately after the LLM call):

```bash
python3 "$SKILL_DIR/scripts/run.py" phase3_merge_revisions \
  --phase2 $RUN_DIR/phase2_generate/phase2_generate_output.json \
  --revisions $RUN_DIR/phase3_revise/phase3_revise_output.json \
  --out $RUN_DIR/phase3_revise/
```

The merger writes `phase3_revise/final_candidate.json` (Phase 4's canonical input) and back-injects `final_candidate` into the patch file so the `kill_switch_integrity` validator's existing chain-check still works without modification.

**Patch op vocabulary** (each `applied_revisions[]` entry uses one):
- `replace` — overwrite the field with `value` (full replacement; for a top-level string, a list, or a dict)
- `append_sentence` — append " " + `value` to an existing string field (preserves prior content; cheap)
- `append_items` — extend an existing list field with `value` (must itself be a list)
- `swap_sub_pattern` — for scope=sub_pattern: identify a gap_closure entry by `field` = the verbatim gap text, replace its `sub_pattern` with `value`; sibling `how_closed` / `core_mechanism` re-alignment is emitted as additional `replace` / `append_sentence` patch entries

**Output schema** (`$RUN_DIR/phase3_revise/phase3_revise_output.json`):
```json
{
  "candidate_id": "...",
  "applied_revisions": [
    {"scope": "tactical | sub_pattern",
     "op": "replace | append_sentence | append_items | swap_sub_pattern",
     "field": "<JSON-path for replace/append_*; verbatim gap text for swap_sub_pattern>",
     "value": "<new value for this field — NOT the full candidate>",
     "outcome": "applied | skipped_already_satisfied | skipped_anti_substitution | skipped_inapplicable",
     "delta_summary": "<one sentence>"}
  ]
}
```
The merger writes a `final_candidate` key back into this file after running.

**Two scopes** (`revision_targets[].scope`):
- `tactical` — modify named candidate fields (e.g., `core_mechanism`, `differentiation_from_lit[2].delta`); gap_closure[] unchanged.
- `sub_pattern` — swap one `gap_closure[i].sub_pattern` to a sibling under the same parent; re-emit `how_closed`; re-align `core_mechanism` only where the new sub-pattern's tactical_pattern makes the previous wording mechanism-misaligned.

**No `composition` scope.** If audit findings imply gap-level changes, the audit produces `verdict = abandon` and the user re-runs Phase 2.1+2.2 with a different random seed.

**Hard rules** (enforced structurally by the merger):
- Kill-switch fields (`falsification_prediction` + `compute_budget`) are STRUCTURALLY off-limits — the merger refuses any patch entry whose `field` root is one of these and raises with an actionable error. The anti-substitution contract is no longer "the LLM must remember not to drift" but "the LLM physically cannot write the field".
- One patch entry per revision_target (including skipped ones).
- Out-of-scope rewrites → `outcome = skipped_inapplicable`; gap-level changes route back to "regenerate Phase 2.1+2.2".

**Anti-substitution chain**: kill_switch_integrity validator handles both routings:
- 3.2=advance, no 3.3: Phase 2.2 → Phase 4 directly (Phase 3 passthrough)
- 3.2=revise, 3.3 ran: Phase 2.2 → Phase 3.3 final_candidate → Phase 4 (3-link chain). All three byte-identical for kill-switch fields.

---

### Phase 4 — Expansion + Packaging

Phase 4 runs in **three steps**: a deterministic skeleton builder (orchestrator), a small LLM fill call, and a deterministic assembler (orchestrator). This split exists because Phase 4's full expansion JSON has ~30 top-level fields and ~half of them are mechanical transforms — kill-switch echoes, venue_year lookups, group-bys over `lit_table.md`, joins of `gap_closure × pattern_saturation`, reviewer-concern lifts from the audit report. Asking the LLM to re-type those wastes tokens and risks a backend inference timeout (the same shape that broke Phase 3.3 before the patch-only redesign).

#### Step 4.skeleton — Build the deterministic skeleton (orchestrator)

```bash
python3 "$SKILL_DIR/scripts/run.py" phase4_skeleton \
  --candidate $RUN_DIR/phase3_revise/final_candidate.json \
  --phase1 $RUN_DIR/phase1/phase1_output.json \
  --phase2-select $RUN_DIR/phase2_select/phase2_select_output.json \
  --phase3-critique $RUN_DIR/phase3_critique/phase3_critique_output.json \
  --phase3-revise $RUN_DIR/phase3_revise/phase3_revise_output.json \
  --phase0-dir $RUN_DIR/phase0/ \
  --collision $RUN_DIR/phase3_collision/collision_hits.json \
  --out $RUN_DIR/phase4/
```

Pass `--candidate $RUN_DIR/phase2_generate/phase2_generate_output.json` on the advance path (Phase 3.3 did not run); omit `--phase3-revise` in that case.

The skeleton writes `phase4_skeleton.json` with every mechanical field fully populated and every prose field marked `<TODO[path]: hint>`. Mechanically populated fields:
- `falsification_prediction`, `compute_budget` (byte-identical from the candidate)
- `differentiation_from_lit` (enriched with `venue_year` per paper)
- `almost_prior_paper_id` + `almost_prior_venue_year`
- `motivation.why_prior_stopped[].paper_id` + `.venue_year` (one entry per closest_adjacent)
- `domain_landscape.pattern_distribution` (from Phase 1 `domain_pattern_distribution`)
- `domain_landscape.candidate_uses` (joined from `gap_closure[].main_pattern` × `pattern_saturation`)
- `literature_breakdown` (grouped from `lit_table.md`)
- `reviewer_concerns_and_responses[].attack` + `severity` + `fields_changed_to_address` (lifted from Phase 3.2 audit + Phase 3.3 patch's `applied_revisions[]`)
- `feasibility_validation.compute.{verdict, rationale}` (bucketed against `intake.compute`)

#### Step 4.fill — Author the prose (single LLM call)

Use [references/system-prompts/expand.txt](references/system-prompts/expand.txt). The LLM reads `phase4_skeleton.json`, finds every `<TODO[path]: hint>` placeholder, and outputs ONE flat JSON whose keys are the placeholder paths and whose values are the prose to substitute. The LLM does NOT touch any non-TODO field; the assembler refuses any fill_map key whose root is `falsification_prediction` or `compute_budget`.

Output path: `$RUN_DIR/phase4/fill_map.json`. Schema:
```json
{
  "abstract_draft": "...",
  "motivation.problem_framing": "...",
  "motivation.why_prior_stopped[0].what_they_did": "...",
  "method_flow.steps": [ {"step_id": "S1", "title": "...", ...}, ... ],
  "feasibility_validation.data.verdict": "feasible",
  ...
}
```

LLM payload drops from ~30 fields (~20k tokens) to ~12 prose-only fields (~8k tokens).

#### Step 4.assemble — Merge fill into expansion (orchestrator)

```bash
python3 "$SKILL_DIR/scripts/run.py" phase4_assemble \
  --skeleton $RUN_DIR/phase4/phase4_skeleton.json \
  --fill-map $RUN_DIR/phase4/fill_map.json \
  --out $RUN_DIR/phase4/
```

Produces `phase4_expansion.json` (the canonical input to `phase4_render`). The assembler validates: each fill_map path resolves to a real TODO in the skeleton; no fill_map path targets a kill-switch root. It warns when any `<TODO[...]>` placeholder remains un-filled — the `expansion_completeness` validator will reject the run otherwise.

**Anti-substitution is structural**, not enforced post-hoc: the skeleton populates kill-switch fields byte-identically from the candidate, the LLM never authors them, and the assembler refuses any attempt to overwrite them. `kill_switch_integrity` remains a belt-and-suspenders post-hoc validator.

**Echo vs reference policy**: anti-substitution-guarded fields (`falsification_prediction`, `compute_budget`, `differentiation_from_lit`, `almost_prior_paper_id`, `what_step_was_missed`) and structural lookups (venue_years, `domain_landscape`, `literature_breakdown`, `reviewer_concerns_and_responses.attack/severity/fields_changed`) are filled by the skeleton. `closest_adjacent` from Phase 1 and `lit_grounding_mode` from the Phase 0 sentinel are rendered directly by the card template; not duplicated into Phase 4 output.

**No calendar projections.** Sequencing in dependencies, not weeks. **No experiment matrix / ablation plan / baseline table / expected figures.** Skill produces IDEA + falsifiability + feasibility judgment; experimental engineering is the user's responsibility.

#### Step 4.1.5 — Implementability audit (default on)

Single LLM call, run by default after 4.1 and before 4.2. Use [references/system-prompts/implementability_audit.txt](references/system-prompts/implementability_audit.txt).

**Why this step exists.** Phase 4.1's `method_flow.steps[]` are often too terse to *understand* — a step names an operation ("extract premises", "score consensus", "train a critic") without the concrete object it runs on (the unit, the estimator, the output schema, how a quantity is computed), so the method "reads" but cannot be built from. This step adopts a fresh, skeptical implementing-engineer persona (a separate call from the 4.1 author — same anti-self-answering rationale as Phase 3.2's principle 7) and rewrites each step into a specification an engineer could code from, recording every hole it filled or left open.

**Compute-agnostic, by design.** When fleshing out a step this call MUST NOT consider compute / GPU-days / wall-clock / dataset cost — it assumes unlimited resources and specifies the full proper method, never truncating or cheapening a step to "fit". Resource feasibility is judged separately by 4.1's `feasibility_validation`; conflating the two would re-introduce exactly the hand-waving this step removes. A step that is expensive but fully specified is the correct output.

**Bounded contract.** Emits a SEPARATE file `phase4_implementability.json` — it never re-emits the expansion and structurally never carries the kill-switch fields (`falsification_prediction` / `compute_budget`). It produces `enriched_steps[]` (one per method step, same ids/order, each with a detailed `what_changes` + `what_to_do_en` + `what_to_do_zh`) and `underspecified_points[]` (`{step_id, hole, fill, severity}`, severity ∈ filled|open). It does NOT add, remove, or rename steps and stays faithful to `core_claim` / `sub_claims` — it specifies HOW to build the existing method, not a different one. Holes it cannot fill without fabricating are left honest as `severity: open` rather than papered over.

**How it reaches the cards.** Step 4.2 auto-detects the sibling `phase4_implementability.json` and merges `enriched_steps` into the rendered Method by `step_id` (replacing `method_flow.steps[].what_changes` for the pro card and `plain_method_steps_{en,zh}[].what_to_do` for the std cards). Everything else (titles, why_*, linked_*, equations, kill-switch fields) is untouched. The merge is deterministic and a no-op when the file is absent, so older runs still render. `underspecified_points[]` stays in JSON as the audit trail — the card itself stays lean (Title + Motivation + Method).

**Output path**: `$RUN_DIR/phase4/phase4_implementability.json`.

#### Step 4.2 — Idea-card rendering

Templating only, no model call. `render_pdf.py` builds the Markdown and LaTeX inline and compiles a PDF when `xelatex` or `tectonic` is available. Failure modes go to `phase_3_failed.md`.

```bash
python3 "$SKILL_DIR/scripts/run.py" phase4_render \
  --expansion $RUN_DIR/phase4/phase4_expansion.json \
  --out $RUN_DIR/phase4/
```

Each successful run writes **three audience-targeted markdown surfaces** plus per-card LaTeX side artifacts:
- `idea.std.zh.md` — **plain Chinese**, for the user's own quick read. Domain-newcomer register, no reviewer prose. (动机 + 方法步骤, from `plain_motivation_zh` + `plain_method_steps_zh`.)
- `idea.std.en.md` — **plain English**, same register, for international collaborators / drafting. (Motivation + Method, from `plain_motivation_en` + `plain_method_steps_en`.)
- `idea.detail.en.md` — **rigorous English**, the novelty + validity defense. Surfaces the heavyweight fields (motivation with why-prior-stopped, method flow with linked component/falsification, contributions, both legs, falsification prediction, closest prior, feasibility, differentiation, reviewer concerns) that otherwise live only in the `.tex`.
- `idea.std.{en,zh}.tex` — side artifacts, kept under the output dir; auto-compiled to `idea.std.{en,zh}.pdf` when a LaTeX engine (`xelatex`/`tectonic`) is on PATH, otherwise left for manual compilation.

The host LLM reads **all three markdown files** and returns them as the run's final response to the user, each under a clear heading (中文版 / English / Reviewer version). A PDF is compiled automatically when `xelatex` or `tectonic` is available (cross-platform TeX paths + an available CJK font are auto-detected); when no engine is present the `.md`/`.tex` are still written and only the PDF is skipped, with an install hint.

Other Phase outputs (`$RUN_DIR/phase0/`, `$RUN_DIR/phase1/`, `$RUN_DIR/phase2_*/`, `$RUN_DIR/phase3_*/`, `$RUN_DIR/phase4/phase4_expansion.json`) remain on disk for inspection but are not echoed to the user.

Failed runs write `do_not_generate.md` (Phase 1 OOD) or `phase_3_failed.md` (Phase 3 abandon) with concrete remedial steps; the host LLM surfaces those instead.

---

## Validators

Run after Phase 4 to verify the contracts the prompts assert:

```bash
# When Phase 3.2 verdict = advance (no Phase 3.3 ran)
python3 "$SKILL_DIR/scripts/run.py" validate \
  --phase2 $RUN_DIR/phase2_generate/phase2_generate_output.json \
  --phase3 $RUN_DIR/phase3_critique/phase3_critique_output.json \
  --phase4 $RUN_DIR/phase4/phase4_expansion.json \
  --phase4-impl $RUN_DIR/phase4/phase4_implementability.json

# When Phase 3.2 verdict = revise (Phase 3.3 produced final_candidate)
python3 "$SKILL_DIR/scripts/run.py" validate \
  --phase2 $RUN_DIR/phase2_generate/phase2_generate_output.json \
  --phase3 $RUN_DIR/phase3_revise/phase3_revise_output.json \
  --phase4 $RUN_DIR/phase4/phase4_expansion.json \
  --phase4-impl $RUN_DIR/phase4/phase4_implementability.json
```

(`--phase4-impl` is optional; supply it to enable `implementability_completeness`. Omit it for runs that skipped Step 4.1.5.)

**Retry budget on `fail` (cap = 2).** On a hard `fail`, fix only the named contract in the relevant Phase 4 JSON and re-run `validate`. Cap this fix→re-validate loop at **2 retries** (3 `validate` runs total, including the first). If validators still report `fail` after the 2nd retry, **stop revising** and finalize with the current best version: run Step 4.2 render (`phase4_render`) on the JSON as-is, return the cards, and append a short note listing the still-failing validators so the unmet contract is visible to the user. A flagged-imperfect card beats looping until the host watchdog kills the run with zero output. (Exception: never "fix" `kill_switch_integrity` or `subpattern_citation_consistency` by editing a guarded field — if those persist after 2 retries, surface them as the headline caveat rather than papering over them.)

| Validator | Check | Severity |
|---|---|---|
| **subpattern_citation_consistency** | each `gap_closure[].sub_pattern` resolves to a real C## cluster in `overview.md` whose true parent == the cited `main_pattern`, and whose cited parenthetical == that cluster's parent display name. Runs whenever `--phase2` is given. **Primary use is the Phase 2.2 citation gate (run before Phase 3); re-runs harmlessly here.** Catches citations guessed from the parent's name instead of read from overview.md. | fail (hard) |
| **kill_switch_integrity** | `falsification_prediction` (single paragraph) and `compute_budget` (flat string) byte-identical Phase 2.2 → Phase 4 (Phase 3.2 passthrough on advance path) or Phase 2.2 → Phase 3.3 final_candidate → Phase 4 (revise path). 2 fields total. | fail (hard) |
| **expansion_completeness** | Phase 4 expansion has the structural sections downstream rendering needs: motivation (with ≥ 2 `why_prior_stopped` entries), `method_flow.steps[]` (each with `linked_component` + `linked_falsification`), `feasibility_validation` (5 sub-verdicts + `overall`), non-empty `abstract_draft` + `core_claim` + `sub_claims[]`. | fail (hard — missing sections would silently render as blank content in the markdown / LaTeX output, so the validator blocks rather than warns) |
| **implementability_completeness** | Phase 4.1.5 audit covers every method step: `enriched_steps[]` is one-per-step (same ids, same order) each with `what_changes` + `what_to_do_en` + `what_to_do_zh`; `underspecified_points[]` present (`[]` allowed); and the file carries NO kill-switch field. Runs only when `--phase4-impl` is given. | fail (hard — a coverage gap ships a half-enriched method; a kill-switch field signals the audit overstepped) |
| **implementability_readability** | Phase 4.1.5 std-register fields (`what_to_do_en` / `what_to_do_zh`) avoid the known readability regressions from audit Hard rule 8: no `占位`/`placeholder` leak (the std card never shows the value it stands in for), no bare English jargon word (`entail`…) dropped into Chinese prose. Runs only when `--phase4-impl` is given. | warn (style/clarity — surfaces a Hard-rule-8 slip in the report without blocking ship) |

---

## Configuration

By default every model-driven phase runs on the host LLM (whatever launched the skill). To route specific phases to a different backend (Gemini, open-weights, custom), set the corresponding env var:

- `NOVELTY_LLM_REASONING_LARGE_CMD` — used for Phase 1 / 2.1 / 2.2 / 3.2 / 3.3 / 4.1 (needs ≥ 200k context, JSON output)
- `NOVELTY_LLM_CLASSIFY_FAST_CMD` — used for Phase 0 intent extraction + per-paper pattern tagging (smaller context, JSON output)

Each value is a CLI command that takes a stdin prompt (`<<SYSTEM>>...<<USER>>...` format) and emits JSON on stdout. When unset (default for Claude Code), the orchestrator emits sentinel files and the host LLM handles those steps natively.
