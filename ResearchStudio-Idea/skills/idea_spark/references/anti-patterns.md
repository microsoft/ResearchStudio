# Anti-patterns — reject-favored compositions to guard against

This file is a **guard, not a ban**. The 1,891-paper multi-label tagging surfaces three 2-way pattern compositions whose Oral rate $p_O = n_O / (n_O + n_R)$ is at least 12 percentage points below the dataset baseline ($p_O = 58.4\%$). They are not forbidden — sometimes a problem genuinely calls for one — but Phase 3.2's `anti_pattern_check` audit must explicitly verify the documented failure mode is mitigated before such a composition advances.

This is the **only place the historical acceptance prior enters the design**. The prior is used as a structural risk signal at audit time, not as a generation guidance.

## The three reject-favored 2-way compositions

Selection criterion: $n_O + n_R \geq 30$ AND $\Delta p_O \leq -12\,\text{pp}$ (i.e. $p_O \leq 46.4\%$). Three compositions clear the bar; **all three involve `heterogeneous_decomposition`** as one component — the empirical signal is that pairing "decompose heterogeneity for differentiated treatment" with another constructive move stacks two ad-hoc choices that have to mutually justify each other.

| Composition | $n_O$ | $n_R$ | $p_O$ | $\Delta p_O$ | Failure mode | Required mitigation if used |
|---|---|---|---|---|---|---|
| `heterogeneous_decomposition` + `self_supervised_signal_engineering` (`audit_decomp_supervisor`) | 17 | 36 | 32.1% | −26.3 | "We made up the groups AND made up the labels." Decomposing into sub-populations is one un-derived choice; manufacturing supervision for each sub-population is a second un-derived choice; the paper is reviewed as two stacked heuristics, neither of which is testable independently of the other. By a wide margin the dataset's strongest reject signal. | The decomposition criterion must be derivable from observed structure or task-level supervision (not just intuition), AND the manufactured signal must be the *unique* signal the decomposition implies. An ablation that holds the decomposition fixed and varies the signal (or vice versa) must show the two are not conflated. |
| `heterogeneous_decomposition` + `structural_prior_encoding` (`audit_decomp_prior`) | 42 | 51 | 45.2% | −13.2 | "The prior masks the decomposition, or the decomposition masks the prior — which is doing the work?" Encoding a structural prior on top of a heterogeneous-decomposition pipeline asks the prior to handle both the homogeneous core and the inter-group differences; reviewers cannot tell which axis carries the contribution. The highest-volume reject-favored combination in the corpus ($n_{O+R} = 93$). | An ablation that turns off either the decomposition or the prior in isolation must show a clear differential effect (not just a smaller combined number). Theoretically, the prior must encode a property the decomposition does not already imply — otherwise the two are doing the same job. |
| `architectural_operator_substitution` + `heterogeneous_decomposition` (`audit_decomp_operator`) | 18 | 21 | 46.2% | −12.2 | "The operator IS the architecture." Substituting a more expressive operator and asking it to handle multi-population heterogeneity stacks two distinct tradeoffs in one design choice — the operator's inductive bias is being asked to deliver both the homogeneous-data gain and the cross-group differentiation. Reviewers consistently say the contribution is over-attributed to a single change. | The operator's expressivity gain must be demonstrated on homogeneous data (where decomposition is unnecessary), and the decomposition's separate effect must be demonstrated on heterogeneous data with the operator held fixed. Each leg's contribution must be independently identifiable. |

## How Phase 3.2 audit uses this

Phase 3.2's `anti_pattern_check`:
1. Takes `composition_set` = the set of `main_pattern` values across the candidate's `gap_closure[]` entries.
2. Tests each 2-way subset against the 3 documented compositions in the table above.
3. If a subset matches: emit `matched_pattern_id` (`audit_decomp_supervisor` | `audit_decomp_prior` | `audit_decomp_operator`) and the corresponding `required_mitigation`, then judge whether the candidate's `core_mechanism` (and supporting fields like `theoretical_leg` / `engineering_leg`) substantively delivers the mitigation — `mitigation_substantively_delivered: true | false`.
4. If matched AND not delivered AND mitigation cannot be inserted by Phase 3.3 revision → hard-floor `verdict = abandon`. Otherwise the candidate may advance with the mitigation surfaced in `reviewer_concerns_and_responses`.

The mitigation must be **visible in the candidate's `core_mechanism`** at the artifact level, not merely claimed in the framing — keyword presence is not delivery.

## What this is not

- **Not a ban.** The data shows these compositions Oral 32–46% of the time; they can succeed. The prior here is a risk weight, not a verdict.
- **Not a generation incentive.** Phase 2 selection never proposes a composition because of its acceptance prior. The prior is consulted only after the candidate is generated, by Phase 3.2 audit, to check for the documented failure mode.
- **Not the only source of reviewer risk.** Phase 3.2's `gap_closure_reject_check` checks per-cluster (sub-pattern) reject lessons. Anti-patterns are a level above: composition-level failure modes that aren't visible in any single sub-pattern card.
- **Not exhaustive.** Five additional combinations at $-11\,\text{pp} \leq \Delta p_O \leq -8\,\text{pp}$ are mildly reject-favored; they are watch-list candidates but the empirical signal is weaker than the three flagged above. Notably, `heterogeneous_decomposition + reframe_as_solvable_object` ($p_O = 47.4\%$, $n = 95$) just misses the threshold and may warrant inclusion as the corpus grows.
