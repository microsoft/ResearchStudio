"""Canonical Paper2Video and PPT-Master option contract.

Descriptive fields such as audience, color, and typography remain bounded
strings because PPT-Master intentionally generates those from the paper;
every enumerable field is closed over the catalog below.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping


CATALOG_VERSION = "paper2video-ppt-options.v1"

PPT_OPTIONS_PUBLIC_CATALOG = {
    "narrative_modes": (
        {"id": "auto", "label": "Auto · recommended"},
        {"id": "pyramid", "label": "Pyramid"},
        {"id": "narrative", "label": "Narrative"},
        {"id": "instructional", "label": "Instructional"},
        {"id": "showcase", "label": "Showcase"},
        {"id": "briefing", "label": "Briefing"},
    ),
    "visual_style_groups": (
        {
            "label": "Corporate / product",
            "options": (
                {"id": "swiss-minimal", "label": "Swiss minimal"},
                {"id": "soft-rounded", "label": "Soft rounded"},
                {"id": "glassmorphism", "label": "Glassmorphism"},
                {"id": "dark-tech", "label": "Dark tech"},
                {"id": "blueprint", "label": "Blueprint"},
            ),
        },
        {
            "label": "Editorial / data",
            "options": (
                {"id": "editorial", "label": "Editorial"},
                {"id": "photo-editorial", "label": "Photo editorial"},
                {"id": "data-journalism", "label": "Data journalism"},
            ),
        },
        {
            "label": "Expressive",
            "options": (
                {"id": "brutalist", "label": "Brutalist"},
                {"id": "memphis", "label": "Memphis"},
                {"id": "zine", "label": "Zine"},
                {"id": "vintage-poster", "label": "Vintage poster"},
                {"id": "paper-cut", "label": "Paper cut"},
                {"id": "sketch-notes", "label": "Sketch notes"},
                {"id": "ink-notes", "label": "Ink notes"},
                {"id": "chalkboard", "label": "Chalkboard"},
                {"id": "ink-wash", "label": "Ink wash"},
                {"id": "pixel-art", "label": "Pixel art"},
            ),
        },
    ),
    "image_sources": (
        {"id": "auto", "label": "Auto"},
        {"id": "ai", "label": "AI-generated", "requires_image_api": True},
        {"id": "web", "label": "Web-sourced"},
        {"id": "provided", "label": "Paper / provided"},
        {"id": "placeholder", "label": "Placeholder"},
        {"id": "none", "label": "No images"},
    ),
    "formula_policies": (
        {"id": "mixed", "label": "Mixed · complex formulas rendered"},
        {"id": "render-all", "label": "Render all formulas"},
        {"id": "text-only", "label": "Editable text only"},
    ),
    "delivery_purposes": (
        {"id": "text", "label": "Read-close"},
        {"id": "balanced", "label": "Balanced"},
        {"id": "presentation", "label": "Presentation"},
    ),
    "icon_libraries": (
        {"id": "auto", "label": "Auto"},
        {"id": "chunk-filled", "label": "Chunk filled"},
        {"id": "tabler-filled", "label": "Tabler filled"},
        {"id": "tabler-outline", "label": "Tabler outline"},
        {"id": "phosphor-duotone", "label": "Phosphor duotone"},
        {"id": "emoji", "label": "Emoji"},
        {"id": "none", "label": "No icons"},
    ),
    "image_ai_paths": (
        {"id": "auto", "label": "Auto"},
        {"id": "api", "label": "Configured API"},
        {"id": "host-native", "label": "Host-native"},
        {"id": "manual", "label": "Manual"},
    ),
    "transitions": tuple(
        {"id": value, "label": value}
        for value in (
            "fade",
            "push",
            "wipe",
            "split",
            "strips",
            "cover",
            "random",
            "none",
        )
    ),
    "animations": tuple(
        {"id": value, "label": value}
        for value in (
            "none",
            "auto",
            "mixed",
            "random",
            "appear",
            "fade",
            "fly",
            "cut",
            "zoom",
            "wipe",
            "split",
            "blinds",
            "checkerboard",
            "dissolve",
            "random_bars",
            "peek",
            "wheel",
            "box",
            "circle",
            "diamond",
            "plus",
            "strips",
            "wedge",
            "stretch",
            "expand",
            "swivel",
        )
    ),
    "animation_triggers": tuple(
        {"id": value, "label": value}
        for value in ("on-click", "with-previous", "after-previous")
    ),
}


def _ids(name: str) -> tuple[str, ...]:
    return tuple(str(option["id"]) for option in PPT_OPTIONS_PUBLIC_CATALOG[name])


PPT_MASTER_MODES = _ids("narrative_modes")
PPT_MASTER_VISUAL_STYLES = (
    "auto",
    *tuple(
        str(option["id"])
        for group in PPT_OPTIONS_PUBLIC_CATALOG["visual_style_groups"]
        for option in group["options"]
    ),
)
PPT_MASTER_DELIVERY_PURPOSES = _ids("delivery_purposes")
PPT_MASTER_ICONS = _ids("icon_libraries")
PPT_MASTER_IMAGE_USAGE = _ids("image_sources")
PPT_MASTER_IMAGE_AI_PATHS = _ids("image_ai_paths")
PPT_MASTER_FORMULA_POLICIES = _ids("formula_policies")
PPT_MASTER_TRANSITIONS = _ids("transitions")
PPT_MASTER_ANIMATIONS = _ids("animations")
PPT_MASTER_ANIMATION_TRIGGERS = _ids("animation_triggers")

_CONCRETE_MODES = tuple(value for value in PPT_MASTER_MODES if value != "auto")
_CONCRETE_VISUAL_STYLES = tuple(
    value for value in PPT_MASTER_VISUAL_STYLES if value != "auto"
)
_CONCRETE_ICONS = tuple(value for value in PPT_MASTER_ICONS if value != "auto")
_CONCRETE_IMAGE_USAGE = tuple(
    value for value in PPT_MASTER_IMAGE_USAGE if value != "auto"
)

PPT_RESOLVED_SCHEMA = {
    "$id": CATALOG_VERSION,
    "type": "object",
    "additionalProperties": False,
    "required": [
        "page_count",
        "mode",
        "visual_style",
        "delivery_purpose",
        "target_audience",
        "color_direction",
        "typography_direction",
        "icon_library",
        "formula_policy",
        "image_usage",
        "image_ai_path",
    ],
    "properties": {
        "page_count": {"type": "integer", "minimum": 1, "maximum": 60},
        "mode": {"type": "string", "enum": list(_CONCRETE_MODES)},
        "visual_style": {
            "type": "string",
            "enum": list(_CONCRETE_VISUAL_STYLES),
        },
        "delivery_purpose": {
            "type": "string",
            "enum": list(PPT_MASTER_DELIVERY_PURPOSES),
        },
        "target_audience": {"type": "string", "minLength": 3, "maxLength": 500},
        "color_direction": {"type": "string", "minLength": 3, "maxLength": 500},
        "typography_direction": {
            "type": "string",
            "minLength": 3,
            "maxLength": 500,
        },
        "icon_library": {"type": "string", "enum": list(_CONCRETE_ICONS)},
        "formula_policy": {
            "type": "string",
            "enum": list(PPT_MASTER_FORMULA_POLICIES),
        },
        "image_usage": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "enum": list(_CONCRETE_IMAGE_USAGE)},
        },
        "image_ai_path": {
            "type": "string",
            "enum": ["api", "not-used"],
        },
    },
}

_RESOLVED_KEYS = tuple(PPT_RESOLVED_SCHEMA["required"])
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}\b")


class PptOptionsValidationError(ValueError):
    """A structured Auto resolution violates the shared PPT option contract."""


def prompt_catalog() -> dict:
    """Return the compact machine-facing enum catalog used in resolver prompts."""
    return {
        "catalog_version": CATALOG_VERSION,
        "mode": list(_CONCRETE_MODES),
        "visual_style": list(_CONCRETE_VISUAL_STYLES),
        "delivery_purpose": list(PPT_MASTER_DELIVERY_PURPOSES),
        "icon_library": list(_CONCRETE_ICONS),
        "formula_policy": list(PPT_MASTER_FORMULA_POLICIES),
        "image_usage": list(_CONCRETE_IMAGE_USAGE),
        "image_ai_path": ["api", "not-used"],
    }


def export_flags_from_options(opts: Mapping[str, object]) -> list[str]:
    """Derive the exact svg_to_pptx flags from sanitized options."""
    transition = str(opts.get("ppt_transition") or "fade")
    animation = str(opts.get("ppt_animation") or "none")
    flags = [f"-t {transition}", f"-a {animation}"]
    if animation != "none":
        flags.append(
            f"--animation-trigger "
            f"{opts.get('ppt_animation_trigger') or 'after-previous'}"
        )
    if bool(opts.get("ppt_native_objects")):
        flags.append("--native-objects")
    if bool(opts.get("ppt_strict_line_fidelity")):
        flags.append("--no-merge")
    return flags


def _page_bounds(value: object) -> tuple[int, int] | None:
    raw = str(value or "auto").strip().lower()
    if raw == "auto":
        return None
    match = re.fullmatch(r"(\d{1,2})(?:-(\d{1,2}))?", raw)
    if not match:
        raise PptOptionsValidationError("requested page count is invalid")
    lower = int(match.group(1))
    upper = int(match.group(2) or lower)
    if lower < 1 or upper > 60 or lower > upper:
        raise PptOptionsValidationError("requested page count is outside 1-60")
    return lower, upper


def _bounded_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise PptOptionsValidationError(f"{key} must be a string")
    value = value.strip()
    if not 3 <= len(value) <= 500:
        raise PptOptionsValidationError(f"{key} must contain 3-500 characters")
    return value


def validate_resolved_ppt_options(
    payload: object,
    requested: Mapping[str, object],
    *,
    image_api_available: bool,
) -> dict:
    """Validate a resolver response against one schema and the user's request."""
    if not isinstance(payload, Mapping):
        raise PptOptionsValidationError("resolved PPT options must be a JSON object")
    if set(payload) != set(_RESOLVED_KEYS):
        missing = sorted(set(_RESOLVED_KEYS) - set(payload))
        extra = sorted(set(payload) - set(_RESOLVED_KEYS))
        raise PptOptionsValidationError(
            f"resolved PPT options have wrong keys; missing={missing}, extra={extra}"
        )

    page_count = payload.get("page_count")
    if isinstance(page_count, bool) or not isinstance(page_count, int):
        raise PptOptionsValidationError("page_count must be an integer")
    if not 1 <= page_count <= 60:
        raise PptOptionsValidationError("page_count must be between 1 and 60")

    def enum_value(key: str, allowed: tuple[str, ...]) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or value not in allowed:
            raise PptOptionsValidationError(
                f"{key} must be one of {list(allowed)}"
            )
        return value

    mode = enum_value("mode", _CONCRETE_MODES)
    visual_style = enum_value("visual_style", _CONCRETE_VISUAL_STYLES)
    delivery_purpose = enum_value(
        "delivery_purpose", PPT_MASTER_DELIVERY_PURPOSES
    )
    icon_library = enum_value("icon_library", _CONCRETE_ICONS)
    formula_policy = enum_value("formula_policy", PPT_MASTER_FORMULA_POLICIES)
    image_ai_path = enum_value("image_ai_path", ("api", "not-used"))

    target_audience = _bounded_text(payload, "target_audience")
    color_direction = _bounded_text(payload, "color_direction")
    typography_direction = _bounded_text(payload, "typography_direction")

    image_usage_raw = payload.get("image_usage")
    if not isinstance(image_usage_raw, list) or not image_usage_raw:
        raise PptOptionsValidationError("image_usage must be a non-empty array")
    if any(
        not isinstance(value, str) or value not in _CONCRETE_IMAGE_USAGE
        for value in image_usage_raw
    ):
        raise PptOptionsValidationError(
            f"image_usage entries must be selected from {list(_CONCRETE_IMAGE_USAGE)}"
        )
    image_usage = list(dict.fromkeys(image_usage_raw))
    if len(image_usage) != len(image_usage_raw):
        raise PptOptionsValidationError("image_usage must not contain duplicates")
    if "none" in image_usage and len(image_usage) != 1:
        raise PptOptionsValidationError("image_usage `none` is exclusive")
    if not image_api_available and "ai" in image_usage:
        raise PptOptionsValidationError("AI images require a configured API")
    if ("ai" in image_usage) != (image_ai_path == "api"):
        raise PptOptionsValidationError(
            "image_ai_path must be `api` exactly when image_usage contains `ai`"
        )

    page_bounds = _page_bounds(requested.get("ppt_page_count"))
    if page_bounds and not page_bounds[0] <= page_count <= page_bounds[1]:
        raise PptOptionsValidationError(
            f"page_count must stay inside requested range {page_bounds}"
        )

    exact_enums = {
        "mode": ("ppt_mode", mode),
        "visual_style": ("ppt_visual_style", visual_style),
        "delivery_purpose": ("ppt_delivery_purpose", delivery_purpose),
        "icon_library": ("ppt_icons", icon_library),
        "formula_policy": ("ppt_formula_policy", formula_policy),
    }
    for label, (request_key, resolved_value) in exact_enums.items():
        requested_value = str(requested.get(request_key) or "auto").strip()
        if requested_value != "auto" and resolved_value != requested_value:
            raise PptOptionsValidationError(
                f"{label} must preserve explicit request {requested_value}"
            )

    exact_text = {
        "target_audience": ("ppt_audience", target_audience),
        "color_direction": ("ppt_color", color_direction),
        "typography_direction": ("ppt_typography", typography_direction),
    }
    for label, (request_key, resolved_value) in exact_text.items():
        requested_value = str(requested.get(request_key) or "").strip()
        if requested_value and resolved_value != requested_value:
            raise PptOptionsValidationError(
                f"{label} must preserve the user's exact text"
            )

    requested_usage = list(requested.get("ppt_image_usage") or ["auto"])
    if requested_usage != ["auto"] and set(image_usage) != set(requested_usage):
        raise PptOptionsValidationError(
            "image_usage must preserve the explicitly selected sources"
        )

    return {
        "page_count": page_count,
        "mode": mode,
        "visual_style": visual_style,
        "delivery_purpose": delivery_purpose,
        "target_audience": target_audience,
        "color_direction": color_direction,
        "typography_direction": typography_direction,
        "icon_library": icon_library,
        "formula_policy": formula_policy,
        "image_usage": image_usage,
        "image_ai_path": image_ai_path,
    }


