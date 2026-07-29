"""Structured validation for Paper2Video's PPT-Master audit.

PPT-Master may phrase an automatically resolved direction differently in its
receipt, design specification, and execution lock. The validator therefore
checks concrete locked fields and semantic agreement instead of requiring one
generated sentence to be copied verbatim between artifacts.
"""

from __future__ import annotations

import re
import shlex
import unicodedata
from collections.abc import Sequence


_AUDIENCE_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "for",
        "following",
        "of",
        "the",
        "to",
        "work",
    }
)
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_SPEC_LOCK_COLOR_KEYS = {
    # PPT-Master spec-lock/v1 uses bg/text. The longer names are accepted for
    # historical Paper2Video projects and older confirmation-UI receipts. A
    # few generated locks used ``body`` in the colors section (mirroring the
    # typography size key); it is unambiguous there, so retain it as a narrow
    # compatibility alias while requiring new locks to emit ``body_text``.
    "background": ("bg", "background"),
    "primary": ("primary",),
    "accent": ("accent",),
    "body_text": ("text", "body_text", "body"),
}


def spec_lock_value(lock_text: str, section: str, key: str) -> str:
    """Read one scalar from PPT-Master's markdown execution lock."""
    section_match = re.search(
        rf"(?ms)^##\s+{re.escape(section)}\s*$\n(.*?)(?=^##\s+|\Z)",
        lock_text,
    )
    if not section_match:
        return ""
    row = re.search(
        rf"(?m)^-\s+{re.escape(key)}:\s*(.+?)\s*$",
        section_match.group(1),
    )
    return row.group(1).strip().strip("\"'") if row else ""


def design_table_value(design_text: str, item: str) -> str:
    """Read a two-column value from a markdown table in design_spec.md."""
    wanted = _normalize_text(item)
    for line in design_text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [
            cell.strip().strip("*`")
            for cell in line.strip().strip("|").split("|")
        ]
        if len(cells) >= 2 and _normalize_text(cells[0]) == wanted:
            return cells[1].strip()
    return ""


def _spec_lock_alias_value(
    lock_text: str,
    section: str,
    semantic_role: str,
    keys: Sequence[str],
) -> str:
    """Resolve one schema role without silently accepting conflicting aliases."""
    found = [
        (key, spec_lock_value(lock_text, section, key))
        for key in keys
    ]
    found = [(key, value) for key, value in found if value]
    if not found:
        return ""
    distinct = {value.casefold() for _, value in found}
    if len(distinct) != 1:
        detail = ", ".join(f"{key}={value}" for key, value in found)
        raise RuntimeError(
            "PPT-Master spec_lock.md has conflicting aliases for "
            f"{semantic_role}: {detail}"
        )
    return found[0][1]


def _normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def _audience_tokens(value: str) -> set[str]:
    tokens = set(_normalize_text(value).split()) - _AUDIENCE_STOP_WORDS
    if "ml" in tokens:
        tokens.update({"machine", "learning"})
    if "ai" in tokens:
        tokens.update({"artificial", "intelligence"})
    return tokens


def _material_audience_overlap(left: str, right: str) -> bool:
    left_tokens = _audience_tokens(left)
    right_tokens = _audience_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = left_tokens & right_tokens
    return len(overlap) >= min(2, len(left_tokens), len(right_tokens))


def _contains_normalized(haystack: str, needle: str) -> bool:
    normalized_needle = _normalize_text(needle)
    return bool(normalized_needle) and normalized_needle in _normalize_text(haystack)


