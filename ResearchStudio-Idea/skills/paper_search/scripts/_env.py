"""Lightweight .env loader for the paper_search scripts.

Why: the source connectors read credentials via os.environ (e.g. OPENREVIEW_USER/PASS).
When these scripts are invoked directly by an LLM through bash, the shell has NOT sourced
any .env, so those vars are empty and the credentialed sources silently degrade. This module
walks up from the script directory to find a .env and loads it into os.environ BEFORE the
connectors run — no external dependency (not python-dotenv), shell-set vars take precedence.

Search order (first match wins):
  1. .env in any ancestor directory of this script (scripts/ -> paper_search/ -> skills/ -> repo root)
  2. any skills/<name>/.env under the repo root (keys currently live in skills/ResearchStudio-Idea/.env)
"""
from __future__ import annotations
import os
from pathlib import Path

_loaded = False


def _apply(env_path: Path) -> None:
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            # setdefault: a value already exported in the real shell wins over the .env file.
            os.environ.setdefault(key, val)


def load_env_once() -> Path | None:
    """Load the first .env found (see module docstring). Idempotent. Returns the path used."""
    global _loaded
    if _loaded:
        return None
    _loaded = True

    here = Path(__file__).resolve()
    candidates: list[Path] = []
    repo_root: Path | None = None
    for parent in here.parents:
        candidates.append(parent / ".env")
        if (parent / ".git").exists():
            repo_root = parent
            break
    if repo_root is not None:
        candidates += sorted(repo_root.glob("skills/*/.env"))

    for cand in candidates:
        try:
            if cand.is_file():
                _apply(cand)
                return cand
        except OSError:
            continue
    return None
