"""
NoveltySkill literature-search module.

Provides Phase 1.5 Recent Literature Grounding for any LLM backend.
Auto-detects which LLM SDK is available via env vars, and uses that for
per-paper innovation-lens classification (C00-C17).

Usage:
    from lit_search import search_recent_literature
    result = search_recent_literature("your topic", months_back=24, top_k=15)
    # result["papers"], result["lens_distribution"], result["warning"]
"""

from .literature_search import search_recent_literature
from .backends import detect_backend, call_llm_json
from .clusters import CLUSTER_NAMES, CLUSTER_TO_META

__all__ = [
    "search_recent_literature",
    "detect_backend",
    "call_llm_json",
    "CLUSTER_NAMES",
    "CLUSTER_TO_META",
]
