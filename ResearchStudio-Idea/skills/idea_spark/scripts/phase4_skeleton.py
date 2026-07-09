"""phase4_skeleton: build the deterministic Phase 4 expansion skeleton.

Why this script exists:
  Phase 4's single LLM call used to produce ~30 top-level fields, of which
  ~half are mechanical transforms (kill-switch echo, venue-year lookup,
  group-by over lit_table, candidate_uses derived from gap_closure × pattern
  saturation, reviewer_concerns_and_responses lifted from the audit report).
  Asking the model to re-type those wastes tokens and risks a backend
  inference timeout.

  This script does the mechanical half deterministically. It writes
  `phase4_skeleton.json` where every mechanical field is fully populated and
  every prose field is a `<TODO[path]: ...>` placeholder. The host LLM then
  authors only the prose, emitting a flat fill_map `{path: value}` that
  `phase4_assemble` merges back into the skeleton.

  The result: LLM payload drops from ~30 fields of mixed mechanical+prose to
  ~12 prose-only fields. Anti-substitution becomes structural — the model
  physically does not see the kill-switch fields' current values during
  authoring, so it cannot drift them.

Inputs (all paths resolved against the user's run dir, not the skill dir):
  - candidate.json     (Phase 2.2 candidate or Phase 3.3 final_candidate)
  - phase1_output.json
  - phase2_select_output.json
  - phase3_critique_output.json
  - phase3_revise_output.json   (optional; present only if Phase 3.3 ran)
  - phase0_dir/                  (containing lit_table.md, lit_results.json)
  - collision_hits.json          (optional; Phase 3.1 retrieval)

Output:
  - phase4_skeleton.json
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# TODO placeholder helper
# ---------------------------------------------------------------------------

def TODO(path: str, hint: str = '') -> str:
    """Render a deterministic TODO marker. The host LLM scans for this exact
    prefix to know which fields it must author. The path is informational —
    the LLM's fill_map output uses the same path syntax.

    Format: `<TODO[path]: hint>`
    """
    if hint:
        return f'<TODO[{path}]: {hint}>'
    return f'<TODO[{path}]>'


# ---------------------------------------------------------------------------
# lit_table.md parser — handle the 9-column markdown table the host LLM writes
# ---------------------------------------------------------------------------

# columns expected (from pattern-summary-rubric.md):
# | paper_id | year_month | venue | title | ideation pattern tags |
# | bottleneck this paper targets | open issue / unresolved gap |
# | resolves_problem | retrieved_via |
LIT_TABLE_COLUMNS = [
    'paper_id', 'year_month', 'venue', 'title', 'ideation_pattern_tags',
    'bottleneck_targeted', 'open_issue', 'resolves_problem', 'retrieved_via',
]


def parse_lit_table(path: Path) -> list[dict]:
    """Tolerant markdown-table parser. Returns one dict per data row.

    Skips:
      - the header row (`| paper_id | ... |`)
      - the separator row (`|---|---|...`)
      - blank / non-pipe lines

    A row with fewer cells than columns gets empty strings for the missing
    tail; a row with more cells gets the extras concatenated into the LAST
    expected column (the open-issue text often contains pipes from naive LLM
    quoting). This is the empirically-observed failure mode.
    """
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line.startswith('|') or not line.endswith('|'):
            continue
        # Skip separator
        if re.match(r'^\|[\s\-:|]+\|$', line):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        # Skip header (paper_id literal)
        if cells and cells[0].lower() in ('paper_id', '**paper_id**'):
            continue
        # Pad or trim
        if len(cells) < len(LIT_TABLE_COLUMNS):
            cells = cells + [''] * (len(LIT_TABLE_COLUMNS) - len(cells))
        elif len(cells) > len(LIT_TABLE_COLUMNS):
            # Concatenate overflow into the LAST column position before retrieved_via
            # (retrieved_via is always one short token; the bleed is in earlier cells)
            keep = cells[:len(LIT_TABLE_COLUMNS) - 2]
            bleed = ' | '.join(cells[len(LIT_TABLE_COLUMNS) - 2:-1])
            keep.append(bleed)
            keep.append(cells[-1])
            cells = keep
        row = dict(zip(LIT_TABLE_COLUMNS, cells))
        # Split semicolon-separated ideation pattern tags into a list
        tags = row.get('ideation_pattern_tags', '')
        row['ideation_pattern_tags_list'] = [t.strip() for t in tags.split(';') if t.strip()]
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Venue+year formatting — normalize the heterogeneous venue field across sources
# ---------------------------------------------------------------------------

def fmt_venue_year(venue: str, year_month: str | None = None,
                   year: int | None = None) -> str:
    """Render a uniform `venue + year` token for the idea-card.

    Heuristics (in priority order):
      1. OpenReview entries: `ICML.cc/2026/Conference` → `ICML 2026 (in review)`
      2. arXiv: `arXiv.org` / `ArXiv.org` / empty venue but arxiv_id present → `arXiv YYYY-MM`
      3. Standard conference: `International Conference on …` → keep as-is, append year
      4. Journal: use venue verbatim + year
      5. Unknown: fall back to year_month or year string
    """
    v = (venue or '').strip()
    ym = (year_month or '').strip()
    yr = str(year) if year else (ym.split('-')[0] if ym else '')

    # OpenReview venue strings: `ICML.cc/2026/Conference`, `ICLR.cc/2025/Conference`
    m = re.match(r'^(\w+)\.cc/(\d{4})/Conference$', v)
    if m:
        return f'{m.group(1)} {m.group(2)} (in review)'

    # arXiv-shaped venues
    if v.lower() in ('arxiv', 'arxiv.org'):
        return f'arXiv {ym}' if ym else f'arXiv {yr}'.strip()

    if not v:
        return f'arXiv {ym}' if ym else (yr or 'unknown')

    # Default: venue + year
    return f'{v} {yr}'.strip()


def build_venue_year_lookup(lit_results: list[dict]) -> dict[str, str]:
    """paper_id → venue_year string, for cheap lookup in motivation /
    differentiation_from_lit / literature_breakdown."""
    lut = {}
    for p in lit_results or []:
        pid = p.get('paper_id') or p.get('id')
        if not pid:
            continue
        lut[pid] = fmt_venue_year(p.get('venue', ''), p.get('year_month'), p.get('year'))
    return lut


# ---------------------------------------------------------------------------
# Compute-budget feasibility — bucket against the 90 A100-day default
# ---------------------------------------------------------------------------

_NUM = re.compile(r'(\d+(?:\.\d+)?)')


def _extract_a100_days(s: str) -> float | None:
    """Greedy parse: find the first `<num> A100-day` / `<num> GPU-day` /
    `<num> H100-day` token. Returns the number as a float A100-day-equivalent
    (H100 counted as 2× A100). Returns None if no number is found near a
    compute-day unit."""
    if not s:
        return None
    pattern = re.compile(r'(\d+(?:\.\d+)?)\s*(A100|H100|GPU)[-\s]?day', re.IGNORECASE)
    m = pattern.search(s)
    if not m:
        # Fallback: just the first number, treated as A100-day
        m2 = _NUM.search(s)
        return float(m2.group(1)) if m2 else None
    n = float(m.group(1))
    unit = m.group(2).upper()
    if unit == 'H100':
        n *= 2.0  # rough heuristic; the verdict bucketing is coarse enough that this is fine
    return n


def compute_verdict_from_budget(compute_budget: str, intake_compute: str) -> tuple[str, str]:
    """Return (verdict, rationale).

    Default intake is `1×A100 × 3 months ≈ 90 A100-day`. Verdict thresholds:
      - feasible: budget ≤ 50% of intake
      - tight:    50% < budget ≤ 100%
      - infeasible: budget > 100%
    """
    DEFAULT_A100_DAY = 90.0
    budget_n = _extract_a100_days(compute_budget)
    intake_n = _extract_a100_days(intake_compute) or DEFAULT_A100_DAY

    if budget_n is None:
        return ('tight', f'Could not parse a numeric A100-day budget from compute_budget; '
                         f'manual review against intake.compute ({intake_compute or "default 90 A100-day"}) required.')

    ratio = budget_n / intake_n
    if ratio <= 0.5:
        verdict = 'feasible'
    elif ratio <= 1.0:
        verdict = 'tight'
    else:
        verdict = 'infeasible'
    return (verdict, f'Budget ≈ {budget_n:g} A100-day vs intake.compute ≈ {intake_n:g} A100-day '
                     f'({ratio*100:.0f}% of envelope) → {verdict}.')


# ---------------------------------------------------------------------------
# Domain landscape — derived from phase1 + phase2_select + gap_closure
# ---------------------------------------------------------------------------

def build_domain_landscape(phase1: dict, gap_closure: list[dict],
                           pattern_saturation: dict) -> dict:
    """Phase 4's `domain_landscape` field. All sub-fields except
    `position_note` are mechanical. position_note is a one-sentence prose
    summary the LLM authors."""
    dpd = phase1.get('domain_pattern_distribution') or {}
    pattern_distribution = []
    for entry in dpd.get('patterns', []):
        pattern_distribution.append({
            'pattern_id': entry.get('pattern_id'),
            'count': entry.get('count'),
            'share': entry.get('share'),
            'saturation_band': entry.get('saturation_band'),
        })

    candidate_uses = []
    for i, g in enumerate(gap_closure or []):
        main_pat = g.get('main_pattern')
        sat = (pattern_saturation or {}).get(main_pat) or {}
        candidate_uses.append({
            'pattern_id': main_pat,
            'role': f'closes Gap {i + 1}',
            'sub_pattern_id': g.get('sub_pattern'),
            'saturation_in_domain': sat.get('saturation_band', 'unknown'),
        })

    return {
        'n_papers': dpd.get('n_on_topic'),
        'pattern_distribution': pattern_distribution,
        'candidate_uses': candidate_uses,
        'position_note': TODO('domain_landscape.position_note',
                              'one sentence describing how the candidate\'s chosen patterns sit relative to the area\'s pattern usage; '
                              'descriptive, not prescriptive'),
    }


# ---------------------------------------------------------------------------
# Literature breakdown — group lit_table by ideation pattern
# ---------------------------------------------------------------------------

# Plain-language names for the 15 ideation patterns (mirrors overview.md).
PATTERN_DISPLAY_NAMES = {
    'assumption_audit_and_pivot': 'Audit and Pivot an Assumption',
    'architectural_operator_substitution': 'Substitute the Operator or Representation',
    'generative_process_redesign': 'Liberate a Fixed Generative Component',
    'controlled_diagnostic_design': 'Design a Confound-Isolating Diagnostic',
    'unify_into_shared_representation': 'Unify Heterogeneous Inputs into One Space',
    'reframe_as_solvable_object': 'Reframe as a Solvable Object',
    'self_supervised_signal_engineering': 'Manufacture the Supervisory Signal',
    'structural_prior_encoding': 'Encode Structure by Construction',
    'algebraic_equivalence_unification': 'Prove Equivalence to Unify',
    'heterogeneous_decomposition': 'Decompose for Differentiated Treatment',
    'decompose_and_delegate': 'Decompose and Delegate to Solvers',
    'relax_discrete_search_to_continuous': 'Relax Discrete Search to Continuous',
    'adapt_via_conditioning': 'Adapt by Conditioning, Not Retraining',
    'characterize_limit_then_surpass': 'Characterize a Limit, Then Surpass It',
    'targeted_self_supervised_objective': 'Design a Property-Targeting Pretext Objective',
}


def build_literature_breakdown(lit_table_rows: list[dict],
                                venue_lut: dict[str, str],
                                collision_hits: list[dict]) -> dict:
    """Group lit_table rows by PRIMARY ideation pattern (first tag in the row).
    Outside-taxonomy rows go to a dedicated bucket. Phase 3.1 collision hits
    render as a flat list."""
    by_pattern: dict[str, list[dict]] = {}
    outside_taxonomy: list[dict] = []

    for row in lit_table_rows or []:
        tags = row.get('ideation_pattern_tags_list') or []
        primary = (tags[0] if tags else 'outside_taxonomy').strip()
        venue_year = venue_lut.get(row['paper_id']) or fmt_venue_year(row.get('venue', ''),
                                                                       row.get('year_month'))
        entry = {
            'paper_id': row.get('paper_id'),
            'title': row.get('title'),
            'venue_year': venue_year,
            'bottleneck_targeted': (row.get('bottleneck_targeted') or '')[:160],
        }
        if primary == 'outside_taxonomy':
            outside_taxonomy.append(entry)
        else:
            by_pattern.setdefault(primary, []).append(entry)

    phase0_by_pattern = []
    # Stable order: sort by pattern_id (alphabetic). Counts visible to the reader.
    for pat_id in sorted(by_pattern.keys()):
        phase0_by_pattern.append({
            'pattern_id': pat_id,
            'pattern_name': PATTERN_DISPLAY_NAMES.get(pat_id, pat_id),
            'papers': by_pattern[pat_id],
        })

    phase3_collision = []
    for p in collision_hits or []:
        ym = p.get('year_month') or p.get('published_iso', '')[:7]
        venue_year = fmt_venue_year(p.get('venue', ''), ym, p.get('year'))
        phase3_collision.append({
            'paper_id': p.get('paper_id'),
            'title': p.get('title'),
            'venue_year': venue_year,
        })

    n_on_topic = sum(len(b['papers']) for b in phase0_by_pattern)
    n_outside = len(outside_taxonomy)

    return {
        'summary': {
            'n_phase0_total': n_on_topic + n_outside,
            'n_phase0_on_topic': n_on_topic,
            'n_phase0_outside_taxonomy': n_outside,
            'n_phase3_collision': len(phase3_collision),
        },
        'phase0_by_pattern': phase0_by_pattern,
        'phase0_outside_taxonomy': outside_taxonomy,
        'phase3_collision': phase3_collision,
    }


# ---------------------------------------------------------------------------
# Reviewer concerns + responses — lift the mechanical structure from Phase 3.2 + 3.3
# ---------------------------------------------------------------------------

def build_reviewer_concerns(phase3_critique: dict,
                            phase3_revise: dict | None) -> list[dict]:
    """Derive one entry per concern surfaced by Phase 3.2 audit. The `attack`
    + `severity` + `fields_changed_to_address` are mechanical; the `response`
    is the prose the LLM authors."""
    entries = []

    # 1. paper_pointed_threat
    ppt = phase3_critique.get('paper_pointed_threat') or {}
    if ppt.get('threat_paper_id') and ppt.get('threat_paper_id') != 'no_threat_found':
        sev = 'blocking' if (ppt.get('addressable_via') is None) else 'non_blocking'
        entries.append({
            'attack': (f"Paper-pointed threat: {ppt.get('threat_paper_id')} "
                       f"({ppt.get('threat_source')}). {ppt.get('subsumption_argument') or ''}"),
            'severity': sev,
            'response': TODO('reviewer_concerns_and_responses[0].response',
                             '2-3 sentences: explain where in the candidate (which field) the defense is anchored; '
                             'reference the Phase 3.2 verdict_rationale when relevant'),
            'fields_changed_to_address': [],  # filled below from phase3_revise.applied_revisions[]
        })

    # 1b. paper_pointed_threat.parametric_family_concern — the audit's soft signal
    # that an older, named mechanism family exists outside the retrieved pool.
    # Never gates the verdict; here it becomes an explicit "run a scoop-check on
    # this vocabulary before investing" reviewer concern so the card carries the
    # known blind spot instead of silently claiming full novelty coverage.
    pfc = ppt.get('parametric_family_concern')
    if pfc and isinstance(pfc, str) and pfc.strip().lower() not in ('null', 'none', 'n/a'):
        entries.append({
            'attack': (f"Un-retrieved mechanism family flagged by the audit (parametric "
                       f"knowledge, not in the retrieved pool): {pfc.strip()} — novelty vs "
                       f"this family is UNVERIFIED; run a targeted scoop-check on that "
                       f"vocabulary before investing."),
            'severity': 'non_blocking',
            'response': TODO(f'reviewer_concerns_and_responses[{len(entries)}].response',
                             '1-2 sentences: state what a scoop-check on the named family must '
                             'establish for the candidate\'s delta to survive (do NOT claim the '
                             'check already passed)'),
            'fields_changed_to_address': [],
        })

    # 2. gap_closure_reject_check borderline entries
    gcrc = phase3_critique.get('gap_closure_reject_check') or {}
    for j, entry in enumerate(gcrc.get('entries', [])):
        if (entry or {}).get('verdict') == 'borderline':
            # Find the borderline lessons that fired
            triggered = [r for r in entry.get('reject_lessons_evaluated', [])
                         if r.get('candidate_match') == 'borderline']
            lesson_text = '; '.join(r.get('lesson_quoted', '')[:200] for r in triggered) or \
                          'borderline reject-lesson match (see Phase 3.2 audit for the specific lesson_quoted).'
            entries.append({
                'attack': f"Gap-closure reject-check borderline on gap {j+1} ({entry.get('sub_pattern')}): {lesson_text}",
                'severity': 'non_blocking',
                'response': TODO(f'reviewer_concerns_and_responses[{len(entries)}].response',
                                 '2-3 sentences: anchor the defense in a specific candidate field'),
                'fields_changed_to_address': [],
            })

    # 3. anti_pattern_check
    apc = phase3_critique.get('anti_pattern_check') or {}
    if apc.get('matched_pattern_id'):
        sev = 'non_blocking' if apc.get('mitigation_substantively_delivered') in (True, 'true') else 'blocking'
        entries.append({
            'attack': (f"Anti-pattern matched: {apc.get('matched_pattern_id')}. "
                       f"Required mitigation: {apc.get('required_mitigation_quoted', '')}"),
            'severity': sev,
            'response': TODO(f'reviewer_concerns_and_responses[{len(entries)}].response',
                             '2-3 sentences: name how the candidate\'s core_mechanism delivers the mitigation'),
            'fields_changed_to_address': [],
        })

    # If no audit-driven concern fired, surface a single TODO for the strongest anticipated question
    if not entries:
        entries.append({
            'attack': TODO('reviewer_concerns_and_responses[0].attack',
                           'one paragraph: the strongest anticipated reviewer question (paper-pointed when possible)'),
            'severity': 'non_blocking',
            'response': TODO('reviewer_concerns_and_responses[0].response',
                             '2-3 sentences: anchor the defense in a specific candidate field'),
            'fields_changed_to_address': [],
        })

    # Now backfill fields_changed_to_address from phase3_revise.applied_revisions[]
    applied = (phase3_revise or {}).get('applied_revisions') or []
    changed = []
    for r in applied:
        if (r.get('outcome') or '').startswith('skipped_'):
            continue
        f = r.get('field')
        if f:
            changed.append(f)
    # Apply the same list to every entry (the audit produces one revise-set per audit run)
    for e in entries:
        e['fields_changed_to_address'] = list(changed)

    return entries


# ---------------------------------------------------------------------------
# differentiation_from_lit — enrich with venue_year per paper
# ---------------------------------------------------------------------------

def enrich_differentiation(candidate_diff: list[dict],
                           venue_lut: dict[str, str]) -> list[dict]:
    out = []
    for d in candidate_diff or []:
        pid = d.get('paper_id')
        venue_year = venue_lut.get(pid, '')
        out.append({
            'paper_id': pid,
            'venue_year': venue_year,
            'delta': d.get('delta'),
        })
    return out


# ---------------------------------------------------------------------------
# motivation.why_prior_stopped[] — one entry per closest_adjacent, mechanical
# scaffolding + prose TODOs
# ---------------------------------------------------------------------------

def build_why_prior_stopped(closest_adjacent: list[dict],
                            venue_lut: dict[str, str]) -> list[dict]:
    out = []
    for i, ca in enumerate(closest_adjacent or []):
        pid = ca.get('paper_id')
        out.append({
            'paper_id': pid,
            'venue_year': venue_lut.get(pid, TODO(f'motivation.why_prior_stopped[{i}].venue_year',
                                                  'venue + year for this paper_id (not in lit_results lookup)')),
            'what_they_did': TODO(f'motivation.why_prior_stopped[{i}].what_they_did',
                                  'one sentence'),
            'what_they_did_not_do': TODO(f'motivation.why_prior_stopped[{i}].what_they_did_not_do',
                                          'one sentence — the specific limit being lifted by the candidate'),
            'structural_reason_they_stopped': TODO(
                f'motivation.why_prior_stopped[{i}].structural_reason_they_stopped',
                'one sentence — missing tool / missing assumption-relaxation / missing mechanism / missing measurement'),
        })
    return out


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_skeleton(candidate: dict, phase1: dict, phase2_select: dict,
                   phase3_critique: dict, phase3_revise: dict | None,
                   lit_table_rows: list[dict], lit_results: list[dict],
                   collision_hits: list[dict]) -> dict:
    venue_lut = build_venue_year_lookup(lit_results)
    intake_compute = (phase1.get('intake') or {}).get('compute', '')

    # Compute-budget verdict is fully deterministic; LLM authors only the rationale
    # if it wants to override the auto-generated one (otherwise the auto-text stays)
    compute_verdict, compute_rationale = compute_verdict_from_budget(
        candidate.get('compute_budget', ''), intake_compute)

    almost_prior_pid = candidate.get('almost_prior_paper_id')
    almost_prior_vy = venue_lut.get(almost_prior_pid, '') if almost_prior_pid else ''

    skeleton = {
        # Top-level mechanical echoes
        'title': candidate.get('title', TODO('title', 'final paper title')),
        'title_zh': TODO('title_zh', 'Chinese translation; keep proper nouns and method acronyms in English'),
        'method_name': TODO('method_name',
                            "short handle for the proposed method, e.g. 'Persistent Baseline GRPO (PB-GRPO)'"),
        'hook': candidate.get('hook', TODO('hook', 'echoed from candidate, possibly tightened')),
        'abstract_draft': TODO('abstract_draft',
                               '150-250 words. Order: problem → bottleneck (cite ≥ 1 Phase 0 paper) → '
                               'contribution (one sentence) → falsification prediction → expected outcome.'),

        # Motivation — structure mechanical, prose TODO
        'motivation': {
            'problem_framing': TODO('motivation.problem_framing',
                                    '2-3 paragraphs framing the user\'s problem. Reference the bottleneck_statement '
                                    'from Phase 1 and the closest_adjacent papers. NOT a category label.'),
            'why_now': TODO('motivation.why_now',
                            'one paragraph on what makes this gap timely. Cite the most recent Phase 0 papers '
                            '(within last 4-12 months) that get close but stop short.'),
            'why_prior_stopped': build_why_prior_stopped(
                phase1.get('closest_adjacent') or [], venue_lut),
            'what_changes_when_gap_closes': TODO('motivation.what_changes_when_gap_closes',
                                                  '2-3 sentences naming downstream consequences. NOT "better numbers" — '
                                                  'name the specific capability or theoretical statement that becomes available'),
        },

        # Claims — prose TODO
        'core_claim': TODO('core_claim',
                           'one sentence; should mirror the candidate\'s hook stripped to its load-bearing assertion'),
        'sub_claims': TODO('sub_claims',
                           'list of {id, statement, supports_which_aspect}; 2-4 entries'),

        # Equations — optional; LLM emits empty list or 3-6 entries
        'key_equations': TODO('key_equations',
                              'optional 3-6 equations; each {id, linked_step_id, latex, description, description_zh}. '
                              'Emit [] (literal empty list) for a pure-prose candidate.'),

        # Method flow — prose TODO; the LLM derives from candidate.core_mechanism_steps
        'method_flow': {
            'high_level_pipeline': TODO('method_flow.high_level_pipeline',
                                         '3-5 sentences narrating the method end-to-end as a story: '
                                         'input → key transformation → output'),
            'steps': TODO('method_flow.steps',
                          'derive from candidate.core_mechanism_steps; emit a list where each entry is '
                          '{step_id, title, what_changes, why_this_step, linked_component, linked_falsification, input, output}. '
                          'Each step_id MUST be S1, S2, ... in reading order. linked_component ∈ {theory, engineering, both}; '
                          'linked_falsification ∈ {metric_specification, mechanism_distinguisher, both}.'),
            'design_reasoning_echo': TODO('method_flow.design_reasoning_echo',
                                          'one paragraph echoing or condensing candidate.core_mechanism_reasoning'),
        },

        # Plain renderings — prose TODO; LLM authors per the schema
        'plain_motivation_en': TODO('plain_motivation_en',
                                    'plain-language English rendering of motivation for a reader outside this subfield. '
                                    'Simplify LANGUAGE only — never drop the load-bearing mechanism. '
                                    'Spell out every abbreviation on first use.'),
        'plain_motivation_zh': TODO('plain_motivation_zh',
                                    'Chinese 普通版 counterpart. Same content; keep identifiers/symbols/acronyms in English.'),
        'plain_method_steps_en': TODO('plain_method_steps_en',
                                       'list of {step_id, what_to_do, why_this_makes_sense}; '
                                       'SAME step_ids and SAME order as method_flow.steps.'),
        'plain_method_steps_zh': TODO('plain_method_steps_zh',
                                       'Chinese 普通版 counterpart; English for identifiers/symbols/acronyms.'),
        'plain_method_modules_en': TODO('plain_method_modules_en',
                                         'group the CONTRIBUTION steps into named modules; '
                                         'list of {module_id, purpose_oneline, step_ids}.'),
        'plain_method_modules_zh': TODO('plain_method_modules_zh',
                                         'Chinese 普通版 counterpart.'),

        # KILL-SWITCH echoes — DETERMINISTIC, byte-identical to candidate
        'falsification_prediction': candidate.get('falsification_prediction', ''),
        'compute_budget': candidate.get('compute_budget', ''),

        # Almost-prior — mechanical echo + venue_year lookup
        'almost_prior_paper_id': almost_prior_pid,
        'almost_prior_venue_year': almost_prior_vy,
        'what_step_was_missed': candidate.get('what_step_was_missed', ''),

        # Feasibility validation — compute verdict deterministic; others prose
        'feasibility_validation': {
            'compute': {
                'verdict': compute_verdict,
                'rationale': compute_rationale,
            },
            'data': {
                'verdict': TODO('feasibility_validation.data.verdict', 'feasible | tight | infeasible'),
                'rationale': TODO('feasibility_validation.data.rationale',
                                  'one sentence: required data sources accessible; if any closed/private, name a public substitute'),
            },
            'theoretical': {
                'verdict': TODO('feasibility_validation.theoretical.verdict',
                                'feasible | tight | infeasible | n/a (only when the candidate has no theoretical contribution)'),
                'rationale': TODO('feasibility_validation.theoretical.rationale',
                                  'one sentence; if tight, name the missing prerequisite'),
            },
            'engineering': {
                'verdict': TODO('feasibility_validation.engineering.verdict',
                                'feasible | tight | infeasible | n/a (only when the candidate has no engineering contribution)'),
                'rationale': TODO('feasibility_validation.engineering.rationale',
                                  'one sentence; if tight, name the binding implementation cost'),
            },
            'falsification': {
                'verdict': TODO('feasibility_validation.falsification.verdict', 'feasible | tight | infeasible'),
                'rationale': TODO('feasibility_validation.falsification.rationale',
                                  'one sentence: the falsification_prediction experiment is concrete enough to run with available tooling'),
            },
            'overall': TODO('feasibility_validation.overall', 'feasible | tight | infeasible'),
        },

        # Differentiation_from_lit — enriched with venue_year, deltas verbatim
        'differentiation_from_lit': enrich_differentiation(
            candidate.get('differentiation_from_lit') or [], venue_lut),

        # Reviewer concerns — attack mechanical from audit; response prose TODO
        'reviewer_concerns_and_responses': build_reviewer_concerns(phase3_critique, phase3_revise),

        # Domain landscape — derived; position_note prose
        'domain_landscape': build_domain_landscape(
            phase1, candidate.get('gap_closure') or [],
            phase2_select.get('pattern_saturation') or {}),

        # Literature breakdown — fully mechanical
        'literature_breakdown': build_literature_breakdown(
            lit_table_rows, venue_lut, collision_hits),
    }

    return skeleton


# ---------------------------------------------------------------------------
# Assembler (Phase 4 step 4.assemble): merge a flat fill_map into the skeleton
# ---------------------------------------------------------------------------

def assemble_expansion(skeleton: dict, fill_map: dict) -> dict:
    """Apply the LLM-authored fill_map to the skeleton. Each key in fill_map
    is a field path (same syntax as merge_revisions: dotted + bracketed).
    Each value REPLACES the TODO placeholder at that path.

    Refuses any fill_map key whose ROOT is a kill-switch field. The skeleton
    already populated those byte-identically from the candidate; the LLM is
    not allowed to overwrite them.
    """
    from scripts.merge_revisions import _apply_replace, KILL_SWITCH_FIELDS, _parse_field_path
    import copy
    out = copy.deepcopy(skeleton)

    for path, value in (fill_map or {}).items():
        root = path.split('.', 1)[0].split('[', 1)[0]
        if root in KILL_SWITCH_FIELDS:
            raise ValueError(f'fill_map key {path!r} targets kill-switch root {root!r}; refused.')
        try:
            _apply_replace(out, path, value)
        except ValueError as e:
            raise ValueError(f'fill_map[{path!r}]: {e}') from None

    return out