def _positive_number(value: str) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def audit_descriptive_options(
    applied: dict,
    opts: dict,
    lock_text: str,
    design_text: str,
) -> None:
    """Verify audience, typography, and color against executable PPT locks.

    Explicit choices must be copied exactly into the applied-options receipt
    and be recorded in the generated design/lock. Auto choices may be worded
    differently, but must resolve to mutually consistent structured values in
    both design_spec.md and spec_lock.md.
    """
    requested_audience = str(opts.get("ppt_audience") or "").strip()
    applied_audience = str(applied.get("target_audience") or "").strip()
    locked_audience = spec_lock_value(lock_text, "communication", "audience")
    designed_audience = design_table_value(design_text, "Target Audience")
    if not applied_audience:
        raise RuntimeError("PPT-Master did not resolve a target audience")
    if not locked_audience or not designed_audience:
        raise RuntimeError(
            "PPT-Master audience is missing from spec_lock.md or design_spec.md"
        )
    if requested_audience:
        if applied_audience != requested_audience:
            raise RuntimeError("PPT-Master target audience does not match the request")
        if not (
            _contains_normalized(locked_audience, requested_audience)
            or _contains_normalized(designed_audience, requested_audience)
        ):
            raise RuntimeError(
                "PPT-Master did not record the requested target audience in its design lock"
            )
    elif not (
        _material_audience_overlap(applied_audience, locked_audience)
        and _material_audience_overlap(locked_audience, designed_audience)
    ):
        raise RuntimeError(
            "PPT-Master Auto target audience is inconsistent across its receipt and design lock"
        )

    requested_typography = str(opts.get("ppt_typography") or "").strip()
    applied_typography = str(applied.get("typography_direction") or "").strip()
    font_family = spec_lock_value(lock_text, "typography", "font_family")
    body_size = spec_lock_value(lock_text, "typography", "body")
    title_size = spec_lock_value(lock_text, "typography", "title")
    if not applied_typography:
        raise RuntimeError("PPT-Master did not resolve a typography direction")
    if not font_family or not _positive_number(body_size) or not _positive_number(title_size):
        raise RuntimeError(
            "PPT-Master spec_lock.md is missing executable typography values"
        )
    primary_font = font_family.split(",", 1)[0].strip().strip("\"'")
    if not _contains_normalized(design_text, primary_font):
        raise RuntimeError(
            "PPT-Master design_spec.md does not match the font in spec_lock.md"
        )
    if requested_typography:
        if applied_typography != requested_typography:
            raise RuntimeError(
                "PPT-Master typography direction does not match the request"
            )
        if not _contains_normalized(design_text, requested_typography):
            raise RuntimeError(
                "PPT-Master did not record the requested typography direction in design_spec.md"
            )
    elif not _contains_normalized(applied_typography, primary_font):
        raise RuntimeError(
            "PPT-Master Auto typography receipt does not match the font locked in its design"
        )

    requested_color = str(opts.get("ppt_color") or "").strip()
    applied_color = str(applied.get("color_direction") or "").strip()
    locked_colors = {
        role: _spec_lock_alias_value(
            lock_text,
            "colors",
            role,
            keys,
        )
        for role, keys in _SPEC_LOCK_COLOR_KEYS.items()
    }
    if not applied_color:
        raise RuntimeError("PPT-Master did not resolve a color direction")
    invalid_color_roles = [
        role
        for role, value in locked_colors.items()
        if not _HEX_COLOR.fullmatch(value)
    ]
    if invalid_color_roles:
        raise RuntimeError(
            "PPT-Master spec_lock.md is missing or has invalid executable HEX "
            "color roles: " + ", ".join(invalid_color_roles)
        )
    missing_design_colors = [
        value
        for value in locked_colors.values()
        if value.casefold() not in design_text.casefold()
    ]
    if missing_design_colors:
        raise RuntimeError(
            "PPT-Master design_spec.md does not match the colors in spec_lock.md"
        )
    if requested_color:
        if applied_color != requested_color:
            raise RuntimeError("PPT-Master color direction does not match the request")
        if not _contains_normalized(design_text, requested_color):
            raise RuntimeError(
                "PPT-Master did not record the requested color direction in design_spec.md"
            )
    else:
        receipt_color_count = sum(
            value.casefold() in applied_color.casefold()
            for value in locked_colors.values()
        )
        if receipt_color_count < 2:
            raise RuntimeError(
                "PPT-Master Auto color receipt does not describe the palette locked in its design"
            )


def normalize_export_flag_tokens(
    raw: str | Sequence[object] | None,
) -> list[str]:
    """Normalize either grouped or tokenized JSON export flags."""
    if isinstance(raw, str):
        chunks = [raw]
    elif isinstance(raw, Sequence):
        chunks = [str(item).strip() for item in raw if str(item).strip()]
    else:
        return []

    tokens: list[str] = []
    try:
        for chunk in chunks:
            tokens.extend(shlex.split(chunk))
    except ValueError:
        return []
    return tokens


def audit_export_flags(applied_raw: object, expected_flags: Sequence[str]) -> None:
    """Require the exact svg_to_pptx options, independent of JSON grouping."""
    applied_tokens = normalize_export_flag_tokens(applied_raw)  # type: ignore[arg-type]
    expected_tokens = normalize_export_flag_tokens(expected_flags)
    if applied_tokens != expected_tokens:
        raise RuntimeError(
            f"PPT-Master export flags mismatch: expected {list(expected_flags)}, "
            f"got {applied_tokens}"
        )
