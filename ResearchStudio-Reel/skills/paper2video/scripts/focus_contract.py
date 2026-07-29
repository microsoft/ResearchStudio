"""Canonical visual-attention option contract for Paper2Video."""

from __future__ import annotations


VIDEO_POINTER_STYLES = ("cursor", "laser", "none")
VIDEO_SPOTLIGHT_STYLES = ("spotlight", "box", "none")
VIDEO_HIGHLIGHT_STYLES = (
    "box",
    "spotlight",
    "cursor",
    "box_cursor",
    "spotlight_cursor",
    "laser",
    "box_laser",
    "spotlight_laser",
)

VIDEO_DEFAULT_POINTER_STYLE = "laser"
VIDEO_DEFAULT_SPOTLIGHT_STYLE = "spotlight"

_LEGACY_FOCUS_PARTS = {
    "box": ("none", "box"),
    "spotlight": ("none", "spotlight"),
    "cursor": ("cursor", "none"),
    "box_cursor": ("cursor", "box"),
    "spotlight_cursor": ("cursor", "spotlight"),
    "laser": ("laser", "none"),
    "box_laser": ("laser", "box"),
    "spotlight_laser": ("laser", "spotlight"),
    "none": ("none", "none"),
}


def normalize_video_focus(
    pointer_style: object = None,
    spotlight_style: object = None,
    legacy_style: object = None,
) -> tuple[str, str, str]:
    """Return validated ``(pointer, spotlight, renderer_style)`` values.

    Older saved jobs sent one combined ``highlight_style``. New submissions
    send independent pointer and spotlight axes. Supporting both keeps queued
    or retried jobs deterministic while exposing every 3x3 combination.
    """

    pointer_raw = str(pointer_style or "").strip().lower()
    spotlight_raw = str(spotlight_style or "").strip().lower()
    legacy_raw = str(legacy_style or "").strip().lower()

    if not pointer_raw and not spotlight_raw and legacy_raw in _LEGACY_FOCUS_PARTS:
        pointer, spotlight = _LEGACY_FOCUS_PARTS[legacy_raw]
    else:
        pointer = (
            pointer_raw
            if pointer_raw in VIDEO_POINTER_STYLES
            else VIDEO_DEFAULT_POINTER_STYLE
        )
        spotlight = (
            spotlight_raw
            if spotlight_raw in VIDEO_SPOTLIGHT_STYLES
            else VIDEO_DEFAULT_SPOTLIGHT_STYLE
        )

    if pointer == "none" and spotlight == "none":
        renderer_style = "none"
    elif spotlight == "none":
        renderer_style = pointer
    elif pointer == "none":
        renderer_style = spotlight
    else:
        renderer_style = f"{spotlight}_{pointer}"

    if renderer_style != "none" and renderer_style not in VIDEO_HIGHLIGHT_STYLES:
        pointer = VIDEO_DEFAULT_POINTER_STYLE
        spotlight = VIDEO_DEFAULT_SPOTLIGHT_STYLE
        renderer_style = f"{spotlight}_{pointer}"

    return pointer, spotlight, renderer_style
