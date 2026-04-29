"""
Unified LLM backend dispatcher.

Auto-detects which provider to use for the lens-classification LLM call,
based on (in priority order):
  1. NOVELTY_LLM_BACKEND env var  (explicit override)
  2. OPENAI_API_KEY   -> "openai"
  3. ANTHROPIC_API_KEY -> "anthropic"
  4. GOOGLE_API_KEY   -> "gemini"
  5. Ollama reachable at OLLAMA_URL (default http://localhost:11434)
  6. None (caller gets primary_lens=None for all papers)

Supported backends: "openai", "anthropic", "gemini", "ollama", "none".

All backends share one interface:
    call_llm_json(prompt: str, max_tokens: int = 200) -> dict | None
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional


# ----------------------------- detection ------------------------------------

def _ollama_alive(url: str) -> bool:
    try:
        import urllib.request
        req = urllib.request.Request(f"{url.rstrip('/')}/api/tags")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def detect_backend() -> str:
    """Pick the first available LLM backend; return 'none' if nothing is configured."""
    explicit = os.getenv("NOVELTY_LLM_BACKEND", "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    if _ollama_alive(os.getenv("OLLAMA_URL", "http://localhost:11434")):
        return "ollama"
    return "none"


# ----------------------------- JSON parsing ---------------------------------

def _extract_json(text: str) -> Optional[dict]:
    """Pull the first JSON object out of an LLM response, tolerating code fences."""
    if not text:
        return None
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if m:
        blob = m.group(1)
    else:
        m2 = re.search(r"\{.*\}", text, flags=re.DOTALL)
        blob = m2.group(0) if m2 else text
    try:
        return json.loads(blob)
    except Exception:
        return None


# ----------------------------- backends -------------------------------------

def _call_openai(prompt: str, max_tokens: int) -> Optional[dict]:
    from openai import OpenAI
    client = OpenAI()
    model = os.getenv("NOVELTY_OPENAI_MODEL", "gpt-4o-mini")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return _extract_json(resp.choices[0].message.content or "")


def _call_anthropic(prompt: str, max_tokens: int) -> Optional[dict]:
    import anthropic
    client = anthropic.Anthropic()
    model = os.getenv("NOVELTY_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(
        getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"
    )
    return _extract_json(text)


def _call_gemini(prompt: str, max_tokens: int) -> Optional[dict]:
    from google import genai
    from google.genai import types as gtypes
    client = genai.Client()
    model = os.getenv("NOVELTY_GEMINI_MODEL", "gemini-2.5-flash")
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=gtypes.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
        ),
    )
    return _extract_json(resp.text or "")


def _call_ollama(prompt: str, max_tokens: int) -> Optional[dict]:
    import urllib.request
    url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/chat"
    model = os.getenv("NOVELTY_OLLAMA_MODEL", "qwen2.5:7b")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, "num_predict": max_tokens},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return _extract_json(data.get("message", {}).get("content", ""))


_DISPATCH = {
    "openai": _call_openai,
    "anthropic": _call_anthropic,
    "gemini": _call_gemini,
    "ollama": _call_ollama,
}


def call_llm_json(prompt: str, max_tokens: int = 200, backend: Optional[str] = None) -> Optional[dict]:
    """Route a JSON-output LLM call to the configured backend."""
    backend = (backend or detect_backend()).lower()
    if backend == "none":
        return None
    fn = _DISPATCH.get(backend)
    if fn is None:
        raise ValueError(f"Unknown backend: {backend!r}. Expected one of {list(_DISPATCH)} or 'none'.")
    return fn(prompt, max_tokens)