def _fallback_page_count(requested: Mapping[str, object]) -> int:
    bounds = _page_bounds(requested.get("ppt_page_count"))
    if bounds:
        return round((bounds[0] + bounds[1]) / 2)
    duration = str(requested.get("duration") or "auto")
    try:
        minutes = float(duration)
    except ValueError:
        minutes = math.nan
    if math.isfinite(minutes):
        return max(5, min(20, round(minutes * 2)))
    return 10


def fallback_resolved_ppt_options(
    requested: Mapping[str, object],
    *,
    image_api_available: bool,
) -> dict:
    """Return deterministic, canonical values when both resolver attempts fail."""
    requested_usage = list(requested.get("ppt_image_usage") or ["auto"])
    image_usage = (
        ["provided", "placeholder"]
        if requested_usage == ["auto"]
        else requested_usage
    )
    if not image_api_available:
        image_usage = [value for value in image_usage if value != "ai"]
    if not image_usage:
        image_usage = ["provided", "placeholder"]

    payload = {
        "page_count": _fallback_page_count(requested),
        "mode": (
            "narrative"
            if requested.get("ppt_mode") in (None, "", "auto")
            else requested["ppt_mode"]
        ),
        "visual_style": (
            "editorial"
            if requested.get("ppt_visual_style") in (None, "", "auto")
            else requested["ppt_visual_style"]
        ),
        "delivery_purpose": requested.get("ppt_delivery_purpose")
        or "presentation",
        "target_audience": requested.get("ppt_audience")
        or "Research readers and technical practitioners",
        "color_direction": requested.get("ppt_color")
        or (
            "Light editorial palette: background #F8FAFC, primary #0F172A, "
            "accent #2563EB, body text #1E293B"
        ),
        "typography_direction": requested.get("ppt_typography")
        or "Aptos headings with Aptos body text and a clear presentation hierarchy",
        "icon_library": (
            "tabler-outline"
            if requested.get("ppt_icons") in (None, "", "auto")
            else requested["ppt_icons"]
        ),
        "formula_policy": requested.get("ppt_formula_policy") or "mixed",
        "image_usage": image_usage,
        "image_ai_path": "api" if "ai" in image_usage else "not-used",
    }
    return validate_resolved_ppt_options(
        payload,
        requested,
        image_api_available=image_api_available,
    )


