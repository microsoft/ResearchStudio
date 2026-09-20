"""Validator: the plain motivation opens on a claim, not a definition.

`derive_plain.txt` writes the plain register for a reader outside the subfield and spells
out every abbreviation on first use. Followed literally, that puts a definition in sentence
one — "Super-resolution means turning a small, blurry photo into ..." — and the gap the card
exists to state arrives a paragraph later. A reviewer reads the first sentence for the
claim; a definition there reads as a textbook, and the card is judged before its point.

The prompt now says: first sentence is a claim, definitions from sentence two. This check
flags the definition shapes that actually occurred in rendered cards. `warn`: an opener
can be a legitimate scene-setting sentence, and a heuristic on one sentence cannot tell
those apart with certainty.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Shapes taken from rendered cards, not invented: "X means ...", "X is a/an <thing that> ...",
# "X (ABBR — systems that ...)", "X speeds up/lets/enables ... by ...".
_DEFINITION = [
    re.compile(r'\bmeans\b'),
    re.compile(r'^(?:A |An |The |Modern |Current )?[^.]{2,80}?\b(?:is|are) (?:a|an|the)? ?'
               r'(?:[a-z-]+ )?(?:system|model|technique|method|agent|network|approach|process|'
               r'procedure|framework|setting|task|problem)s?\b(?: that| which| where| whose)', re.I),
    re.compile(r'\([A-Z][A-Za-z0-9-]{1,12}s? — '),
    re.compile(r'\b(?:speeds up|lets|allows|enables|makes it possible for)\b[^.]{0,120}\bby '
               r'(?:having|letting|using|running|asking)\b', re.I),
]


def _first_sentence(text: str) -> str:
    text = text.strip()
    # Sentence end: period/?/! followed by space+capital, or end of text. Skip abbreviations
    # like "e.g." and decimals by requiring the following char to be a capital letter.
    m = re.search(r'[.!?](?=\s+[A-Z"\'(])', text)
    return text[: m.end()] if m else text[:300]


def validate_motivation_opener(phase4_path: str) -> list[dict]:
    findings: list[dict] = []
    try:
        doc = json.loads(Path(phase4_path).read_text())
    except Exception:
        return findings
    mot = doc.get('plain_motivation_en') if isinstance(doc, dict) else None
    if not isinstance(mot, str) or not mot.strip():
        return findings
    first = _first_sentence(mot)
    hit = next((p for p in _DEFINITION if p.search(first)), None)
    if hit:
        findings.append({
            'validator': 'motivation_opener', 'severity': 'warn',
            'message': (f'plain_motivation_en opens on a definition, not a claim: '
                        f'"{first[:140]}". The first sentence should state what is wrong, missing '
                        f'or assumed; move the gloss to sentence two (see derive_plain.txt, '
                        f'THE FIRST SENTENCE IS A CLAIM).')})
    else:
        findings.append({'validator': 'motivation_opener', 'severity': 'pass',
                         'message': 'plain_motivation_en opens on a claim.'})
    return findings
