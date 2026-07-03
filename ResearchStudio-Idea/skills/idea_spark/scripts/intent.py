"""Extract search queries (map mode) or signature terms (collision mode) from user input.

Why: every downstream connector needs cleaned, focused queries; LLMs do this much better
than rule-based keyword extraction.

Capability profile: [CLASSIFY_FAST] — single shot, JSON output, 8k context plenty.

I/O:
  python3 -m scripts.intent --mode map     --input '{...}'   --out queries.json
  python3 -m scripts.intent --mode collision --input '{...}' --out signature.json
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / 'references' / 'intent-recognition.md'

MAP_SYSTEM = """You read a user's research question and extract 4-6 search queries to send to academic search APIs.

Return JSON: {"queries": ["...", "..."], "domain_hints": ["..."], "venue_hints": ["..."]}

Rules:
- Query 1: BROAD-DOMAIN (3-5 words).
- Query 2: METHOD-SIGNATURE (5-8 words).
- Query 3: MOST-SIMILAR-PROBLEM (5-8 words).
- Query 4: ESCAPE-MECHANISM (4-7 words) — the vocabulary a paper that ALREADY fixed this bottleneck would title itself with. A solver paper names itself by its solution (e.g. "empirical Bayes shrinkage baseline"), not by the problem, so queries 1-3 (all problem-keyed) miss exactly the closest prior work that scoops you. Reason about 1-2 plausible solution families and phrase this query in SOLUTION vocabulary. Do not skip it.
- Query 5 (optional): APPLICATION-ANGLE (3-5 words).
- Query 6 (optional): VENUE-INSIDER (5-8 words).

domain_hints: 1-3 lowercase tags. venue_hints: 0-3 venue names if mentioned.
No quotes around words, no boolean operators."""

COLLISION_SYSTEM = """You read a candidate research idea and extract 3-5 signature terms for phrase matching.

Return JSON: {"signature_terms": ["...", "..."]}

Rules:
- Each term is 3-7 words.
- Cover (a) mechanism, (b) claim, (c) setting; plus 1-2 specific identifiers.
- Avoid generic terms.
- Prefer noun phrases."""


def call_llm(system: str, user: str) -> dict:
    """Call the configured [CLASSIFY_FAST] backend.

    The skill resolves which backend via config.yaml. By default this falls through
    to the host LLM that launched the skill (in Claude Code, that means the running
    Claude session reads the prompt and produces JSON; the script merely formats
    the prompt and parses the JSON when it comes back via stdout).

    For non-host-LLM deployments (e.g., the skill is being run as a Python library
    by an external orchestrator), set NOVELTY_LLM_CLASSIFY_FAST_CMD in env to a
    shell command that takes stdin (system + user prompt) and returns JSON on stdout.
    """
    cmd = os.environ.get('NOVELTY_LLM_CLASSIFY_FAST_CMD')
    if cmd:
        import subprocess
        full_input = f'<<SYSTEM>>\n{system}\n<<USER>>\n{user}'
        r = subprocess.run(cmd, input=full_input, shell=True, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f'classify_fast call failed: {r.stderr[:200]}')
        return json.loads(r.stdout)
    # Host-LLM mode: write the prompt to a sentinel file the host LLM is expected to
    # read and respond to inline. This is the default Claude Code behavior.
    raise RuntimeError(
        'NOVELTY_LLM_CLASSIFY_FAST_CMD not set. In Claude Code, the host LLM '
        'reads the prompt and returns JSON inline. For batch/library mode set the env var.'
    )


def map_mode(user_input: dict) -> dict:
    user = json.dumps(user_input, ensure_ascii=False, indent=1)
    return call_llm(MAP_SYSTEM, user)


def collision_mode(user_input: dict) -> dict:
    user = json.dumps(user_input, ensure_ascii=False, indent=1)
    return call_llm(COLLISION_SYSTEM, user)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode', choices=['map', 'collision'], required=True)
    ap.add_argument('--input', required=True, help='JSON string with the user input')
    ap.add_argument('--out', required=True, help='output JSON path')
    args = ap.parse_args()

    user = json.loads(args.input)
    out = map_mode(user) if args.mode == 'map' else collision_mode(user)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f'wrote {args.out}', file=sys.stderr)


if __name__ == '__main__':
    main()