def merge_resolved_ppt_options(
    requested: Mapping[str, object],
    resolved: Mapping[str, object],
) -> dict:
    """Overlay one validated resolution onto sanitized Paper2Video options."""
    merged = dict(requested)
    merged["_ppt_user_request"] = {
        "ppt_audience": str(requested.get("ppt_audience") or ""),
        "ppt_color": str(requested.get("ppt_color") or ""),
        "ppt_typography": str(requested.get("ppt_typography") or ""),
    }
    merged.update(
        {
            "ppt_page_count": str(resolved["page_count"]),
            "ppt_mode": resolved["mode"],
            "ppt_visual_style": resolved["visual_style"],
            "ppt_delivery_purpose": resolved["delivery_purpose"],
            "ppt_audience": resolved["target_audience"],
            "ppt_color": resolved["color_direction"],
            "ppt_typography": resolved["typography_direction"],
            "ppt_icons": resolved["icon_library"],
            "ppt_formula_policy": resolved["formula_policy"],
            "ppt_image_usage": list(resolved["image_usage"]),
            "ppt_image_ai_path": resolved["image_ai_path"],
        }
    )
    return merged


def resolution_prompt(
    pdf_abs: str,
    requested: Mapping[str, object],
    *,
    image_api_available: bool,
    previous_error: str = "",
) -> str:
    """Build the read-only JSON-only Auto resolution prompt."""
    retry = (
        f"\nYour previous response failed validation: {previous_error}\n"
        "Correct it without adding keys or inventing enum ids.\n"
        if previous_error
        else ""
    )
    context = {
        "pdf_path": pdf_abs,
        "paper_title": requested.get("paper_title") or "",
        "target_duration_minutes": requested.get("duration") or "auto",
        "additional_requirements": requested.get("requirements") or "",
        "requested_ppt_options": {
            key: requested.get(key)
            for key in (
                "ppt_page_count",
                "ppt_mode",
                "ppt_visual_style",
                "ppt_delivery_purpose",
                "ppt_audience",
                "ppt_color",
                "ppt_typography",
                "ppt_icons",
                "ppt_formula_policy",
                "ppt_image_usage",
            )
        },
        "image_api_available": image_api_available,
    }
    return (
        "Resolve Paper2Video's PPT-Master Auto options before any deck generation. "
        "This is a read-only planning call: inspect the PDF as needed, do not modify "
        "files, and return exactly one JSON object with no Markdown or prose.\n"
        "Every enumerable value MUST be copied verbatim from canonical_catalog. "
        "Never create, combine, alias, or rename an enum id. Preserve every explicit "
        "non-Auto request exactly. Descriptive audience/color/typography fields may "
        "be paper-specific strings; an Auto color_direction must include at least "
        "two concrete #RRGGBB values and typography_direction must name its primary "
        "font. Set image_ai_path to `api` exactly when image_usage contains `ai`, "
        "otherwise `not-used`.\n"
        f"{retry}"
        f"canonical_catalog = {json.dumps(prompt_catalog(), ensure_ascii=False)}\n"
        f"json_schema = {json.dumps(PPT_RESOLVED_SCHEMA, ensure_ascii=False)}\n"
        f"context = {json.dumps(context, ensure_ascii=False)}\n"
    )


def parse_json_object(text: str) -> dict:
    """Extract exactly one JSON object from a model's final text."""
    raw = str(text or "").strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and not raw[index + end :].strip(" \t\r\n`"):
            return value
    raise PptOptionsValidationError("resolver did not return one clean JSON object")
