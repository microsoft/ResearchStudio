#!/usr/bin/env python3
"""
Generate narration-synchronized visual cues for paper2video.

The renderer burns semantic highlight boxes into the video when precise target
geometry is available. Point cues remain valid for legacy/debug decks, but the
production path emits both a normalized `box` and its center `point` so QA can
verify that the highlighted target stays inside the slide canvas.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

try:
    from extract_pptx_elements import extract_pptx_elements
except ImportError:  # pragma: no cover - same-dir import when used as a script
    extract_pptx_elements = None  # type: ignore

SCHEMA_VERSION = "paper2video_visual_cues.v3"
REGIONS_SCHEMA_VERSION = "paper2video_slide_regions.v1"
AUDIT_SCHEMA_VERSION = "paper2video_cue_audit.v1"
CUE_PLAN_SCHEMA_VERSION = "paper2video_visual_cue_plan.v1"
REPAIR_SCHEMA_VERSION = "paper2video_cue_repair_requests.v1"
ANCHOR_CONTRACT_SCHEMA_VERSION = "paper2video_visual_anchor_contract.v1"
ANCHOR_RE = re.compile(r"\bcue_[A-Za-z0-9][A-Za-z0-9_.:-]*")
MICRO_TARGET_AREA = 0.012
MODULE_MIN_AREA = 0.018
MODULE_MAX_AREA = 0.22
CONTAINER_AREA = 0.24
PPTX_GEOMETRY_MIN_SCORE = 3.4
PPTX_GEOMETRY_MIN_IOU = 0.08
PPTX_GEOMETRY_MIN_COVERAGE = 0.55
PPTX_GEOMETRY_CLUSTER_GAP = 0.025
PPTX_GEOMETRY_MAX_OVERHANG = 0.08
PPTX_GEOMETRY_CLUSTER_MAX_AREA = 0.22
TIMING_ALIGNMENT_MIN_SCORE = 0.58
TIMING_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*|[\u4e00-\u9fff]")


@dataclass
class Section:
    index: int
    sid: str
    heading: str
    text: str


@dataclass
class Region:
    slide_index: int
    slide_id: str
    region_id: str
    text: str
    box_px: tuple[float, float, float, float]
    box: tuple[float, float, float, float]
    point: tuple[float, float]
    role: str
    source: str = "svg"
    shape_type: str = ""
    parent_id: str = ""


@dataclass
class CueChoice:
    region: Region | None
    score: float
    confidence: float
    accepted: bool
    reason: str
    candidates: list[dict] = field(default_factory=list)


@dataclass
class GeometryChoice:
    box: tuple[float, float, float, float]
    point: tuple[float, float]
    source: str
    target: str
    role: str
    matched: bool
    score: float
    iou: float
    semantic_coverage: float
    geometry_coverage: float
    reason: str
    candidates: list[dict] = field(default_factory=list)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_float(raw: object, default: float = 0.0) -> float:
    if raw is None:
        return default
    text = str(raw).strip()
    match = re.match(r"^-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else default


def parse_viewbox(root: ET.Element) -> tuple[float, float]:
    raw = root.get("viewBox")
    if raw:
        parts = [parse_float(p) for p in raw.replace(",", " ").split()]
        if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
            return parts[2], parts[3]
    return parse_float(root.get("width"), 1280.0), parse_float(root.get("height"), 720.0)


def parse_transform_offset(transform: str | None) -> tuple[float, float]:
    if not transform:
        return 0.0, 0.0
    tx = ty = 0.0
    for name, body in re.findall(r"([A-Za-z]+)\(([^)]*)\)", transform):
        vals = [parse_float(v) for v in re.split(r"[\s,]+", body.strip()) if v.strip()]
        if name == "translate" and vals:
            tx += vals[0]
            ty += vals[1] if len(vals) > 1 else 0.0
        elif name == "matrix" and len(vals) == 6:
            tx += vals[4]
            ty += vals[5]
    return tx, ty


def union_box(a: tuple[float, float, float, float] | None,
              b: tuple[float, float, float, float] | None) -> tuple[float, float, float, float] | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def points_box(points: Iterable[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    pts = list(points)
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def path_box(raw: str, ox: float, oy: float) -> tuple[float, float, float, float] | None:
    """Approximate an SVG path bbox from command endpoints/control points.

    This intentionally avoids the old "all numbers are x/y pairs" shortcut,
    which misread arc flags and relative h/v values as canvas coordinates and
    produced giant boxes for rounded-card paths. The approximation is enough
    for cue targeting because surrounding rect/text/image children usually
    carry the exact visible extents.
    """
    tokens = re.findall(r"[AaCcHhLlMmQqSsTtVvZz]|-?\d*\.?\d+(?:[eE][+-]?\d+)?", raw or "")
    if not tokens:
        return None
    arity = {
        "M": 2, "L": 2, "T": 2,
        "H": 1, "V": 1,
        "C": 6, "S": 4, "Q": 4,
        "A": 7,
    }
    points: list[tuple[float, float]] = []
    i = 0
    cmd = ""
    x = y = 0.0
    start_x = start_y = 0.0

    def is_cmd(token: str) -> bool:
        return len(token) == 1 and token.isalpha()

    while i < len(tokens):
        if is_cmd(tokens[i]):
            cmd = tokens[i]
            i += 1
            if cmd in {"Z", "z"}:
                x, y = start_x, start_y
                points.append((x + ox, y + oy))
                continue
        if not cmd:
            break
        upper = cmd.upper()
        count = arity.get(upper)
        if count is None:
            break
        first_moveto = upper == "M"
        while i + count <= len(tokens) and not is_cmd(tokens[i]):
            try:
                vals = [float(tokens[i + j]) for j in range(count)]
            except ValueError:
                break
            rel = cmd.islower()
            if upper in {"M", "L", "T"}:
                nx, ny = vals[-2], vals[-1]
                if rel:
                    nx += x
                    ny += y
                x, y = nx, ny
                points.append((x + ox, y + oy))
                if first_moveto:
                    start_x, start_y = x, y
                    first_moveto = False
                    if upper == "M":
                        cmd = "l" if rel else "L"
                        upper = "L"
                        count = arity[upper]
            elif upper == "H":
                nx = vals[0] + x if rel else vals[0]
                x = nx
                points.append((x + ox, y + oy))
            elif upper == "V":
                ny = vals[0] + y if rel else vals[0]
                y = ny
                points.append((x + ox, y + oy))
            elif upper in {"C", "S", "Q"}:
                coords = list(zip(vals[0::2], vals[1::2]))
                if rel:
                    coords = [(cx + x, cy + y) for cx, cy in coords]
                points.extend((cx + ox, cy + oy) for cx, cy in coords)
                x, y = coords[-1]
            elif upper == "A":
                nx, ny = vals[5], vals[6]
                if rel:
                    nx += x
                    ny += y
                points.extend([(x + ox, y + oy), (nx + ox, ny + oy)])
                x, y = nx, ny
            i += count
            if i >= len(tokens) or is_cmd(tokens[i]):
                break
    return points_box(points)


def element_own_box(el: ET.Element, ox: float, oy: float) -> tuple[float, float, float, float] | None:
    tag = local_name(el.tag)
    if tag in {"rect", "image", "use"}:
        x = parse_float(el.get("x")) + ox
        y = parse_float(el.get("y")) + oy
        w = parse_float(el.get("width"))
        h = parse_float(el.get("height"))
        if w > 0 and h > 0:
            return x, y, x + w, y + h
    if tag == "circle":
        cx = parse_float(el.get("cx")) + ox
        cy = parse_float(el.get("cy")) + oy
        r = parse_float(el.get("r"))
        if r > 0:
            return cx - r, cy - r, cx + r, cy + r
    if tag == "ellipse":
        cx = parse_float(el.get("cx")) + ox
        cy = parse_float(el.get("cy")) + oy
        rx = parse_float(el.get("rx"))
        ry = parse_float(el.get("ry"))
        if rx > 0 and ry > 0:
            return cx - rx, cy - ry, cx + rx, cy + ry
    if tag == "line":
        x1 = parse_float(el.get("x1")) + ox
        y1 = parse_float(el.get("y1")) + oy
        x2 = parse_float(el.get("x2")) + ox
        y2 = parse_float(el.get("y2")) + oy
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
    if tag in {"polygon", "polyline"}:
        raw = el.get("points") or ""
        vals = [parse_float(v) for v in re.split(r"[\s,]+", raw.strip()) if v.strip()]
        pts = [(vals[i] + ox, vals[i + 1] + oy) for i in range(0, len(vals) - 1, 2)]
        return points_box(pts)
    if tag == "path":
        return path_box(el.get("d") or "", ox, oy)
    if tag in {"text", "tspan"}:
        x = parse_float(el.get("x"), math.nan)
        y = parse_float(el.get("y"), math.nan)
        if math.isnan(x) or math.isnan(y):
            return None
        size = parse_float(el.get("font-size"), 16.0)
        text = "".join(el.itertext()).strip()
        width = max(12.0, min(520.0, len(text) * size * 0.46))
        return x + ox, y - size + oy, x + width + ox, y + size * 0.35 + oy
    return None


def element_box(el: ET.Element, ox: float = 0.0, oy: float = 0.0) -> tuple[float, float, float, float] | None:
    tx, ty = parse_transform_offset(el.get("transform"))
    ox += tx
    oy += ty
    box = element_own_box(el, ox, oy)
    for child in list(el):
        box = union_box(box, element_box(child, ox, oy))
    return box


def ancestor_transform_offset(el: ET.Element, parent_map: dict[ET.Element, ET.Element]) -> tuple[float, float]:
    """Return cumulative translate/matrix offset from ancestors only.

    `element_box()` already applies the element's own transform and all child
    transforms. When `extract_regions()` scores every `<g>` independently via
    `root.iter()`, however, nested groups would otherwise lose their parent
    translation. That shifts cue points for table rows and card internals.
    """
    chain: list[ET.Element] = []
    parent = parent_map.get(el)
    while parent is not None:
        chain.append(parent)
        parent = parent_map.get(parent)
    ox = oy = 0.0
    for ancestor in reversed(chain):
        tx, ty = parse_transform_offset(ancestor.get("transform"))
        ox += tx
        oy += ty
    return ox, oy


def semantic_text(el: ET.Element) -> str:
    """Collect visible text plus explicit cue labels from an SVG element."""
    parts: list[str] = []
    for attr in ("id", "aria-label", "data-cue-label", "data-section", "data-role"):
        value = el.get(attr)
        if value:
            parts.append(str(value))
    for child in list(el):
        if local_name(child.tag) in {"title", "desc"}:
            text = " ".join("".join(child.itertext()).split())
            if text:
                parts.append(text)
    visible = " ".join("".join(el.itertext()).split())
    if visible:
        parts.append(visible)
    return " ".join(dict.fromkeys(p for p in parts if p)).strip()


def clamp_box(box: tuple[float, float, float, float],
              width: float, height: float) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = box
    return (
        max(0.0, min(width, x0)),
        max(0.0, min(height, y0)),
        max(0.0, min(width, x1)),
        max(0.0, min(height, y1)),
    )


def infer_role(region_id: str, text: str) -> str:
    blob = f"{region_id} {text}".lower()
    if any(k in blob for k in ("background", "footer", "page-number", "pagenum", "chrome")):
        return "chrome"
    if "header" in blob:
        return "header"
    if (
        re.search(r"\b(?:figure|table)\s+\d+", text, flags=re.IGNORECASE)
        and "figure" not in region_id.lower()
        and "panel" not in region_id.lower()
    ):
        return "caption"
    role_map = [
        ("formula", ("formula", "equation", "sinusoid", "sine", "cosine", "wavelength", "positional encoding")),
        ("figure", ("figure", "image", "chart", "scaling", "evidence", "plot")),
        ("result", ("kpi", "metric", "result", "headline", "number", "accuracy", "average", "gain")),
        ("method", ("method", "pipeline", "flow", "step", "score", "organize", "selection", "stream", "attention", "encoder", "decoder", "sublayer", "sub-layer", "projection", "head", "layernorm", "residual")),
        ("guidance", ("guidance", "boundary", "cyclic", "continuity", "diversity", "framework", "jitter", "jit", "local diversity", "homogeneous", "similar", "strictly sorted", "brittle")),
        ("takeaway", ("takeaway", "closing", "core", "claim")),
        ("qr", ("qr", "logo", "github", "arxiv", "repository", "repo", "link")),
        ("title", ("title", "cover")),
        ("result", ("table", "row", "complexity", "benchmark", "bleu", "score")),
        ("text", ("textbox", "text-box")),
    ]
    for role, keys in role_map:
        if any(k in blob for k in keys):
            return role
    return "content"


def is_chrome(region_id: str) -> bool:
    rid = region_id.lower()
    return any(k in rid for k in ("background", "footer", "page-number", "pagenum", "chrome"))


def extract_regions(svg_path: Path, slide_index: int) -> tuple[str, float, float, list[Region]]:
    root = ET.parse(svg_path).getroot()
    width, height = parse_viewbox(root)
    slide_id = svg_path.stem
    regions: list[Region] = []
    canvas_area = width * height
    parent_map = {child: parent for parent in root.iter() for child in list(parent)}

    for el in root.iter():
        if local_name(el.tag) != "g" or not el.get("id"):
            continue
        rid = str(el.get("id"))
        ox, oy = ancestor_transform_offset(el, parent_map)
        box = element_box(el, ox, oy)
        if box is None:
            continue
        x0, y0, x1, y1 = clamp_box(box, width, height)
        bw, bh = x1 - x0, y1 - y0
        if bw <= 4 or bh <= 4:
            continue
        area = bw * bh
        if area > canvas_area * 0.88:
            continue
        text = semantic_text(el)
        norm = (x0 / width, y0 / height, bw / width, bh / height)
        point = ((x0 + bw / 2.0) / width, (y0 + bh / 2.0) / height)
        regions.append(
            Region(
                slide_index=slide_index,
                slide_id=slide_id,
                region_id=rid,
                text=text[:240],
                box_px=(x0, y0, bw, bh),
                box=norm,
                point=point,
                role=infer_role(rid, text),
                source="svg",
            )
        )

    return slide_id, width, height, regions


def region_area(region: Region) -> float:
    return max(0.0, region.box[2]) * max(0.0, region.box[3])


def region_is_chrome(region: Region) -> bool:
    return region.role in {"chrome", "footer", "background"} or is_chrome(region.region_id)


def box_contains(parent: Region, child: Region, *, tolerance: float = 0.008) -> bool:
    px, py, pw, ph = parent.box
    cx, cy, cw, ch = child.box
    if parent.region_id == child.region_id and parent.source == child.source:
        return False
    return (
        cx + tolerance >= px
        and cy + tolerance >= py
        and cx + cw <= px + pw + tolerance
        and cy + ch <= py + ph + tolerance
    )


def looks_like_caption(region: Region) -> bool:
    blob = f"{region.region_id} {region.text}".lower()
    return region.role == "caption" or (
        region_area(region) < 0.035
        and re.search(r"\b(?:figure|table)\s+\d+", blob, flags=re.IGNORECASE) is not None
    )


def is_named_module(region: Region) -> bool:
    rid = region.region_id.lower()
    prefixes = (
        "card-", "kpi-", "point-", "step-", "row-", "pillar-", "legend-",
        "item-", "reg-", "takeaway", "paper-figure", "formula", "track-",
        "block-", "panel-", "diagram-", "flow-", "timeline-", "comparison-",
    )
    return rid.startswith(prefixes) or any(f"-{prefix}" in rid for prefix in prefixes)


def is_module_sized(region: Region) -> bool:
    area = region_area(region)
    return MODULE_MIN_AREA <= area <= 0.34


def is_micro_target(region: Region) -> bool:
    area = region_area(region)
    if region_anchor_ids(region):
        return False
    return area < MICRO_TARGET_AREA and region.role in {"text", "caption", "header", "content", "figure"}


def is_large_container(region: Region) -> bool:
    area = region_area(region)
    rid = region.region_id.lower()
    if is_named_module(region) and area <= 0.34:
        return False
    return area > CONTAINER_AREA or rid in {"content", "body", "group", "panel"}


def module_size_adjustment(region: Region) -> tuple[float, list[str]]:
    area = region_area(region)
    delta = 0.0
    reasons: list[str] = []
    if looks_like_caption(region):
        delta -= 8.0
        reasons.append("caption_target_penalty")
    if is_micro_target(region):
        delta -= 5.5
        reasons.append("micro_word_target_penalty")
    elif area < MODULE_MIN_AREA and not region_anchor_ids(region):
        delta -= 1.8
        reasons.append("small_leaf_penalty")

    if is_named_module(region) and is_module_sized(region):
        delta += 2.0
        reasons.append("module_id_bonus")
    elif MODULE_MIN_AREA <= area <= MODULE_MAX_AREA:
        delta += 1.0
        reasons.append("module_size_bonus")

    if is_large_container(region) and region.role not in {"figure", "title"}:
        delta -= 4.0
        reasons.append("large_container_penalty")
    return delta, reasons


def box_edges(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x, y, w, h = box
    return x, y, x + w, y + h


def box_area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2]) * max(0.0, box[3])


def box_intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    ax0, ay0, ax1, ay1 = box_edges(a)
    bx0, by0, bx1, by1 = box_edges(b)
    iw = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    ih = max(0.0, min(ay1, by1) - max(ay0, by0))
    return iw * ih


def box_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    inter = box_intersection_area(a, b)
    union = box_area(a) + box_area(b) - inter
    return inter / union if union > 0 else 0.0


def box_coverage(
    source_box: tuple[float, float, float, float],
    target_box: tuple[float, float, float, float],
) -> float:
    denom = box_area(source_box)
    return box_intersection_area(source_box, target_box) / denom if denom > 0 else 0.0


def box_center(box: tuple[float, float, float, float]) -> tuple[float, float]:
    return box[0] + box[2] / 2.0, box[1] + box[3] / 2.0


def point_from_box(box: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y = box_center(box)
    return max(0.0, min(1.0, x)), max(0.0, min(1.0, y))


def box_center_distance(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax, ay = box_center(a)
    bx, by = box_center(b)
    return math.hypot(ax - bx, ay - by)


def box_gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = box_edges(a)
    bx0, by0, bx1, by1 = box_edges(b)
    dx = max(0.0, max(ax0, bx0) - min(ax1, bx1))
    dy = max(0.0, max(ay0, by0) - min(ay1, by1))
    return math.hypot(dx, dy)


def union_region_boxes(regions: list[Region]) -> tuple[float, float, float, float] | None:
    if not regions:
        return None
    x0 = min(r.box[0] for r in regions)
    y0 = min(r.box[1] for r in regions)
    x1 = max(r.box[0] + r.box[2] for r in regions)
    y1 = max(r.box[1] + r.box[3] for r in regions)
    x0 = max(0.0, x0)
    y0 = max(0.0, y0)
    x1 = min(1.0, x1)
    y1 = min(1.0, y1)
    return x0, y0, max(0.001, x1 - x0), max(0.001, y1 - y0)


def geometry_text_overlap(chunk: str, semantic_region: Region, geometry_region: Region) -> int:
    semantic_tokens = set(content_tokens(f"{semantic_region.region_id} {semantic_region.text}"))
    geometry_tokens = set(content_tokens(f"{geometry_region.region_id} {geometry_region.text}"))
    chunk_tokens = set(content_tokens(chunk))
    return len((semantic_tokens | chunk_tokens) & geometry_tokens)


# --- Wrapped-line grouping -------------------------------------------------
# One logical text (a title or tagline) is frequently authored/exported as
# SEVERAL per-line boxes under a single group. A cue that matches one line
# should spotlight the whole wrapped run, so the box handed to the renderer is
# the intended unit — the renderer's ink-tighten then hugs all the lines. This
# unions ONLY genuine single-line continuations (same left edge, same line
# height, nearly touching, each clearly one line = wide:short), so multi-line
# PARAGRAPH blocks inside a card — which must keep their own focus for the
# script's progression — are never merged.
GROUP_WRAPPED_LINES = os.environ.get(
    "VIDEO_CUE_GROUP_WRAPPED_LINES", "1").strip().lower() not in ("0", "off", "false", "no")
WRAP_X_EPS = float(os.environ.get("VIDEO_CUE_WRAP_X_EPS", "0.02"))        # same left edge
WRAP_MIN_ASPECT = float(os.environ.get("VIDEO_CUE_WRAP_MIN_ASPECT", "2.5"))  # w/h => one line
WRAP_GAP_MAX_FRAC = float(os.environ.get("VIDEO_CUE_WRAP_GAP_FRAC", "0.15"))  # gap <= frac*line-h
WRAP_H_LO, WRAP_H_HI = 0.6, 1.6                                           # line-height ratio band


def _region_is_single_line(region: Region) -> bool:
    _, _, w, h = region.box
    return h > 0 and (w / h) >= WRAP_MIN_ASPECT


def _wrapped_adjacent(a: Region, b: Region) -> bool:
    """True when b is a wrapped continuation directly below a: same column, same
    line height, nearly touching, both clearly single lines."""
    ax, ay, aw, ah = a.box
    bx, by, bw, bh = b.box
    if abs(ax - bx) > WRAP_X_EPS:
        return False
    if ah <= 0 or bh <= 0 or not (WRAP_H_LO <= bh / ah <= WRAP_H_HI):
        return False
    if not (_region_is_single_line(a) and _region_is_single_line(b)):
        return False
    gap = by - (ay + ah)
    minh = min(ah, bh)
    return -0.5 * minh <= gap <= WRAP_GAP_MAX_FRAC * minh


def _wrapped_run(target: Region, siblings: list[Region]) -> list[Region]:
    order = sorted(siblings, key=lambda r: r.box[1])
    try:
        idx = order.index(target)
    except ValueError:
        return [target]
    run = [target]
    i = idx
    while i + 1 < len(order) and _wrapped_adjacent(order[i], order[i + 1]):
        run.append(order[i + 1])
        i += 1
    i = idx
    while i - 1 >= 0 and _wrapped_adjacent(order[i - 1], order[i]):
        run.insert(0, order[i - 1])
        i -= 1
    return run


def union_wrapped_line_cues(cue_entries: list[dict], regions: list[Region]) -> None:
    """In-place: expand each single-line-fragment cue to its full wrapped run so
    the box is the whole title/tagline, not one line. Only pptx single-element
    text cues are touched; clusters and multi-line blocks are left as-is."""
    if not GROUP_WRAPPED_LINES:
        return
    by_id = {r.region_id: r for r in regions if r.source == "pptx"}
    for cue in cue_entries:
        if cue.get("geometry_source") != "pptx":
            continue
        target = by_id.get(cue.get("geometry_target"))
        if target is None or target.shape_type != "TEXT_BOX" or not target.parent_id:
            continue
        if not _region_is_single_line(target):
            continue
        sibs = [r for r in by_id.values()
                if r.parent_id == target.parent_id and r.shape_type == "TEXT_BOX"]
        if len(sibs) < 2:
            continue
        run = _wrapped_run(target, sibs)
        if len(run) < 2:
            continue
        ub = union_region_boxes(run)
        if not ub:
            continue
        cue["box"] = round_list(ub)
        cue["point"] = round_list(point_from_box(ub))
        cue["geometry_box"] = round_list(ub)
        cue["grouped_wrapped_lines"] = [r.region_id for r in run]


def geometry_match_score(chunk: str, semantic_region: Region, geometry_region: Region) -> tuple[float, list[str], float, float, float]:
    semantic_box = semantic_region.box
    geometry_box = geometry_region.box
    iou = box_iou(semantic_box, geometry_box)
    semantic_cov = box_coverage(semantic_box, geometry_box)
    geometry_cov = box_coverage(geometry_box, semantic_box)
    distance = box_center_distance(semantic_box, geometry_box)
    area_ratio = box_area(geometry_box) / max(box_area(semantic_box), 1e-6)

    score = iou * 6.0 + semantic_cov * 1.8 + geometry_cov * 2.0 + max(0.0, 1.4 - distance * 5.0)
    reasons = [
        f"iou={iou:.3f}",
        f"semantic_cov={semantic_cov:.3f}",
        f"geometry_cov={geometry_cov:.3f}",
        f"center_dist={distance:.3f}",
    ]
    if semantic_region.role == geometry_region.role:
        score += 0.7
        reasons.append("role_match")
    elif geometry_region.role in {semantic_region.role, "text", "content"} or semantic_region.role in {geometry_region.role, "text", "content"}:
        score += 0.25
        reasons.append("role_compatible")

    shared_anchors = set(region_anchor_ids(semantic_region)) & set(region_anchor_ids(geometry_region))
    if shared_anchors:
        score += 4.0
        reasons.append("shared_anchor:" + ",".join(sorted(shared_anchors)[:3]))

    overlap = geometry_text_overlap(chunk, semantic_region, geometry_region)
    if overlap:
        score += min(1.4, overlap * 0.35)
        reasons.append(f"text_overlap={overlap}")

    if area_ratio > 1.45:
        score -= min(2.8, (area_ratio - 1.45) * 2.2)
        reasons.append(f"large_geometry_ratio={area_ratio:.2f}")
    elif 0.35 <= area_ratio <= 1.25:
        score += 0.45
        reasons.append("area_ratio_ok")
    elif area_ratio < 0.16 and not shared_anchors:
        score -= 1.2
        reasons.append(f"tiny_geometry_ratio={area_ratio:.2f}")

    if looks_like_caption(geometry_region):
        score -= 4.0
        reasons.append("reject_caption_geometry")
    if region_is_chrome(geometry_region):
        score -= 100.0
        reasons.append("reject_chrome_geometry")
    return score, reasons, iou, semantic_cov, geometry_cov


def geometry_candidate_payload(
    region: Region,
    *,
    score: float,
    reasons: list[str],
    iou: float,
    semantic_coverage: float,
    geometry_coverage: float,
) -> dict:
    payload = region_debug_payload(region, score=score, reasons=reasons)
    payload.update({
        "iou": round(iou, 3),
        "semantic_coverage": round(semantic_coverage, 3),
        "geometry_coverage": round(geometry_coverage, 3),
    })
    return payload


def connected_pptx_components(regions: list[Region]) -> list[list[Region]]:
    remaining = set(range(len(regions)))
    components: list[list[Region]] = []
    while remaining:
        start = remaining.pop()
        stack = [start]
        component = [regions[start]]
        while stack:
            i = stack.pop()
            for j in list(remaining):
                if box_gap(regions[i].box, regions[j].box) <= PPTX_GEOMETRY_CLUSTER_GAP:
                    remaining.remove(j)
                    stack.append(j)
                    component.append(regions[j])
        components.append(component)
    return components


def cluster_region(
    semantic_region: Region,
    members: list[Region],
    all_regions: list[Region],
    idx: int,
) -> Region | None:
    union_box = union_region_boxes(members)
    if union_box is None:
        return None
    union_area = box_area(union_box)
    semantic_area = max(box_area(semantic_region.box), 1e-6)
    if union_area > PPTX_GEOMETRY_CLUSTER_MAX_AREA and semantic_region.role not in {"figure", "title"}:
        return None
    if union_area / semantic_area > 2.2 and semantic_region.role not in {"figure", "title"}:
        return None
    overhang = 1.0 - box_coverage(union_box, semantic_region.box)
    if overhang > PPTX_GEOMETRY_MAX_OVERHANG:
        return None
    member_keys = {region_key(m) for m in members}
    contamination = 0.0
    for other in all_regions:
        if other.source != "pptx" or region_key(other) in member_keys:
            continue
        if region_is_chrome(other) or looks_like_caption(other) or region_area(other) < 0.001:
            continue
        if other.parent_id in member_keys or any(parent_id_matches(other, m) or parent_id_matches(m, other) for m in members):
            continue
        if box_coverage(other.box, union_box) >= 0.55 and box_coverage(other.box, semantic_region.box) < 0.12:
            contamination += box_area(other.box)
    if union_area > 0 and contamination / union_area > 0.18:
        return None
    member_ids = [m.region_id for m in members]
    text = " ".join(m.text for m in members if m.text).strip()
    return Region(
        slide_index=semantic_region.slide_index,
        slide_id=semantic_region.slide_id,
        region_id=f"pptx_cluster:{idx}:{'+'.join(member_ids[:5])}",
        text=text[:500],
        box_px=(0.0, 0.0, 0.0, 0.0),
        box=union_box,
        point=point_from_box(union_box),
        role=semantic_region.role,
        source="pptx_cluster",
        shape_type="cluster",
        parent_id=semantic_region.region_id,
    )


def resolve_geometry_choice(
    semantic_region: Region,
    regions: list[Region],
    chunk: str,
    *,
    prefer_pptx_geometry: bool,
    min_score: float,
) -> GeometryChoice:
    fallback = GeometryChoice(
        box=semantic_region.box,
        point=semantic_region.point,
        source=semantic_region.source,
        target=semantic_region.region_id,
        role=semantic_region.role,
        matched=False,
        score=0.0,
        iou=1.0,
        semantic_coverage=1.0,
        geometry_coverage=1.0,
        reason="semantic_geometry_fallback",
        candidates=[],
    )
    if not prefer_pptx_geometry:
        return fallback
    if semantic_region.source in {"pptx", "pptx_cluster"}:
        return GeometryChoice(
            box=semantic_region.box,
            point=semantic_region.point,
            source=semantic_region.source,
            target=semantic_region.region_id,
            role=semantic_region.role,
            matched=semantic_region.source == "pptx",
            score=0.0,
            iou=1.0,
            semantic_coverage=1.0,
            geometry_coverage=1.0,
            reason="semantic_target_already_pptx_geometry",
            candidates=[],
        )

    pptx_regions = [
        r for r in regions
        if r.source == "pptx"
        and not region_is_chrome(r)
        and not looks_like_caption(r)
        and region_area(r) > 0.0005
    ]
    if not pptx_regions:
        return fallback

    candidates: list[tuple[float, list[str], Region, float, float, float]] = []
    for region in pptx_regions:
        score, reasons, iou, semantic_cov, geometry_cov = geometry_match_score(chunk, semantic_region, region)
        if iou >= PPTX_GEOMETRY_MIN_IOU or semantic_cov >= 0.35 or geometry_cov >= PPTX_GEOMETRY_MIN_COVERAGE:
            candidates.append((score, reasons, region, iou, semantic_cov, geometry_cov))

    overlapping = [
        r for r in pptx_regions
        if box_coverage(r.box, semantic_region.box) >= 0.35
        or box_coverage(semantic_region.box, r.box) >= 0.10
    ]
    for idx, members in enumerate(connected_pptx_components(overlapping)):
        if len(members) < 2:
            continue
        clustered = cluster_region(semantic_region, members, pptx_regions, idx)
        if clustered is None:
            continue
        score, reasons, iou, semantic_cov, geometry_cov = geometry_match_score(chunk, semantic_region, clustered)
        score += min(1.2, len(members) * 0.12)
        reasons.append(f"connected_cluster={len(members)}")
        candidates.append((score, reasons, clustered, iou, semantic_cov, geometry_cov))

    if not candidates:
        return fallback
    candidates.sort(key=lambda item: (item[0], item[3], item[5], item[2].source == "pptx"), reverse=True)
    candidate_report = [
        geometry_candidate_payload(
            region,
            score=score,
            reasons=reasons,
            iou=iou,
            semantic_coverage=semantic_cov,
            geometry_coverage=geometry_cov,
        )
        for score, reasons, region, iou, semantic_cov, geometry_cov in candidates[:12]
    ]
    score, reasons, best, iou, semantic_cov, geometry_cov = candidates[0]
    promoted, geometry_promotion = promote_geometry_region(best, pptx_regions)
    if geometry_promotion:
        best = promoted
        iou = box_iou(semantic_region.box, best.box)
        semantic_cov = box_coverage(semantic_region.box, best.box)
        geometry_cov = box_coverage(best.box, semantic_region.box)
        reasons = [geometry_promotion["reason"], *reasons]
    if score < min_score or (iou < PPTX_GEOMETRY_MIN_IOU and geometry_cov < PPTX_GEOMETRY_MIN_COVERAGE):
        return GeometryChoice(
            box=semantic_region.box,
            point=semantic_region.point,
            source=semantic_region.source,
            target=semantic_region.region_id,
            role=semantic_region.role,
            matched=False,
            score=round(score, 3),
            iou=round(iou, 3),
            semantic_coverage=round(semantic_cov, 3),
            geometry_coverage=round(geometry_cov, 3),
            reason="pptx_geometry_low_confidence:" + ";".join(reasons[:5]),
            candidates=candidate_report,
        )
    return GeometryChoice(
        box=best.box,
        point=best.point,
        source=best.source,
        target=best.region_id,
        role=best.role,
        matched=True,
        score=round(score, 3),
        iou=round(iou, 3),
        semantic_coverage=round(semantic_cov, 3),
        geometry_coverage=round(geometry_cov, 3),
        reason="pptx_geometry_match:" + ";".join(reasons[:6]),
        candidates=candidate_report,
    )


def regions_from_pptx_payload(pptx_payload: dict | None, *, slide_index: int, slide_id: str) -> list[Region]:
    if not pptx_payload:
        return []
    slides = pptx_payload.get("slides") or []
    if slide_index < 1 or slide_index > len(slides):
        return []
    slide = slides[slide_index - 1]
    out: list[Region] = []
    for element in slide.get("elements") or []:
        box = element.get("box")
        point = element.get("point")
        if (
            not isinstance(box, list)
            or len(box) != 4
            or not isinstance(point, list)
            or len(point) != 2
        ):
            continue
        x, y, w, h = [float(v) for v in box]
        if w <= 0 or h <= 0:
            continue
        rid = f"pptx:{element.get('id') or element.get('name') or slide_index}"
        text = str(element.get("semantic_text") or element.get("text") or "")
        anchors = element.get("cue_anchors") or []
        if anchors:
            text = " ".join([text, " ".join(str(a) for a in anchors)]).strip()
        role = str(element.get("role") or infer_role(rid, text))
        if role == "background":
            continue
        out.append(
            Region(
                slide_index=slide_index,
                slide_id=slide_id,
                region_id=rid,
                text=text[:500],
                box_px=(0.0, 0.0, 0.0, 0.0),
                box=(x, y, w, h),
                point=(float(point[0]), float(point[1])),
                role=role if role != "footer" else "chrome",
                source="pptx",
                shape_type=str(element.get("shape_type") or ""),
                parent_id=str(element.get("parent_id") or ""),
            )
        )
    return out


def merge_regions(svg_regions: list[Region], pptx_regions: list[Region]) -> list[Region]:
    """Keep both semantic SVG groups and precise PPTX shapes.

    PPTX leaf shapes are often more precise, while SVG groups sometimes carry
    better IDs. The scorer below can choose either, but we lightly de-duplicate
    huge chrome regions so they never dominate.
    """
    regions = [r for r in [*svg_regions, *pptx_regions] if not region_is_chrome(r)]
    useful = []
    for region in regions:
        area = region_area(region)
        if area > 0.88 and not region_anchor_ids(region):
            continue
        if area < 0.00045 and not region.text and not region_anchor_ids(region):
            continue
        useful.append(region)
    return useful or regions or svg_regions


def clean_note_text(text: str) -> str:
    lines = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or line.lstrip().startswith("#"):
            continue
        line = re.sub(r"[*_`>#-]+", " ", line)
        if line.strip():
            lines.append(line.strip())
    return " ".join(lines)


def load_sections_from_notes(notes_dir: Path) -> list[Section]:
    files = [p for p in sorted(notes_dir.glob("*.md")) if p.name != "total.md"]
    sections = []
    for idx, path in enumerate(files, start=1):
        text = clean_note_text(path.read_text(encoding="utf-8"))
        if text:
            sections.append(Section(index=idx, sid=path.stem, heading=path.stem, text=text))
    return sections


def load_sections(script_json: Path | None, project: Path) -> list[Section]:
    if script_json is not None:
        payload = json.loads(script_json.read_text(encoding="utf-8"))
        sections = payload.get("sections") or []
        out = []
        for idx, sec in enumerate(sections, start=1):
            sid = str(sec.get("id") or f"slide_{idx:02d}")
            text = str(sec.get("text") or "").strip()
            if text:
                out.append(Section(index=idx, sid=sid, heading=str(sec.get("heading") or sid), text=text))
        return out
    return load_sections_from_notes(project / "notes")


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_sentences(sentences: list[str], max_chunks: int) -> list[str]:
    if len(sentences) <= max_chunks:
        return sentences
    chunks = [[sent] for sent in sentences]
    weights = [len(sent) for sent in sentences]
    while len(chunks) > max_chunks:
        merge_at = min(
            range(len(chunks) - 1),
            key=lambda i: weights[i] + weights[i + 1],
        )
        chunks[merge_at].extend(chunks[merge_at + 1])
        weights[merge_at] += weights[merge_at + 1]
        del chunks[merge_at + 1]
        del weights[merge_at + 1]
    return [" ".join(chunk).strip() for chunk in chunks if " ".join(chunk).strip()]


def normalize_timing_token(raw: str) -> str:
    text = (raw or "").lower()
    text = (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("—", "-")
        .replace("–", "-")
    )
    text = re.sub(r"^[^a-z0-9\u4e00-\u9fff]+|[^a-z0-9\u4e00-\u9fff]+$", "", text)
    return text.strip("-_'\"")


def timing_tokens(text: str) -> list[str]:
    tokens = []
    for match in TIMING_TOKEN_RE.findall(text or ""):
        token = normalize_timing_token(match)
        if token:
            tokens.append(token)
    return tokens


def token_matches(a: str, b: str) -> bool:
    if a == b:
        return True
    return a.replace("-", "") == b.replace("-", "")


def timed_word_tokens(words: list[dict]) -> list[dict]:
    out: list[dict] = []
    for word in words:
        if not isinstance(word, dict) or not isinstance(word.get("start"), (int, float)):
            continue
        raw = str(word.get("text") or word.get("word") or "")
        tokens = timing_tokens(raw)
        if not tokens:
            continue
        start = float(word.get("start", 0.0))
        end = float(word.get("end", word.get("start", start) + 0.2))
        for token in tokens:
            out.append({"token": token, "start": start, "end": end, "text": raw})
    return out


def score_timing_window(chunk_tokens: list[str], words: list[dict], start: int) -> float:
    if not chunk_tokens or start >= len(words):
        return 0.0
    n = min(len(chunk_tokens), len(words) - start)
    if n <= 0:
        return 0.0
    matched = 0
    prefix = 0
    for idx in range(n):
        ok = token_matches(chunk_tokens[idx], str(words[start + idx].get("token") or ""))
        if ok:
            matched += 1
            if idx == prefix:
                prefix += 1
    first_bonus = 0.16 if token_matches(chunk_tokens[0], str(words[start].get("token") or "")) else 0.0
    prefix_bonus = min(0.18, prefix * 0.035)
    length_penalty = 0.0 if len(chunk_tokens) <= len(words) - start else 0.08
    return matched / max(1, len(chunk_tokens)) + first_bonus + prefix_bonus - length_penalty


def find_timing_window(chunk_tokens: list[str], words: list[dict], cursor: int) -> tuple[int, int, float]:
    if not chunk_tokens or not words:
        return cursor, cursor, 0.0
    start_floor = max(0, min(cursor, len(words) - 1))
    best_start = start_floor
    best_score = -1.0
    for start in range(start_floor, len(words)):
        score = score_timing_window(chunk_tokens, words, start)
        score -= min(0.24, max(0, start - start_floor) * 0.006)
        if score > best_score:
            best_start = start
            best_score = score
        if best_score >= 1.0 and start > start_floor + 8:
            break
    end = min(len(words) - 1, best_start + max(1, len(chunk_tokens)) - 1)
    return best_start, end, round(max(0.0, best_score), 3)


def word_timing_source(source: str) -> bool:
    return source.startswith("edge_word_")


def proportional_timing_details(chunks: list[str], times: list[tuple[float, float]]) -> list[dict]:
    details = []
    for idx, (chunk, (start, end)) in enumerate(zip(chunks, times), start=1):
        details.append({
            "chunk_index": idx,
            "method": "duration_proportional",
            "score": 0.0,
            "start_word": "",
            "end_word": "",
            "start": start,
            "end": end,
            "token_count": len(timing_tokens(chunk)),
        })
    return details


def content_tokens(text: str) -> list[str]:
    stop = {
        "the", "and", "for", "that", "this", "with", "from", "into", "then", "than",
        "have", "has", "are", "was", "were", "can", "may", "use", "uses", "using",
        "each", "here", "there", "paper", "model", "data", "training", "slide",
    }
    tokens = [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[0-9]+(?:\.[0-9]+)?", text)]
    return [t for t in tokens if t not in stop]


def load_word_timings(path: Path | None) -> dict[str, list[dict]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("sections"), list):
        return {
            str(sec.get("id")): list(sec.get("words") or [])
            for sec in payload["sections"]
            if isinstance(sec, dict) and sec.get("id")
        }
    if isinstance(payload, dict):
        return {str(k): list(v) for k, v in payload.items() if isinstance(v, list)}
    return {}


def allocate_times_from_words(
    chunks: list[str],
    duration: float,
    word_timings: list[dict] | None,
) -> tuple[list[tuple[float, float]], str, list[dict]]:
    if not word_timings:
        times = allocate_times(chunks, duration)
        return times, "duration_proportional", proportional_timing_details(chunks, times)

    words = timed_word_tokens(word_timings)
    if not words:
        times = allocate_times(chunks, duration)
        return times, "duration_proportional", proportional_timing_details(chunks, times)

    cursor = 0
    out: list[tuple[float, float]] = []
    details: list[dict] = []
    aligned = True
    for idx, chunk in enumerate(chunks, start=1):
        chunk_tokens = timing_tokens(chunk)
        if not chunk_tokens:
            start_i = min(cursor, len(words) - 1)
            end_i = start_i
            score = 0.0
            aligned = False
        else:
            start_i, end_i, score = find_timing_window(chunk_tokens, words, cursor)
            if score < TIMING_ALIGNMENT_MIN_SCORE:
                aligned = False
        start = float(words[start_i].get("start", 0.0))
        end = float(words[end_i].get("end", words[end_i].get("start", start) + 0.2))
        out.append((round(max(0.0, start), 3), round(max(start + 0.05, min(end, duration)), 3)))
        cursor = end_i + 1
        details.append({
            "chunk_index": idx,
            "method": "edge_word_alignment",
            "score": score,
            "start_word": words[start_i].get("text") or words[start_i].get("token") or "",
            "end_word": words[end_i].get("text") or words[end_i].get("token") or "",
            "start_word_index": start_i,
            "end_word_index": end_i,
            "start": out[-1][0],
            "end": out[-1][1],
            "token_count": len(chunk_tokens),
        })
    return out, "edge_word_alignment" if aligned else "edge_word_alignment_partial", details


def mentions_auxiliary_link(text: str) -> bool:
    lowered = text.lower()
    if any(phrase in lowered for phrase in ("source code", "project page", "paper link", "code link")):
        return True
    return re.search(r"\b(qr|code|github|repository|repo|arxiv|link|url)\b", lowered) is not None


def expected_roles(chunk: str) -> set[str]:
    chunk_l = chunk.lower()
    roles: set[str] = set()
    if mentions_auxiliary_link(chunk):
        roles.add("qr")
    role_keys = [
        ("result", ("result", "reaches", "average", "gain", "outperform", "accuracy", "random", "improvement", "bleu", "imagenet", "cifar", "coco", "error", "top-5", "winner", "evaluation", "benchmark", "classification", "detection")),
        ("figure", ("figure", "chart", "plot", "evidence", "trajectory", "analysis", "scaling", "loss", "architecture", "evolution", "diagram", "block", "curve")),
        ("formula", ("positional", "encoding", "sinusoidal", "sine", "cosine", "wavelength", "offset", "linear function", "linear combination", "position")),
        ("method", ("method", "pipeline", "score", "select", "selection", "organize", "stream", "saw", "str", "attention", "transformer", "encoder", "decoder", "multi-head", "queries", "keys", "values", "residual", "shortcut", "identity", "bottleneck", "rnn", "lstm", "gru", "trained", "training")),
        ("guidance", ("boundary", "cyclic", "continuity", "diversity", "guidance", "rule", "framework", "jitter", "jit", "homogeneous", "brittle", "strictly sorted", "local diversity")),
        ("takeaway", ("takeaway", "toolbox", "validate", "closing", "core claim")),
        ("title", ("question", "asks", "answer", "paper asks", "deceptively simple", "paper title", "today we are reading", "influential machine learning paper", "attention is all you need", "by vaswani")),
    ]
    for role, keys in role_keys:
        if any(k in chunk_l for k in keys):
            roles.add(role)
    return roles


def has_explicit_cue_anchor(region: Region) -> bool:
    """Return true for regions deliberately labeled as cue targets.

    These labels come from ppt-master SVG/source markup such as a stable group
    id, `<title>`, `<desc>`, `aria-label`, or `data-cue-label`. We keep this
    conservative: ordinary slide text should not get the anchor bonus just
    because it happens to overlap with narration.
    """
    blob = f"{region.region_id} {region.text}".lower()
    return bool(region_anchor_ids(region)) or "data-cue-label" in blob or "visual cue" in blob or "highlight target" in blob


def anchor_ids_from_text(*values: str) -> list[str]:
    anchors: set[str] = set()
    for value in values:
        anchors.update(ANCHOR_RE.findall(value or ""))
    return sorted(anchors)


def region_anchor_ids(region: Region) -> list[str]:
    return anchor_ids_from_text(region.region_id, region.text, region.parent_id)


def is_table_row_region(region: Region) -> bool:
    blob = f"{region.region_id} {region.text} {region.parent_id}".lower()
    return (
        "row-" in region.region_id.lower()
        or "table-row" in blob
        or region.role == "table_row"
    )


def table_row_score(chunk_l: str, region: Region) -> tuple[float, list[str]]:
    """Prefer specific table rows over table-wide or takeaway text."""
    blob = f"{region.region_id} {region.text}".lower()
    is_row = is_table_row_region(region)
    in_table_context = any(
        key in chunk_l
        for key in (
            "table", "complexity", "per layer", "sequential", "path length",
            "self-attention", "recurrent", "rnn", "lstm", "gru",
            "convolutional", "kernel", "restricted", "o of", "o(",
        )
    )
    score = 0.0
    reasons: list[str] = []
    if is_row and in_table_context:
        score += 2.5
        reasons.append("table_row_context")

    row_specs = [
        ("row_self_attention", ("self-attention", "self attention", "attention layer"), ("self-attention", "self attention")),
        ("row_recurrent", ("recurrent", "rnn", "lstm", "gru"), ("recurrent", "rnn", "lstm", "gru")),
        ("row_convolutional", ("convolutional", "convolution", "kernel"), ("convolutional", "conv", "kernel")),
        ("row_restricted", ("restricted", "window"), ("restricted", "window")),
    ]
    primary_reason = ""
    primary_pos = 10**9
    for reason, chunk_keys, _row_keys in row_specs:
        positions = [chunk_l.find(key) for key in chunk_keys if chunk_l.find(key) >= 0]
        if positions and min(positions) < primary_pos:
            primary_pos = min(positions)
            primary_reason = reason

    for reason, chunk_keys, row_keys in row_specs:
        chunk_mentions = any(key in chunk_l for key in chunk_keys)
        row_mentions = any(key in blob for key in row_keys)
        if reason == "row_self_attention" and "restricted" in blob and not any(key in chunk_l for key in ("restricted", "window")):
            row_mentions = False
        if chunk_mentions and row_mentions and is_row:
            score += 11.0 if reason == primary_reason else 6.0
            reasons.append(reason)
        elif chunk_mentions and is_row and not row_mentions:
            if reason == primary_reason and primary_reason in {"row_recurrent", "row_convolutional", "row_restricted"}:
                score -= 13.0
            else:
                score -= 6.0 if reason == primary_reason else 2.2
            reasons.append(f"{reason}_mismatch")

    row_level_chunk = any(
        key in chunk_l
        for key in (
            "self-attention layer", "recurrent layer", "convolutional layer",
            "pays o", "sequential operations", "max path length",
        )
    )
    if row_level_chunk and ("takeaway" in blob or region.role == "takeaway"):
        score -= 9.0
        reasons.append("table_row_takeaway_penalty")
    if row_level_chunk and region.region_id.lower() in {"table", "table-area"}:
        score -= 7.0
        reasons.append("table_container_penalty")
    return score, reasons


def keyword_score(chunk: str, region: Region) -> tuple[float, list[str]]:
    chunk_l = chunk.lower()
    rid = region.region_id.lower()
    role = region.role
    area = region_area(region)
    wants_auxiliary_link = mentions_auxiliary_link(chunk)
    if role == "qr" and not wants_auxiliary_link:
        return -100.0, ["reject_qr_without_link_mention"]
    if region_is_chrome(region):
        return -100.0, ["reject_chrome"]

    score = 0.0
    reasons: list[str] = []
    table_bonus, table_reasons = table_row_score(chunk_l, region)
    if table_bonus:
        score += table_bonus
        reasons.extend(table_reasons)
    table = [
        (("question", "asks", "answer", "paper asks"), ("title", "cover"), 6),
        (("boundary", "late", "ending"), ("boundary",), 8),
        (("cyclic", "fold", "review"), ("cyclic", "review"), 8),
        (("continuity", "zig", "transition", "smooth"), ("continuity",), 8),
        (("diversity", "jitter", "jit", "perturb", "robust", "brittle"), ("diversity", "robust"), 8),
        (("score", "select", "selection", "organize", "training stream", "pipeline"), ("method", "pipeline", "comparison"), 5),
        (("str", "saw", "method", "permute", "stable", "transition"), ("method", "figure"), 5),
        (("result", "reaches", "random", "average", "gain", "outperform"), ("result", "kpi", "figure"), 6),
        (("attention", "transformer", "encoder", "decoder", "multi-head", "queries", "keys", "values", "positional", "feed-forward", "bottom up", "read it"), ("method", "figure", "paper-figure", "formula", "pillar", "point", "legend"), 6),
        (("positional", "encoding", "sinusoidal", "sine", "cosine", "wavelength", "offset", "position", "linear function", "linear combination"), ("formula", "equation", "figure", "result", "explanation"), 6),
        (("translation", "bleu", "training", "trained", "optimizer", "dropout", "label smoothing", "regularization", "ablation", "variation study", "table three", "takeaways"), ("result", "kpi", "card", "track", "item", "regularization", "optimizer", "training"), 6),
        (("rnn", "lstms", "gru", "recurrent", "convolutional", "sequence modeling"), ("method", "figure", "timeline", "comparison", "content"), 6),
        (("residual", "resnet", "shortcut", "identity", "plain", "degradation", "bottleneck", "deep"), ("method", "figure", "block", "architecture", "comparison"), 6),
        (("imagenet", "cifar", "coco", "voc", "top-5", "error", "accuracy", "winner", "ensemble"), ("result", "kpi", "figure", "chart", "curve", "metric"), 6),
        (("evaluation", "benchmark", "classification", "detection", "segmentation", "localization", "transfer"), ("result", "kpi", "figure", "benchmark", "card", "dataset"), 6),
        (("architecture", "diagram", "overview", "evolution", "sequence"), ("figure", "paper-figure", "timeline", "comparison", "content"), 5),
        (("scaling", "1.7", "loss", "scale", "larger"), ("scaling", "metric", "figure"), 6),
        (("figure", "evidence", "trajectory", "analysis"), ("figure", "evidence"), 5),
        (("qr", "code", "github", "repository", "repo", "arxiv", "link", "project page"), ("qr", "logo"), 7),
        (("takeaway", "toolbox", "selection", "validate"), ("takeaway", "qr"), 4),
    ]
    for chunk_keys, region_keys, weight in table:
        if any(k in chunk_l for k in chunk_keys) and (
            any(k in rid for k in region_keys) or role in region_keys
        ):
            score += weight
            reasons.append(f"keyword:{'/'.join(region_keys)}")
    for token in re.findall(r"[a-zA-Z0-9]+", rid):
        if len(token) > 3 and token in chunk_l:
            score += 2
            reasons.append(f"id_overlap:{token}")

    region_tokens = set(content_tokens(f"{region.region_id} {region.text}"))
    chunk_tokens = set(content_tokens(chunk))
    overlap = sorted(region_tokens & chunk_tokens)
    if overlap:
        lexical = min(5.0, len(overlap) * 0.9)
        score += lexical
        reasons.append("text_overlap:" + ",".join(overlap[:5]))
        if len(overlap) >= 2:
            score += 0.9
            reasons.append("dense_text_overlap")
        if region.source == "pptx" and region.text and MODULE_MIN_AREA <= area <= 0.18:
            score += 0.9
            reasons.append("precise_pptx_text_target")
        if has_explicit_cue_anchor(region):
            score += 1.6
            reasons.append("explicit_cue_anchor")

    expected = expected_roles(chunk)
    if role in expected:
        score += 3.0
        reasons.append(f"expected_role:{role}")
    elif expected and role in {"title", "header", "qr", "chrome", "caption"}:
        score -= 5.0
        reasons.append(f"role_mismatch:{role}")

    if role in {"figure", "result", "method", "guidance", "title", "text"}:
        score += 0.8
    if role == "header" and "title" not in expected:
        score -= 2.5
        reasons.append("header_penalty")
    if role == "caption" and not re.search(r"\bfigure\s+\d+\b", chunk_l):
        score -= 3.5
        reasons.append("caption_penalty")
    if region.source == "pptx":
        score += 0.8
        reasons.append("pptx_geometry")
    size_delta, size_reasons = module_size_adjustment(region)
    score += size_delta
    reasons.extend(size_reasons)
    return score, reasons


def confidence_from_score(score: float) -> float:
    return round(max(0.0, min(0.99, (score - 1.5) / 9.0)), 3)


def region_key(region: Region) -> str:
    return region.region_id.split(":", 1)[-1]


def parent_id_matches(parent: Region, child: Region) -> bool:
    if not child.parent_id:
        return False
    return region_key(parent) == child.parent_id or parent.region_id == child.parent_id


def region_debug_payload(region: Region, *, score: float | None = None,
                         reasons: list[str] | None = None,
                         limit_text: int = 180) -> dict:
    payload = {
        "target": region.region_id,
        "role": region.role,
        "source": region.source,
        "box": round_list(region.box),
        "area": round(region_area(region), 5),
        "parent_id": region.parent_id,
        "text": region.text[:limit_text],
    }
    if score is not None:
        payload["score"] = round(score, 3)
        payload["confidence"] = confidence_from_score(score)
    if reasons is not None:
        payload["reasons"] = reasons[:8]
    return payload


def semantic_candidate_report(scored: list[tuple[float, list[str], Region]], limit: int = 12) -> list[dict]:
    return [
        region_debug_payload(region, score=score, reasons=reasons)
        for score, reasons, region in scored[:limit]
    ]


def is_line_level_text_target(region: Region) -> bool:
    area = region_area(region)
    if region.role not in {"text", "content", "method", "takeaway"}:
        return False
    if looks_like_caption(region) or region.role in {"formula", "figure", "result", "qr", "title"}:
        return False
    _x, _y, w, h = region.box
    return (
        h <= 0.065
        and w >= 0.12
        and area <= 0.04
    ) or area < MODULE_MIN_AREA


def module_parent_candidates(region: Region, regions: list[Region]) -> list[Region]:
    parents = []
    for candidate in regions:
        if candidate.region_id == region.region_id and candidate.source == region.source:
            continue
        if candidate.slide_index != region.slide_index:
            continue
        if region_is_chrome(candidate) or looks_like_caption(candidate):
            continue
        if candidate.source != region.source and not (
            region.source == "svg" and candidate.source == "pptx"
        ):
            continue
        if not (parent_id_matches(candidate, region) or box_contains(candidate, region, tolerance=0.012)):
            continue
        area = region_area(candidate)
        if area <= region_area(region) * 1.04:
            continue
        if area > 0.24 and not is_named_module(candidate):
            continue
        if is_large_container(candidate) and not is_named_module(candidate):
            continue
        parents.append(candidate)
    return parents


def promote_semantic_region(region: Region, regions: list[Region], chunk: str) -> tuple[Region, dict | None]:
    if not is_line_level_text_target(region):
        return region, None
    parents = module_parent_candidates(region, regions)
    if not parents:
        return region, None

    chunk_tokens = set(content_tokens(chunk))

    def parent_rank(candidate: Region) -> tuple[float, float, float, float]:
        area = region_area(candidate)
        area_ratio = area / max(region_area(region), 1e-6)
        text_overlap = len(chunk_tokens & set(content_tokens(f"{candidate.region_id} {candidate.text}")))
        direct_parent = 1.0 if parent_id_matches(candidate, region) else 0.0
        module_bonus = 1.0 if is_named_module(candidate) or candidate.shape_type == "GROUP" else 0.0
        size_score = -abs(area - 0.07)
        ratio_penalty = -max(0.0, area_ratio - 5.0) * 0.04
        return (
            direct_parent * 3.0 + module_bonus * 1.2 + text_overlap * 0.25 + ratio_penalty,
            size_score,
            -area,
            -box_center_distance(region.box, candidate.box),
        )

    parents.sort(key=parent_rank, reverse=True)
    promoted = parents[0]
    if region_area(promoted) > 0.26:
        return region, None
    return promoted, {
        "from_target": region.region_id,
        "from_role": region.role,
        "from_source": region.source,
        "from_box": round_list(region.box),
        "to_target": promoted.region_id,
        "to_role": promoted.role,
        "to_source": promoted.source,
        "to_box": round_list(promoted.box),
        "reason": "line_text_promoted_to_module",
    }


def promote_geometry_region(region: Region, regions: list[Region]) -> tuple[Region, dict | None]:
    if region.source != "pptx" or not is_line_level_text_target(region):
        return region, None
    parents = module_parent_candidates(region, regions)
    if not parents:
        return region, None
    parents.sort(
        key=lambda candidate: (
            1 if parent_id_matches(candidate, region) else 0,
            1 if candidate.shape_type == "GROUP" or is_named_module(candidate) else 0,
            -abs(region_area(candidate) - 0.07),
            -region_area(candidate),
        ),
        reverse=True,
    )
    promoted = parents[0]
    if region_area(promoted) > 0.24:
        return region, None
    return promoted, {
        "from_target": region.region_id,
        "from_role": region.role,
        "from_source": region.source,
        "from_box": round_list(region.box),
        "to_target": promoted.region_id,
        "to_role": promoted.role,
        "to_source": promoted.source,
        "to_box": round_list(promoted.box),
        "reason": "line_geometry_promoted_to_module",
    }


def refine_module_choice(
    scored: list[tuple[float, list[str], Region]],
) -> tuple[float, list[str], Region]:
    """Prefer presentation-scale modules over word boxes or whole panels."""
    if not scored:
        raise ValueError("no scored regions available")
    score, reasons, region = scored[0]

    if is_micro_target(region) or looks_like_caption(region):
        parents = [
            item for item in scored[1:]
            if box_contains(item[2], region)
            and is_module_sized(item[2])
            and not looks_like_caption(item[2])
            and not is_micro_target(item[2])
        ]
        if parents:
            parents.sort(key=lambda item: (item[0], -region_area(item[2])), reverse=True)
            parent_score, parent_reasons, parent = parents[0]
            if parent_score >= score - 8.0:
                return (
                    parent_score,
                    [*parent_reasons[:6], f"module_parent_of:{region.region_id}"],
                    parent,
                )

    if is_large_container(region):
        children = [
            item for item in scored[1:]
            if box_contains(region, item[2])
            and is_module_sized(item[2])
            and not looks_like_caption(item[2])
            and not is_micro_target(item[2])
        ]
        viable = [item for item in children if item[0] >= max(3.8, score - 7.0)]
        if viable:
            viable.sort(
                key=lambda item: (
                    item[0],
                    1 if is_named_module(item[2]) else 0,
                    -abs(region_area(item[2]) - 0.06),
                ),
                reverse=True,
            )
            child_score, child_reasons, child = viable[0]
            return (
                child_score,
                [*child_reasons[:6], f"module_child_of:{region.region_id}"],
                child,
            )

    return score, reasons, region


def choose_region(chunk: str, regions: list[Region], fallback_idx: int, *, min_confidence: float) -> CueChoice:
    candidates = [r for r in regions if not region_is_chrome(r)]
    wants_auxiliary_link = mentions_auxiliary_link(chunk)
    if not wants_auxiliary_link:
        primary = [r for r in candidates if r.role != "qr"]
        if primary:
            candidates = primary
    if not candidates:
        candidates = regions
    if not candidates:
        raise ValueError("no regions available")

    scored = []
    for region in candidates:
        score, reasons = keyword_score(chunk, region)
        scored.append((score, reasons, region))
    scored.sort(key=lambda item: (item[0], -region_area(item[2])), reverse=True)
    candidate_report = semantic_candidate_report(scored)

    score, reasons, region = refine_module_choice(scored)
    confidence = confidence_from_score(score)
    if score <= 0:
        fallback = candidates[min(fallback_idx, len(candidates) - 1)]
        return CueChoice(
            region=fallback,
            score=score,
            confidence=confidence,
            accepted=False,
            reason="low_score_no_semantic_match",
            candidates=candidate_report,
        )
    if confidence < min_confidence:
        return CueChoice(
            region=region,
            score=score,
            confidence=confidence,
            accepted=False,
            reason="low_confidence:" + ";".join(reasons[:4]),
            candidates=candidate_report,
        )
    return CueChoice(
        region=region,
        score=score,
        confidence=confidence,
        accepted=True,
        reason=";".join(reasons[:5]) or "best_available_match",
        candidates=candidate_report,
    )


def choose_region_for_anchor(anchor_id: str, regions: list[Region], *, require_pptx_anchor: bool) -> CueChoice:
    candidates = [r for r in regions if not region_is_chrome(r)]
    exact = [r for r in candidates if anchor_id in region_anchor_ids(r)]
    if exact:
        exact.sort(
            key=lambda r: (
                1 if r.source == "pptx" else 0,
                -region_area(r),
            ),
            reverse=True,
        )
        candidate_report = [region_debug_payload(r, score=99.0, reasons=[f"exact_anchor:{anchor_id}"]) for r in exact[:12]]
        region = exact[0]
        if require_pptx_anchor and region.source != "pptx":
            return CueChoice(
                region=region,
                score=99.0,
                confidence=0.99,
                accepted=False,
                reason=f"exact_anchor_not_in_pptx:{anchor_id};source={region.source}",
                candidates=candidate_report,
            )
        return CueChoice(
            region=region,
            score=99.0,
            confidence=0.99,
            accepted=True,
            reason=f"exact_anchor:{anchor_id};source={region.source}",
            candidates=candidate_report,
        )
    fallback = candidates[0] if candidates else None
    return CueChoice(
        region=fallback,
        score=0.0,
        confidence=0.0,
        accepted=False,
        reason=f"anchor_missing:{anchor_id}",
        candidates=[region_debug_payload(r) for r in candidates[:12]],
    )


def load_anchor_contract(path: Path | None) -> dict[int, dict[int, dict]]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"[generate_visual_cues] anchor contract not found: {path}")
    except json.JSONDecodeError as exc:
        sys.exit(f"[generate_visual_cues] invalid anchor contract JSON {path}: {exc}")
    if payload.get("schema_version") not in {ANCHOR_CONTRACT_SCHEMA_VERSION, "paper2video_cue_requirements.v1"}:
        sys.exit(f"[generate_visual_cues] unsupported anchor contract schema: {payload.get('schema_version')}")
    out: dict[int, dict[int, dict]] = {}
    for slide in payload.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        try:
            slide_index = int(slide.get("index"))
        except (TypeError, ValueError):
            continue
        chunks: dict[int, dict] = {}
        for chunk in slide.get("chunks") or []:
            if not isinstance(chunk, dict):
                continue
            try:
                chunk_index = int(chunk.get("chunk_index"))
            except (TypeError, ValueError):
                continue
            anchor_id = str(chunk.get("anchor_id") or "").strip()
            if not anchor_id:
                continue
            chunks[chunk_index] = chunk
        if chunks:
            out[slide_index] = chunks
    return out


def find_tool(name: str) -> str | None:
    return shutil.which(name)


def imageio_ffmpeg_binary() -> str | None:
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def find_ffmpeg_pair() -> tuple[str | None, str | None]:
    env_ffmpeg = os.getenv("PAPER2VIDEO_FFMPEG") or os.getenv("FFMPEG_BINARY")
    if env_ffmpeg and Path(env_ffmpeg).expanduser().is_file():
        env_ffprobe = os.getenv("PAPER2VIDEO_FFPROBE")
        if env_ffprobe and Path(env_ffprobe).expanduser().is_file():
            return str(Path(env_ffmpeg).expanduser()), str(Path(env_ffprobe).expanduser())
        return str(Path(env_ffmpeg).expanduser()), str(Path(env_ffmpeg).expanduser())

    fallback = imageio_ffmpeg_binary()
    if fallback:
        return fallback, fallback

    ffmpeg = find_tool("ffmpeg")
    ffprobe = find_tool("ffprobe")
    if ffmpeg and ffprobe:
        return ffmpeg, ffprobe
    if ffmpeg:
        return ffmpeg, ffmpeg
    return None, None


def probe_duration(audio: Path) -> float:
    ffmpeg, ffprobe = find_ffmpeg_pair()
    if ffprobe and ffmpeg and ffprobe != ffmpeg:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
            capture_output=True,
            text=True,
        )
        if out.returncode == 0 and out.stdout.strip():
            return float(out.stdout.strip())
    if ffmpeg:
        out = subprocess.run([ffmpeg, "-i", str(audio)], capture_output=True, text=True)
        m = re.search(r"Duration:\s+(\d+):(\d+):([\d.]+)", out.stderr)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    raise RuntimeError(f"could not probe duration for {audio}")


def estimate_duration(text: str, words_per_minute: float) -> float:
    words = max(1, len(re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text)))
    return max(2.5, words / words_per_minute * 60.0)


def load_durations(sections: list[Section], audio_dir: Path | None,
                   *, estimate: bool, words_per_minute: float) -> dict[str, float]:
    durations: dict[str, float] = {}
    for sec in sections:
        audio = audio_dir / f"{sec.sid}.mp3" if audio_dir else None
        if audio and audio.is_file():
            durations[sec.sid] = probe_duration(audio)
        elif estimate:
            durations[sec.sid] = estimate_duration(sec.text, words_per_minute)
        else:
            raise FileNotFoundError(
                f"missing audio for {sec.sid}; pass --estimate-durations only for scaffolding"
            )
    return durations


def allocate_times(chunks: list[str], duration: float) -> list[tuple[float, float]]:
    if not chunks:
        return []
    start_base = 0.35 if duration > 3.0 else 0.0
    end_cap = max(start_base + 0.25, duration - 0.25)
    gap = 0.12 if len(chunks) > 1 else 0.0
    usable = max(0.25, end_cap - start_base - gap * (len(chunks) - 1))
    weights = [max(1.0, math.sqrt(len(c))) for c in chunks]
    total = sum(weights)
    out = []
    cursor = start_base
    for weight in weights:
        span = usable * weight / total
        out.append((round(cursor, 3), round(cursor + span, 3)))
        cursor += span + gap
    return out


def round_list(values: Iterable[float], digits: int = 4) -> list[float]:
    return [round(float(v), digits) for v in values]


def generate(project: Path, *, svg_dir: Path, sections: list[Section],
             durations: dict[str, float], max_cues: int, color: str,
             opacity: float, size: int, pptx_payload: dict | None = None,
             word_timings: dict[str, list[dict]] | None = None,
             min_confidence: float = 0.38, strict_gate: bool = False,
             require_timestamps: bool = False,
             anchor_contract: dict[int, dict[int, dict]] | None = None,
             require_pptx_anchors: bool = False,
             prefer_pptx_geometry: bool = True,
             pptx_geometry_min_score: float = PPTX_GEOMETRY_MIN_SCORE) -> tuple[dict, dict, dict, dict, dict]:
    svg_files = sorted(svg_dir.glob("*.svg"))
    if len(svg_files) != len(sections):
        raise ValueError(
            f"slide/script count mismatch: {len(svg_files)} svg files vs {len(sections)} narration sections"
        )

    all_region_entries = []
    cues_payload = {
        "schema_version": SCHEMA_VERSION,
        "cue_shape": "semantic_box",
        "slides": [],
    }
    audit = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "project": str(project),
        "slides": [],
        "errors": [],
        "warnings": [],
    }
    cue_plan = {
        "schema_version": CUE_PLAN_SCHEMA_VERSION,
        "project": str(project),
        "min_confidence": min_confidence,
        "strict_gate": strict_gate,
        "anchor_contract_enabled": bool(anchor_contract),
        "require_pptx_anchors": require_pptx_anchors,
        "prefer_pptx_geometry": prefer_pptx_geometry,
        "pptx_geometry_min_score": pptx_geometry_min_score,
        "slides": [],
        "errors": [],
        "warnings": [],
    }
    geometry_report = {
        "schema_version": "paper2video_geometry_resolution.v1",
        "project": str(project),
        "prefer_pptx_geometry": prefer_pptx_geometry,
        "pptx_geometry_min_score": pptx_geometry_min_score,
        "slides": [],
        "summary": {
            "cue_count": 0,
            "pptx_geometry_count": 0,
            "pptx_cluster_geometry_count": 0,
            "semantic_fallback_count": 0,
        },
    }
    if pptx_payload is None:
        cue_plan["warnings"].append("pptx_element_registry_missing; using SVG groups only")

    for svg, sec in zip(svg_files, sections):
        slide_id, width, height, svg_regions = extract_regions(svg, sec.index)
        pptx_regions = regions_from_pptx_payload(pptx_payload, slide_index=sec.index, slide_id=slide_id)
        regions = merge_regions(svg_regions, pptx_regions)
        if not regions:
            raise ValueError(f"no selectable regions found in {svg}")

        all_region_entries.append({
            "index": sec.index,
            "id": sec.sid,
            "svg": svg.name,
            "canvas": [width, height],
            "source_counts": {
                "svg": len(svg_regions),
                "pptx": len(pptx_regions),
                "merged": len(regions),
            },
            "regions": [
                {
                    "id": r.region_id,
                    "role": r.role,
                    "source": r.source,
                    "shape_type": r.shape_type,
                    "parent_id": r.parent_id,
                    "cue_anchors": region_anchor_ids(r),
                    "box": round_list(r.box),
                    "point": round_list(r.point),
                    "text": r.text,
                }
                for r in regions
            ],
        })

        chunks = chunk_sentences(split_sentences(sec.text), max_cues)
        times, timing_source, timing_details = allocate_times_from_words(
            chunks,
            durations[sec.sid],
            (word_timings or {}).get(sec.sid),
        )
        timing_detail_by_chunk = {
            int(detail.get("chunk_index") or 0): detail
            for detail in timing_details
            if isinstance(detail, dict)
        }
        if require_timestamps and not word_timing_source(timing_source):
            msg = f"slide {sec.index} {sec.sid} has no word-boundary timing; got {timing_source}"
            cue_plan["errors"].append(msg)
            audit["errors"].append(msg)
        cue_entries = []
        audit_entries = []
        plan_entries = []
        geometry_entries = []
        slide_contract = (anchor_contract or {}).get(sec.index, {})
        if anchor_contract and not slide_contract:
            msg = f"slide {sec.index} has no anchor contract entries"
            cue_plan["warnings"].append(msg)
            if strict_gate:
                cue_plan["errors"].append(msg)
                audit["errors"].append(msg)
        for idx, (chunk, (start, end)) in enumerate(zip(chunks, times)):
            anchor_entry = slide_contract.get(idx + 1) if isinstance(slide_contract, dict) else None
            anchor_id = str((anchor_entry or {}).get("anchor_id") or "").strip()
            if anchor_contract and not anchor_id:
                msg = f"slide {sec.index} chunk {idx + 1} has no anchor_id in contract"
                cue_plan["warnings"].append(msg)
                if strict_gate:
                    cue_plan["errors"].append(msg)
                    audit["errors"].append(msg)
            if anchor_id:
                choice = choose_region_for_anchor(anchor_id, regions, require_pptx_anchor=require_pptx_anchors)
            else:
                choice = choose_region(chunk, regions, idx, min_confidence=min_confidence)
            region = choice.region
            promotion = None
            original_region = region
            if choice.accepted and region is not None:
                region, promotion = promote_semantic_region(region, regions, chunk)
                if promotion:
                    choice.reason = f"{choice.reason};{promotion['reason']}"
            if not choice.accepted:
                msg = f"slide {sec.index} chunk {idx + 1} skipped: {choice.reason}"
                cue_plan["warnings"].append(msg)
                if strict_gate:
                    cue_plan["errors"].append(msg)
                    audit["errors"].append(msg)
            cue = None
            if choice.accepted and region is not None:
                geometry = resolve_geometry_choice(
                    region,
                    regions,
                    chunk,
                    prefer_pptx_geometry=prefer_pptx_geometry,
                    min_score=pptx_geometry_min_score,
                )
                geometry_report["summary"]["cue_count"] += 1
                if geometry.source == "pptx":
                    geometry_report["summary"]["pptx_geometry_count"] += 1
                elif geometry.source == "pptx_cluster":
                    geometry_report["summary"]["pptx_cluster_geometry_count"] += 1
                else:
                    geometry_report["summary"]["semantic_fallback_count"] += 1
                cue = {
                    "start": start,
                    "end": end,
                    "type": "highlight",
                    "box": round_list(geometry.box),
                    "point": round_list(geometry.point),
                    "color": color,
                    "opacity": opacity,
                    "size": size,
                    "target": region.region_id,
                    "target_role": region.role,
                    "target_source": region.source,
                    "semantic_original_target": original_region.region_id if original_region else None,
                    "semantic_promoted": bool(promotion),
                    "semantic_promotion": promotion,
                    "semantic_target": region.region_id,
                    "semantic_role": region.role,
                    "semantic_source": region.source,
                    "semantic_box": round_list(region.box),
                    "geometry_target": geometry.target,
                    "geometry_role": geometry.role,
                    "geometry_source": geometry.source,
                    "geometry_box": round_list(geometry.box),
                    "geometry_matched": geometry.matched,
                    "geometry_match_score": geometry.score,
                    "geometry_match_iou": geometry.iou,
                    "geometry_semantic_coverage": geometry.semantic_coverage,
                    "geometry_coverage": geometry.geometry_coverage,
                    "geometry_match_reason": geometry.reason,
                    "semantic_candidates": choice.candidates,
                    "geometry_candidates": geometry.candidates,
                    "confidence": choice.confidence,
                    "anchor_id": anchor_id or None,
                    "anchor_matched": bool(anchor_id),
                }
                cue_entries.append(cue)
                geometry_entries.append({
                    "chunk_index": idx + 1,
                    "timing": timing_detail_by_chunk.get(idx + 1, {}),
                    "semantic_target": region.region_id,
                    "semantic_original_target": original_region.region_id if original_region else None,
                    "semantic_promoted": bool(promotion),
                    "semantic_promotion": promotion,
                    "semantic_source": region.source,
                    "semantic_role": region.role,
                    "semantic_box": round_list(region.box),
                    "geometry_target": geometry.target,
                    "geometry_source": geometry.source,
                    "geometry_role": geometry.role,
                    "geometry_box": round_list(geometry.box),
                    "matched": geometry.matched,
                    "score": geometry.score,
                    "iou": geometry.iou,
                    "semantic_coverage": geometry.semantic_coverage,
                    "geometry_coverage": geometry.geometry_coverage,
                    "reason": geometry.reason,
                    "candidates": geometry.candidates,
                })
            else:
                geometry = None
            plan_entry = {
                "chunk_index": idx + 1,
                "chunk_id": (anchor_entry or {}).get("chunk_id"),
                "text": chunk,
                "start": start,
                "end": end,
                "seconds": round(end - start, 3),
                "timing_source": timing_source,
                "timing": timing_detail_by_chunk.get(idx + 1, {}),
                "accepted": choice.accepted,
                "score": round(choice.score, 3),
                "confidence": choice.confidence,
                "reason": choice.reason,
                "anchor_id": anchor_id or None,
                "anchor_required": bool(anchor_id),
                "anchor_matched": bool(anchor_id and choice.accepted),
                "target": region.region_id if region else None,
                "target_role": region.role if region else None,
                "target_source": region.source if region else None,
                "semantic_original_target": original_region.region_id if original_region else None,
                "semantic_promoted": bool(promotion),
                "semantic_promotion": promotion,
                "semantic_target": region.region_id if region else None,
                "semantic_role": region.role if region else None,
                "semantic_source": region.source if region else None,
                "semantic_box": round_list(region.box) if region else None,
                "point": round_list(geometry.point) if geometry else (round_list(region.point) if region else None),
                "region_box": round_list(geometry.box) if geometry else (round_list(region.box) if region else None),
                "geometry_target": geometry.target if geometry else None,
                "geometry_role": geometry.role if geometry else None,
                "geometry_source": geometry.source if geometry else None,
                "geometry_box": round_list(geometry.box) if geometry else None,
                "geometry_matched": geometry.matched if geometry else False,
                "geometry_match_score": geometry.score if geometry else None,
                "geometry_match_iou": geometry.iou if geometry else None,
                "geometry_semantic_coverage": geometry.semantic_coverage if geometry else None,
                "geometry_coverage": geometry.geometry_coverage if geometry else None,
                "geometry_match_reason": geometry.reason if geometry else None,
                "semantic_candidates": choice.candidates,
                "geometry_candidates": geometry.candidates if geometry else [],
            }
            plan_entries.append(plan_entry)
            audit_entries.append({
                "text": chunk,
                "accepted": choice.accepted,
                "target": region.region_id if region else "",
                "role": region.role if region else "",
                "source": region.source if region else "",
                "semantic_original_target": original_region.region_id if original_region else "",
                "semantic_promoted": bool(promotion),
                "semantic_promotion": promotion,
                "semantic_candidates": choice.candidates,
                "semantic_box": round_list(region.box) if region else [],
                "geometry_target": geometry.target if geometry else "",
                "geometry_source": geometry.source if geometry else "",
                "geometry_box": round_list(geometry.box) if geometry else [],
                "geometry_matched": geometry.matched if geometry else False,
                "geometry_match_score": geometry.score if geometry else None,
                "geometry_match_iou": geometry.iou if geometry else None,
                "geometry_match_reason": geometry.reason if geometry else "",
                "geometry_candidates": geometry.candidates if geometry else [],
                "confidence": choice.confidence,
                "reason": choice.reason,
                "anchor_id": anchor_id or "",
                "anchor_matched": bool(anchor_id and choice.accepted),
                "timing": timing_detail_by_chunk.get(idx + 1, {}),
                "point": round_list(geometry.point) if geometry else (round_list(region.point) if region else []),
                "region_box": round_list(geometry.box) if geometry else (round_list(region.box) if region else []),
                "start": start,
                "end": end,
                "seconds": round(end - start, 3),
            })

        # Union single-line title/tagline fragments so the cue box is the whole
        # wrapped unit (renderer's ink-tighten then hugs all the lines). Multi-line
        # paragraph blocks are never merged, preserving the script's progression.
        union_wrapped_line_cues(cue_entries, regions)
        cues_payload["slides"].append({
            "index": sec.index,
            "id": sec.sid,
            "source_svg": svg.name,
            "cues": cue_entries,
        })
        audit["slides"].append({
            "index": sec.index,
            "id": sec.sid,
            "heading": sec.heading,
            "audio_seconds": round(durations[sec.sid], 3),
            "cue_count": len(cue_entries),
            "timing_source": timing_source,
            "timing_details": timing_details,
            "cues": audit_entries,
        })
        cue_plan["slides"].append({
            "index": sec.index,
            "id": sec.sid,
            "heading": sec.heading,
            "source_svg": svg.name,
            "timing_source": timing_source,
            "timing_details": timing_details,
            "cue_count": len(cue_entries),
            "chunks": plan_entries,
        })
        geometry_report["slides"].append({
            "index": sec.index,
            "id": sec.sid,
            "source_svg": svg.name,
            "entries": geometry_entries,
        })

    regions_payload = {
        "schema_version": REGIONS_SCHEMA_VERSION,
        "slides": all_region_entries,
    }
    return cues_payload, regions_payload, audit, cue_plan, geometry_report


def validate_payload(cues_payload: dict, audit: dict) -> None:
    errors = []
    for slide in cues_payload.get("slides", []):
        for cue in slide.get("cues", []):
            box = cue.get("box")
            point = cue.get("point")
            if box is None and point is None:
                errors.append(f"slide {slide.get('index')} cue missing box/point")
                continue
            if box is not None:
                if not isinstance(box, list) or len(box) != 4:
                    errors.append(f"slide {slide.get('index')} cue box must be [x,y,w,h]")
                elif not all(isinstance(v, (int, float)) for v in box):
                    errors.append(f"slide {slide.get('index')} cue box must be numeric: {box}")
                else:
                    x, y, w, h = [float(v) for v in box]
                    if w <= 0 or h <= 0:
                        errors.append(f"slide {slide.get('index')} cue box has non-positive size: {box}")
                    if x < 0 or y < 0 or x + w > 1.0001 or y + h > 1.0001:
                        errors.append(f"slide {slide.get('index')} cue box out of range: {box}")
            if point is not None:
                if not isinstance(point, list) or len(point) != 2:
                    errors.append(f"slide {slide.get('index')} cue point must be [x,y]")
                elif not all(isinstance(v, (int, float)) and 0 <= float(v) <= 1 for v in point):
                    errors.append(f"slide {slide.get('index')} cue point out of range: {point}")
            if float(cue.get("end", 0)) <= float(cue.get("start", 0)):
                errors.append(f"slide {slide.get('index')} cue has non-positive time span")
    if errors:
        audit.setdefault("errors", []).extend(errors)
        raise ValueError("; ".join(errors))


def repair_suggestions(reason: str, timing_source: str, target_role: str | None) -> list[str]:
    suggestions: list[str] = []
    if "low_confidence" in reason or "low_score_no_semantic_match" in reason:
        suggestions.append(
            "Add an explicit cue anchor to the intended SVG/PPT visual: stable group id, "
            "<title>/<desc>, or data-cue-label containing the narration keywords."
        )
        suggestions.append(
            "Align the speaker-note sentence with the visible slide language, or split the sentence "
            "so each chunk refers to one clear visual target."
        )
    if target_role in {"header", "caption", "chrome", "footer"}:
        suggestions.append(
            "Retarget the cue from slide chrome/header/caption to a content region such as a method, "
            "result, figure, or takeaway group."
        )
    if "large_container_penalty" in reason:
        suggestions.append(
            "Create a smaller semantic group around the specific visual part being discussed; avoid "
            "using a whole-column or whole-slide container as the cue target."
        )
    if timing_source != "edge_word_boundaries":
        suggestions.append(
            "Regenerate audio with generate_edge_audio.py --timings-out and rerun with --require-timestamps."
        )
    if not suggestions:
        suggestions.append("Review the cue_audit.html preview and add a more precise semantic anchor.")
    return suggestions


def build_repair_requests(cue_plan: dict, regions_payload: dict, audit: dict) -> dict:
    region_index = {
        int(slide.get("index")): slide.get("regions", [])
        for slide in regions_payload.get("slides", [])
        if isinstance(slide, dict) and isinstance(slide.get("index"), int)
    }
    requests = []
    for slide in cue_plan.get("slides", []):
        if not isinstance(slide, dict):
            continue
        slide_index = int(slide.get("index") or 0)
        chunks = slide.get("chunks") or []
        failed = [c for c in chunks if isinstance(c, dict) and not c.get("accepted")]
        if not failed:
            continue
        candidate_regions = []
        for region in region_index.get(slide_index, [])[:18]:
            if isinstance(region, dict):
                candidate_regions.append({
                    "id": region.get("id"),
                    "role": region.get("role"),
                    "source": region.get("source"),
                    "point": region.get("point"),
                    "box": region.get("box"),
                    "text": str(region.get("text") or "")[:180],
                })
        requests.append({
            "slide_index": slide_index,
            "slide_id": slide.get("id"),
            "heading": slide.get("heading"),
            "timing_source": slide.get("timing_source"),
            "failed_chunks": [
                {
                    "chunk_index": c.get("chunk_index"),
                    "text": c.get("text"),
                    "start": c.get("start"),
                    "end": c.get("end"),
                    "confidence": c.get("confidence"),
                    "score": c.get("score"),
                    "reason": c.get("reason"),
                    "best_rejected_target": c.get("target"),
                    "best_rejected_role": c.get("target_role"),
                    "best_rejected_source": c.get("target_source"),
                    "suggestions": repair_suggestions(
                        str(c.get("reason") or ""),
                        str(slide.get("timing_source") or ""),
                        str(c.get("target_role") or "") if c.get("target_role") else None,
                    ),
                }
                for c in failed
            ],
            "candidate_regions": candidate_regions,
        })
    blocking_errors = list(dict.fromkeys(
        [str(e) for e in (cue_plan.get("errors") or [])]
        + [str(e) for e in (audit.get("errors") or [])]
    ))
    return {
        "schema_version": REPAIR_SCHEMA_VERSION,
        "project": cue_plan.get("project"),
        "summary": {
            "slides_needing_repair": len(requests),
            "failed_chunks": sum(len(r["failed_chunks"]) for r in requests),
            "cue_plan_errors": len(cue_plan.get("errors") or []),
            "audit_errors": len(audit.get("errors") or []),
        },
        "blocking_errors": blocking_errors,
        "requests": requests,
    }


def write_repair_markdown(repair: dict, path: Path) -> None:
    summary = repair.get("summary", {})
    failed_chunks = int(summary.get("failed_chunks") or 0)
    blocking_errors = repair.get("blocking_errors") or []
    if failed_chunks == 0 and not blocking_errors:
        lines = [
            "# paper2video cue repair status",
            "",
            "Strict visual-cue generation passed. No repair requests are open.",
            "",
            f"- Slides needing repair: {summary.get('slides_needing_repair', 0)}",
            f"- Failed chunks: {failed_chunks}",
            "",
        ]
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return

    lines = [
        "# paper2video cue repair requests",
        "",
        "Strict visual-cue generation failed. Do not render a highlighted video until these requests are resolved and the strict gate passes.",
        "",
        f"- Slides needing repair: {summary.get('slides_needing_repair', 0)}",
        f"- Failed chunks: {failed_chunks}",
        "",
    ]
    errors = blocking_errors
    if errors:
        lines.extend(["## Blocking Errors", ""])
        for err in errors:
            lines.append(f"- {err}")
        lines.append("")
    for req in repair.get("requests", []):
        lines.extend([
            f"## Slide {int(req.get('slide_index') or 0):02d}: {req.get('slide_id')}",
            "",
            f"Heading: {req.get('heading') or ''}",
            f"Timing source: `{req.get('timing_source') or ''}`",
            "",
        ])
        for chunk in req.get("failed_chunks", []):
            lines.extend([
                f"### Chunk {chunk.get('chunk_index')}",
                "",
                f"> {chunk.get('text') or ''}",
                "",
                f"- Confidence: `{chunk.get('confidence')}`; score: `{chunk.get('score')}`",
                f"- Reason: `{chunk.get('reason')}`",
                f"- Best rejected target: `{chunk.get('best_rejected_target')}` ({chunk.get('best_rejected_role')}, {chunk.get('best_rejected_source')})",
                "- Suggested fixes:",
            ])
            for suggestion in chunk.get("suggestions") or []:
                lines.append(f"  - {suggestion}")
            lines.append("")
        candidates = req.get("candidate_regions") or []
        if candidates:
            lines.extend(["Candidate regions visible to the matcher:", ""])
            for region in candidates[:10]:
                text = str(region.get("text") or "").replace("\n", " ")[:120]
                lines.append(f"- `{region.get('id')}` role=`{region.get('role')}` source=`{region.get('source')}` text=\"{text}\"")
            lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def find_preview_image(preview_dir: Path | None, slide: dict) -> Path | None:
    if preview_dir is None or not preview_dir.is_dir():
        return None
    sid = str(slide.get("id") or "")
    index = int(slide.get("index") or 0)
    candidates = [
        preview_dir / f"{sid}.png",
        preview_dir / f"{sid}.jpg",
        preview_dir / f"{index:02d}_{sid}.png",
        preview_dir / f"slide-{index}.png",
        preview_dir / f"slide-{index:02d}.png",
        preview_dir / f"slide-{index:06d}.png",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    matches = sorted(preview_dir.glob(f"{index:02d}_*.png"))
    return matches[0] if matches else None


def write_html_audit(audit: dict, path: Path, preview_dir: Path | None = None) -> None:
    rows = []
    sections = []
    for slide in audit.get("slides", []):
        preview = find_preview_image(preview_dir, slide)
        rel_preview = None
        if preview:
            rel_preview = os.path.relpath(preview, path.parent)
        dots = []
        for cue in slide.get("cues", []):
            status = "accepted" if cue.get("accepted") else "skipped"
            rows.append(
                "<tr>"
                f"<td>{slide['index']:02d}</td>"
                f"<td>{html.escape(slide['id'])}</td>"
                f"<td>{cue['start']:.2f}-{cue['end']:.2f}s</td>"
                f"<td>{html.escape(status)}</td>"
                f"<td>{html.escape(str(cue.get('confidence', '')))}</td>"
                f"<td>{html.escape(cue['target'])}</td>"
                f"<td>{html.escape(cue['text'])}</td>"
                "</tr>"
            )
            box = cue.get("region_box")
            point = cue.get("point")
            if cue.get("accepted") and isinstance(box, list) and len(box) == 4:
                dots.append(
                    f"<span class=\"box\" title=\"{html.escape(cue['target'])}\" "
                    f"style=\"left:{float(box[0]) * 100:.2f}%;top:{float(box[1]) * 100:.2f}%;"
                    f"width:{float(box[2]) * 100:.2f}%;height:{float(box[3]) * 100:.2f}%\"></span>"
                )
            elif cue.get("accepted") and isinstance(point, list) and len(point) == 2:
                dots.append(
                    f"<span class=\"dot\" title=\"{html.escape(cue['target'])}\" "
                    f"style=\"left:{float(point[0]) * 100:.2f}%;top:{float(point[1]) * 100:.2f}%\"></span>"
                )
        if rel_preview:
            sections.append(
                "<section class=\"slide-card\">"
                f"<h2>{slide['index']:02d}. {html.escape(slide['id'])}"
                f" <span>{html.escape(str(slide.get('timing_source', '')))}</span></h2>"
                "<div class=\"preview\">"
                f"<img src=\"{html.escape(rel_preview)}\" alt=\"slide {slide['index']} preview\">"
                + "".join(dots) +
                "</div>"
                "</section>"
            )
    doc = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>paper2video cue audit</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; color: #10201E; }
    h1 { margin-bottom: 4px; }
    h2 { font-size: 18px; margin: 0 0 10px; }
    h2 span { color: #667; font-weight: 400; font-size: 13px; margin-left: 8px; }
    .slides { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 18px; margin: 22px 0 30px; }
    .slide-card { border: 1px solid #C9D7D2; border-radius: 8px; padding: 12px; background: #FAFCFB; }
    .preview { position: relative; aspect-ratio: 16 / 9; background: #E7ECEA; overflow: hidden; }
    .preview img { display: block; width: 100%; height: 100%; object-fit: contain; }
    .box { position: absolute; border: 3px solid rgba(100, 116, 139, 0.68); background: rgba(100, 116, 139, 0.18); box-shadow: 0 0 0 1px rgba(16, 32, 30, 0.12); pointer-events: none; }
    .dot { position: absolute; width: 9.5%; aspect-ratio: 1; transform: translate(-50%, -50%); border-radius: 999px; background: rgba(242, 193, 78, 0.34); box-shadow: 0 0 0 2px rgba(242, 193, 78, 0.9); pointer-events: none; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #C9D7D2; padding: 8px 10px; vertical-align: top; }
    th { background: #EAF1EF; text-align: left; }
    td:nth-child(1), td:nth-child(3), td:nth-child(4), td:nth-child(5) { white-space: nowrap; }
    .skipped { color: #8A4B00; }
  </style>
</head>
<body>
  <h1>paper2video cue audit</h1>
  <p>Accepted rows are the only cues written to visual_cues.json. Skipped rows were judged too uncertain for rendering.</p>
  <div class="slides">
""" + "\n".join(sections) + """
  </div>
  <table>
    <thead><tr><th>Slide</th><th>ID</th><th>Time</th><th>Status</th><th>Confidence</th><th>Target region</th><th>Narration chunk</th></tr></thead>
    <tbody>
""" + "\n".join(rows) + """
    </tbody>
  </table>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


def css_box(box: list | tuple, *, extra: str = "") -> str:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return ""
    return (
        f"left:{float(box[0]) * 100:.2f}%;top:{float(box[1]) * 100:.2f}%;"
        f"width:{float(box[2]) * 100:.2f}%;height:{float(box[3]) * 100:.2f}%;{extra}"
    )


def candidate_rows(candidates: list[dict], *, label: str) -> str:
    if not candidates:
        return f"<p class=\"empty\">No {html.escape(label)} candidates recorded.</p>"
    rows = []
    for idx, cand in enumerate(candidates[:8], start=1):
        reasons = "; ".join(str(r) for r in (cand.get("reasons") or [])[:4])
        rows.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{html.escape(str(cand.get('target') or ''))}</td>"
            f"<td>{html.escape(str(cand.get('source') or ''))}</td>"
            f"<td>{html.escape(str(cand.get('role') or ''))}</td>"
            f"<td>{html.escape(str(cand.get('score') if cand.get('score') is not None else ''))}</td>"
            f"<td>{html.escape(str(cand.get('iou') if cand.get('iou') is not None else ''))}</td>"
            f"<td>{html.escape(str(cand.get('area') if cand.get('area') is not None else ''))}</td>"
            f"<td>{html.escape(reasons)}</td>"
            "</tr>"
        )
    return (
        f"<h4>{html.escape(label)}</h4>"
        "<table class=\"candidates\"><thead><tr>"
        "<th>#</th><th>Target</th><th>Source</th><th>Role</th><th>Score</th><th>IoU</th><th>Area</th><th>Reasons</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def write_candidate_review_html(audit: dict, path: Path, preview_dir: Path | None = None) -> None:
    sections = []
    for slide in audit.get("slides", []):
        preview = find_preview_image(preview_dir, slide)
        rel_preview = os.path.relpath(preview, path.parent) if preview else None
        overlays = []
        cards = []
        for cue in slide.get("cues", []):
            chunk_idx = int(cue.get("chunk_index") or len(cards) + 1)
            semantic_box = cue.get("semantic_box")
            geometry_box = cue.get("geometry_box") or cue.get("region_box")
            if cue.get("accepted") and isinstance(semantic_box, list) and len(semantic_box) == 4:
                overlays.append(
                    f"<span class=\"semantic box\" title=\"chunk {chunk_idx} semantic {html.escape(str(cue.get('target') or ''))}\" "
                    f"style=\"{css_box(semantic_box)}\"></span>"
                )
            if cue.get("accepted") and isinstance(geometry_box, list) and len(geometry_box) == 4:
                overlays.append(
                    f"<span class=\"geometry box\" title=\"chunk {chunk_idx} geometry {html.escape(str(cue.get('geometry_target') or ''))}\" "
                    f"style=\"{css_box(geometry_box)}\"></span>"
                )
            timing = cue.get("timing") if isinstance(cue.get("timing"), dict) else {}
            promotion = cue.get("semantic_promotion") if isinstance(cue.get("semantic_promotion"), dict) else None
            promotion_text = ""
            if promotion:
                promotion_text = (
                    f"<p><b>Promotion:</b> {html.escape(str(promotion.get('from_target') or ''))}"
                    f" -> {html.escape(str(promotion.get('to_target') or ''))}"
                    f" <code>{html.escape(str(promotion.get('reason') or ''))}</code></p>"
                )
            cards.append(
                "<article class=\"chunk\">"
                f"<h3>Chunk {chunk_idx} <span>{float(cue.get('start') or 0):.2f}-{float(cue.get('end') or 0):.2f}s</span></h3>"
                f"<p class=\"narration\">{html.escape(str(cue.get('text') or ''))}</p>"
                f"<p><b>Timing:</b> {html.escape(str(timing.get('method') or ''))}"
                f" score={html.escape(str(timing.get('score') if timing.get('score') is not None else ''))}"
                f" words={html.escape(str(timing.get('start_word') or ''))} -> {html.escape(str(timing.get('end_word') or ''))}</p>"
                f"<p><b>Semantic:</b> {html.escape(str(cue.get('target') or ''))}"
                f" ({html.escape(str(cue.get('source') or ''))}/{html.escape(str(cue.get('role') or ''))})</p>"
                f"{promotion_text}"
                f"<p><b>Geometry:</b> {html.escape(str(cue.get('geometry_target') or ''))}"
                f" ({html.escape(str(cue.get('geometry_source') or ''))})"
                f" score={html.escape(str(cue.get('geometry_match_score') if cue.get('geometry_match_score') is not None else ''))}"
                f" iou={html.escape(str(cue.get('geometry_match_iou') if cue.get('geometry_match_iou') is not None else ''))}</p>"
                + candidate_rows(cue.get("semantic_candidates") or [], label="Semantic candidates")
                + candidate_rows(cue.get("geometry_candidates") or [], label="Geometry candidates")
                + "</article>"
            )
        preview_html = ""
        if rel_preview:
            preview_html = (
                "<div class=\"preview\">"
                f"<img src=\"{html.escape(rel_preview)}\" alt=\"slide {slide.get('index')} preview\">"
                + "".join(overlays)
                + "</div>"
            )
        sections.append(
            "<section class=\"slide\">"
            f"<h2>{int(slide.get('index') or 0):02d}. {html.escape(str(slide.get('id') or ''))}"
            f" <span>{html.escape(str(slide.get('timing_source') or ''))}</span></h2>"
            + preview_html
            + "".join(cards)
            + "</section>"
        )
    doc = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>paper2video cue candidate review</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; color: #17202A; background: #F7F9FA; }
    h1 { margin: 0 0 6px; }
    h2 { margin: 0 0 12px; font-size: 20px; }
    h2 span { color: #667085; font-size: 13px; font-weight: 400; margin-left: 8px; }
    h3 { margin: 0 0 8px; font-size: 16px; }
    h3 span { color: #667085; font-weight: 400; margin-left: 8px; }
    h4 { margin: 14px 0 6px; }
    .slide { background: white; border: 1px solid #D7DEE5; border-radius: 8px; padding: 14px; margin: 18px 0; }
    .preview { position: relative; aspect-ratio: 16 / 9; background: #E9EEF2; overflow: hidden; margin-bottom: 12px; }
    .preview img { display: block; width: 100%; height: 100%; object-fit: contain; }
    .box { position: absolute; pointer-events: none; }
    .semantic { border: 2px dashed rgba(37, 99, 235, 0.75); background: rgba(37, 99, 235, 0.08); }
    .geometry { border: 3px solid rgba(100, 116, 139, 0.8); background: rgba(100, 116, 139, 0.16); }
    .chunk { border-top: 1px solid #E2E8F0; padding: 12px 0; }
    .narration { color: #344054; }
    table { border-collapse: collapse; width: 100%; font-size: 12px; }
    th, td { border: 1px solid #D7DEE5; padding: 5px 6px; vertical-align: top; }
    th { background: #EEF3F7; text-align: left; }
    code { background: #EEF3F7; padding: 1px 4px; border-radius: 4px; }
    .empty { color: #667085; font-style: italic; }
  </style>
</head>
<body>
  <h1>paper2video cue candidate review</h1>
  <p>Blue dashed boxes are selected semantic targets; slate boxes are final rendered geometry. Candidate tables show the alternatives considered before choosing the cue.</p>
""" + "\n".join(sections) + """
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synchronized semantic visual cues for paper2video.")
    ap.add_argument("project_path", help="ppt-master or paper2video project root")
    ap.add_argument("--svg-dir", default=None, help="SVG directory (default: <project>/svg_output)")
    ap.add_argument("--script-json", default=None, help="Narration script JSON; default falls back to notes/*.md")
    ap.add_argument("--audio-dir", default=None, help="Audio directory with <id>.mp3 files (default: <project>/audio)")
    ap.add_argument("--pptx", default=None, help="Final PPTX deck. Enables PPTX element registry and stronger cue planning.")
    ap.add_argument("--anchor-contract", default=None,
                    help="visual_anchor_contract.json from generate_cue_requirements.py. "
                         "When provided, chunks must match explicit cue anchors.")
    ap.add_argument("--require-pptx-anchors", action="store_true",
                    help="Require exact cue anchors to be present in PPTX metadata, not only SVG/HTML.")
    ap.add_argument("--no-prefer-pptx-geometry", action="store_true",
                    help="Disable SVG-semantics to PPTX-geometry resolution; render the selected semantic region box directly.")
    ap.add_argument("--pptx-geometry-min-score", type=float, default=PPTX_GEOMETRY_MIN_SCORE,
                    help=f"Minimum score needed before replacing an SVG semantic box with PPTX geometry (default: {PPTX_GEOMETRY_MIN_SCORE}).")
    ap.add_argument("--timings-json", default=None,
                    help="Optional word-boundary timing JSON written by generate_edge_audio.py --timings-out.")
    ap.add_argument("--preview-dir", default=None,
                    help="Optional slide PNG directory for overlay previews in cue_audit.html.")
    ap.add_argument("--estimate-durations", action="store_true",
                    help="Estimate durations from narration text when audio is missing. Use only for scaffolding.")
    ap.add_argument("--words-per-minute", type=float, default=145.0)
    ap.add_argument("--max-cues-per-slide", type=int, default=4)
    ap.add_argument("--min-confidence", type=float, default=0.38,
                    help="Minimum semantic confidence for a cue to be emitted (0-1).")
    ap.add_argument("--strict-gate", action="store_true",
                    help="Fail if any narration chunk cannot be mapped to a confident visual target.")
    ap.add_argument("--require-timestamps", action="store_true",
                    help="Fail unless --timings-json provides word-boundary timing for every slide.")
    ap.add_argument("--color", default="#64748B")
    ap.add_argument("--opacity", type=float, default=0.18)
    ap.add_argument("--size", type=int, default=58, help="Fallback dot radius in output-video pixels when no box is available")
    ap.add_argument("--out", default=None, help="visual_cues JSON output")
    ap.add_argument("--regions-out", default=None)
    ap.add_argument("--elements-out", default=None)
    ap.add_argument("--geometry-report-out", default=None,
                    help="Output geometry-resolution JSON showing semantic target vs rendered geometry source.")
    ap.add_argument("--cue-plan-out", default=None)
    ap.add_argument("--audit-out", default=None)
    ap.add_argument("--html-audit-out", default=None)
    ap.add_argument("--candidate-review-out", default=None,
                    help="HTML report showing per-chunk semantic and geometry candidates.")
    ap.add_argument("--repair-out", default=None,
                    help="Repair-request JSON written even when --strict-gate fails.")
    ap.add_argument("--repair-md-out", default=None,
                    help="Human-readable repair-request Markdown written even when --strict-gate fails.")
    args = ap.parse_args()

    project = Path(args.project_path).resolve()
    svg_dir = Path(args.svg_dir).resolve() if args.svg_dir else project / "svg_output"
    script_json = Path(args.script_json).resolve() if args.script_json else None
    audio_dir = Path(args.audio_dir).resolve() if args.audio_dir else project / "audio"
    pptx = Path(args.pptx).resolve() if args.pptx else None
    anchor_contract_path = Path(args.anchor_contract).resolve() if args.anchor_contract else None
    timings_json = Path(args.timings_json).resolve() if args.timings_json else None
    preview_dir = Path(args.preview_dir).resolve() if args.preview_dir else None

    if not svg_dir.is_dir():
        sys.exit(f"[generate_visual_cues] svg dir not found: {svg_dir}")
    if args.max_cues_per_slide < 1:
        sys.exit("[generate_visual_cues] --max-cues-per-slide must be positive")

    pptx_payload = None
    blocking_error = ""
    try:
        if pptx is not None:
            if not pptx.is_file():
                raise FileNotFoundError(f"PPTX not found: {pptx}")
            if extract_pptx_elements is None:
                raise RuntimeError("extract_pptx_elements.py could not be imported")
            pptx_payload = extract_pptx_elements(pptx)
        anchor_contract = load_anchor_contract(anchor_contract_path)
        word_timings = load_word_timings(timings_json) if timings_json is not None else {}
        sections = load_sections(script_json, project)
        if not sections:
            raise ValueError("no narration sections found")
        durations = load_durations(
            sections,
            audio_dir,
            estimate=args.estimate_durations,
            words_per_minute=args.words_per_minute,
        )
        cues_payload, regions_payload, audit, cue_plan, geometry_report = generate(
            project,
            svg_dir=svg_dir,
            sections=sections,
            durations=durations,
            max_cues=args.max_cues_per_slide,
            color=args.color,
            opacity=max(0.05, min(args.opacity, 1.0)),
            size=max(1, args.size),
            pptx_payload=pptx_payload,
            word_timings=word_timings,
            min_confidence=max(0.0, min(args.min_confidence, 0.95)),
            strict_gate=args.strict_gate,
            require_timestamps=args.require_timestamps,
            anchor_contract=anchor_contract,
            require_pptx_anchors=args.require_pptx_anchors,
            prefer_pptx_geometry=not args.no_prefer_pptx_geometry,
            pptx_geometry_min_score=max(0.0, args.pptx_geometry_min_score),
        )
        try:
            validate_payload(cues_payload, audit)
        except Exception as exc:
            blocking_error = str(exc)
        if cue_plan.get("errors"):
            blocking_error = "; ".join(str(e) for e in cue_plan["errors"])
    except Exception as exc:
        sys.exit(f"[generate_visual_cues] {exc}")

    out = Path(args.out).resolve() if args.out else project / "visual_cues.json"
    regions_out = Path(args.regions_out).resolve() if args.regions_out else project / "slide_regions.json"
    elements_out = Path(args.elements_out).resolve() if args.elements_out else project / "slide_elements.json"
    geometry_report_out = Path(args.geometry_report_out).resolve() if args.geometry_report_out else project / "geometry_resolution.json"
    cue_plan_out = Path(args.cue_plan_out).resolve() if args.cue_plan_out else project / "visual_cue_plan.json"
    audit_out = Path(args.audit_out).resolve() if args.audit_out else project / "cue_audit.json"
    html_out = Path(args.html_audit_out).resolve() if args.html_audit_out else project / "cue_audit.html"
    candidate_review_out = Path(args.candidate_review_out).resolve() if args.candidate_review_out else project / "cue_candidate_review.html"
    repair_out = Path(args.repair_out).resolve() if args.repair_out else project / "cue_repair_requests.json"
    repair_md_out = Path(args.repair_md_out).resolve() if args.repair_md_out else project / "cue_repair_requests.md"

    repair_payload = build_repair_requests(cue_plan, regions_payload, audit)

    out.write_text(json.dumps(cues_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    regions_out.write_text(json.dumps(regions_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if pptx_payload is not None:
        elements_out.write_text(json.dumps(pptx_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    geometry_report_out.write_text(json.dumps(geometry_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cue_plan_out.write_text(json.dumps(cue_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit_out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_html_audit(audit, html_out, preview_dir=preview_dir)
    write_candidate_review_html(audit, candidate_review_out, preview_dir=preview_dir)
    repair_out.write_text(json.dumps(repair_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_repair_markdown(repair_payload, repair_md_out)

    cue_count = sum(len(s.get("cues", [])) for s in cues_payload["slides"])
    print(f"[generate_visual_cues] wrote {cue_count} semantic highlight cue(s)")
    print(f"  visual cues: {out}")
    print(f"  regions:     {regions_out}")
    if pptx_payload is not None:
        print(f"  elements:    {elements_out}")
    print(f"  geometry:    {geometry_report_out}")
    print(f"  cue plan:    {cue_plan_out}")
    print(f"  audit:       {audit_out}")
    print(f"  html audit:  {html_out}")
    print(f"  candidates:  {candidate_review_out}")
    print(f"  repair json: {repair_out}")
    print(f"  repair md:   {repair_md_out}")
    if blocking_error:
        print(f"[generate_visual_cues] strict gate failed after writing diagnostics: {blocking_error}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
