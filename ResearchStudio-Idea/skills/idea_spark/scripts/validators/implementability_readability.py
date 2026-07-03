"""implementability_readability validator: catch the std-register (普通版) readability regressions that
the Phase 4.1.5 audit's Hard rule 8 forbids, on the fields a practitioner outside the subfield reads
(`enriched_steps[].what_to_do_en` / `what_to_do_zh`).

The audit prompt prevents these at generation time; this validator is the mechanical backstop so a slip is
surfaced before ship. It only flags the unambiguous, near-zero-false-positive classes — readability as a
whole cannot be machine-judged, so the absence of findings is NOT a guarantee of good prose, only that these
specific known failure modes are absent.

Checks (warn severity — these are style/clarity, not contract-integrity, so they surface loudly in the
validate report without brittle-blocking ship):
  1. PLACEHOLDER LEAK — the word "占位" / "placeholder" appears in a std field. The std card never shows the
     value it would stand in for (that lives in the pro `what_changes`), so calling something a placeholder
     there is a dangling reference (Hard rule 8c).
  2. BARE ENGLISH JARGON IN CHINESE — a known jargon WORD that has a plain Chinese term is dropped untranslated
     into what_to_do_zh, e.g. "entail"/"contest"/"endorse" instead of 蕴含/反对/支持 (Hard rule 8b). Identifiers,
     acronyms, symbols, file/tool/dataset names are intentionally English and are NOT on this denylist.

Severity: warn.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

# Jargon words that must be rendered in Chinese in what_to_do_zh (denylist, not allowlist — keeps false
# positives near zero). Only pure jargon verbs/nouns that are NEVER used as formal identifiers in this
# method family belong here: "entail" is loose NLI vocabulary (the equation uses NLI / NLI⁻, never "entail").
# Words like endorse / contest are deliberately EXCLUDED — they double as the PCS equation's component
# identifiers endorse(p) / contest(p), so flagging them would false-positive on a legitimate symbol reference.
ZH_JARGON_DENYLIST = ["entail", "entails", "entailment"]
PLACEHOLDER_TERMS = ["占位", "placeholder"]


def validate_implementability_readability(phase4_impl_path: str) -> list[dict]:
    findings = []
    impl = json.loads(Path(phase4_impl_path).read_text())
    enriched = impl.get("enriched_steps") or []

    for e in enriched:
        if not isinstance(e, dict):
            continue
        sid = e.get("step_id", "?")
        zh = str(e.get("what_to_do_zh", "") or "")
        en = str(e.get("what_to_do_en", "") or "")

        # 1. placeholder leak in either std field
        for field, text in (("what_to_do_zh", zh), ("what_to_do_en", en)):
            for term in PLACEHOLDER_TERMS:
                if term.lower() in text.lower():
                    findings.append({
                        "severity": "warn", "validator": "implementability_readability",
                        "message": f"step {sid} {field} contains '{term}' — the std card does not show the "
                                   f"value it stands in for; state the quantity in plain words instead "
                                   f"(Hard rule 8c).",
                    })

        # 2. bare English jargon word in Chinese std field
        for w in ZH_JARGON_DENYLIST:
            if re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", zh, re.IGNORECASE):
                findings.append({
                    "severity": "warn", "validator": "implementability_readability",
                    "message": f"step {sid} what_to_do_zh drops bare English jargon '{w}' into Chinese prose; "
                               f"use a plain Chinese term (蕴含/支持/反对) instead (Hard rule 8b).",
                })

    if not findings:
        findings.append({
            "severity": "pass", "validator": "implementability_readability",
            "message": "No placeholder leaks or bare-jargon regressions in the std-register audit fields.",
        })
    return findings
