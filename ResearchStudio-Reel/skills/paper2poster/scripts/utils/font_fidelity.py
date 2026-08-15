"""Portable browser-font preparation for generated poster bundles.

The poster composer intentionally exposes familiar Mac/Windows PowerPoint
family names.  Those proprietary fonts are not guaranteed to be installed on
the Linux renderer or on an HTML viewer's machine, so the same CSS can resolve
to different glyph metrics and wrap differently.  This module preserves the
renderer platform's *actual* open-licensed fallback, subsets that exact face
into the bundle, and records the requested family for the native PPTX handoff.
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .cli_common import eprint


_FIDELITY_VERSION = "7"
_SUBSET_FORMAT_VERSION = "2"
_SUBSET_GENERATOR_SCHEMA = "paper2poster-font-subset-p2"


@dataclass(frozen=True)
class _SourceSpec:
    family: str
    regular_style: str
    bold_style: str
    asset_slug: str
    suffix: str
    css_format: str
    license_name: str
    license_candidates: tuple[Path, ...]


@dataclass(frozen=True)
class _FontFace:
    path: Path
    index: int


_SOURCE_SPECS = {
    "noto sans cjk sc": _SourceSpec(
        family="Noto Sans CJK SC",
        regular_style="Regular",
        bold_style="Bold",
        asset_slug="NotoSansCJKSC",
        suffix=".otf",
        css_format="opentype",
        license_name="RS-NotoSansCJKSC-LICENSE.txt",
        license_candidates=(
            Path("/usr/share/doc/fonts-noto-cjk/copyright"),
            Path("/usr/share/licenses/noto-fonts/LICENSE"),
            Path("/usr/share/licenses/google-noto-cjk-fonts/LICENSE"),
            Path("/usr/share/licenses/noto-cjk-fonts/LICENSE"),
        ),
    ),
    "dejavu sans": _SourceSpec(
        family="DejaVu Sans",
        regular_style="Book",
        bold_style="Bold",
        asset_slug="DejaVuSans",
        suffix=".ttf",
        css_format="truetype",
        license_name="RS-DejaVu-LICENSE.txt",
        license_candidates=(
            Path("/usr/share/doc/fonts-dejavu-core/copyright"),
            Path("/usr/share/licenses/ttf-dejavu/LICENSE"),
            Path("/usr/share/licenses/dejavu-fonts/LICENSE"),
        ),
    ),
    "dejavu serif": _SourceSpec(
        family="DejaVu Serif",
        regular_style="Book",
        bold_style="Bold",
        asset_slug="DejaVuSerif",
        suffix=".ttf",
        css_format="truetype",
        license_name="RS-DejaVu-LICENSE.txt",
        license_candidates=(
            Path("/usr/share/doc/fonts-dejavu-core/copyright"),
            Path("/usr/share/licenses/ttf-dejavu/LICENSE"),
            Path("/usr/share/licenses/dejavu-fonts/LICENSE"),
        ),
    ),
}

_PORTABLE_FAMILIES = {
    "calibri": ("Calibri", "DejaVu Sans"),
    "aptos": ("Aptos", "DejaVu Sans"),
    "arial": ("Arial", "DejaVu Sans"),
    "verdana": ("Verdana", "DejaVu Sans"),
    "trebuchet ms": ("Trebuchet MS", "DejaVu Sans"),
    "cambria": ("Cambria", "DejaVu Serif"),
    "times new roman": ("Times New Roman", "DejaVu Serif"),
    "georgia": ("Georgia", "DejaVu Serif"),
}

_FIDELITY_PATTERN = re.compile(
    r'<style\s+id=["\']poster-font-fidelity["\'].*?</style>'
    r'(?:\s*<script\s+id=["\']poster-font-fidelity-refit["\']'
    r'.*?</script>)?',
    flags=re.IGNORECASE | re.DOTALL,
)


def managed_font_asset_names(fonts_dir: Path | None = None) -> frozenset[str]:
    """Return managed mutable and content-addressed font asset names.

    ``render_poster`` uses this closed set for its rollback journal.  Keep the
    fixed names source-derived; when ``fonts_dir`` is supplied, also discover
    existing immutable subset names.  The journal calls this once before a
    render and again during rollback, so identity assets created by a failed
    render are removed without putting unrelated files in scope.
    """
    names: set[str] = set()
    for spec in _SOURCE_SPECS.values():
        names.add(spec.license_name)
        names.add(f"RS-{spec.asset_slug}-Regular{spec.suffix}")
        names.add(f"RS-{spec.asset_slug}-Bold{spec.suffix}")
        if fonts_dir is not None and fonts_dir.is_dir():
            identity_pattern = re.compile(
                rf"^RS-{re.escape(spec.asset_slug)}-(?:Regular|Bold)"
                rf"-s[0-9a-f]{{64}}-i\d+-g[0-9a-f]{{64}}"
                rf"(?:-p1|-p\d+-t[0-9a-f]{{64}})"
                rf"{re.escape(spec.suffix)}$"
            )
            for path in fonts_dir.iterdir():
                if identity_pattern.fullmatch(path.name):
                    names.add(path.name)
    return frozenset(names)


def _copy_public_asset_atomic(source: Path, target: Path) -> None:
    """Install one public font asset without exposing a partial overwrite."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".font-next",
    )
    temporary = Path(raw)
    try:
        os.close(descriptor)
        shutil.copyfile(source, temporary)
        temporary.chmod(0o644)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _resolve_exact_font(family_name: str, style: str) -> _FontFace | None:
    """Resolve an exact installed family/style without accepting an alias."""
    try:
        match = subprocess.run(
            [
                "fc-match",
                "-f",
                "%{family}\t%{style}\t%{file}\t%{index}\n",
                f"{family_name}:style={style}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if match.returncode != 0 or not match.stdout.strip():
        return None
    fields = match.stdout.strip().split("\t", 3)
    if len(fields) != 4:
        return None
    family, _actual_style, filename, raw_index = fields
    # fc-match always returns *some* fallback.  Only accept a genuine member of
    # the requested family; an alias such as Calibri -> DejaVu is not exact.
    actual_families = {
        name.strip().casefold() for name in family.split(",") if name.strip()
    }
    if family_name.casefold() not in actual_families:
        return None
    path = Path(filename)
    try:
        index = int(raw_index or "0")
    except ValueError:
        return None
    return _FontFace(path=path, index=index) if path.is_file() else None


def _split_css_families(value: str) -> list[str]:
    """Split a CSS family list while respecting quotes and parentheses."""
    families: list[str] = []
    start = 0
    quote = ""
    depth = 0
    for index, char in enumerate(value):
        if quote:
            if char == quote and (index == 0 or value[index - 1] != "\\"):
                quote = ""
            continue
        if char in {"\"", "'"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        elif char == "," and depth == 0:
            families.append(value[start:index].strip().strip("\"'"))
            start = index + 1
    families.append(value[start:].strip().strip("\"'"))
    return [family for family in families if family]


def _sha256_file(path: Path) -> str:
    """Hash file content without trusting path, size, or modification time."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _subset_asset_names(
    spec: _SourceSpec,
    regular: _FontFace,
    bold: _FontFace,
    regular_sha256: str,
    bold_sha256: str,
    glyph_signature: str,
    *,
    subset_format_version: str,
    generator_signature: str | None,
) -> tuple[str, str]:
    """Return immutable, content-addressed names for one poster subset pair."""
    if subset_format_version == "1" and generator_signature is None:
        identity_suffix = "-p1"
    elif (
        re.fullmatch(r"[1-9]\d*", subset_format_version)
        and subset_format_version != "1"
        and generator_signature is not None
        and re.fullmatch(r"[0-9a-f]{64}", generator_signature)
    ):
        identity_suffix = (
            f"-p{subset_format_version}-t{generator_signature}"
        )
    else:
        raise ValueError(
            "font subset identity must be legacy untagged p1 or a tagged "
            "numeric pN with a 64-hex generator signature"
        )
    return (
        f"RS-{spec.asset_slug}-Regular-s{regular_sha256}-i{regular.index}"
        f"-g{glyph_signature}{identity_suffix}{spec.suffix}",
        f"RS-{spec.asset_slug}-Bold-s{bold_sha256}-i{bold.index}"
        f"-g{glyph_signature}{identity_suffix}{spec.suffix}",
    )


def _subset_generator_signature() -> str:
    """Fingerprint every loaded generator input that can change font bytes."""
    try:
        import fontTools
    except ImportError as exc:
        raise RuntimeError(
            "fonttools is required to identify compact portable poster fonts"
        ) from exc
    version = str(getattr(fontTools, "__version__", "")).strip()
    if not version:
        raise RuntimeError("loaded fonttools does not expose __version__")
    identity = (
        f"{_SUBSET_GENERATOR_SCHEMA}\0fontTools={version}".encode("utf-8")
    )
    return hashlib.sha256(identity).hexdigest()


def _data_attr(block: str, name: str) -> str | None:
    match = re.search(
        rf'data-{re.escape(name)}=["\']([^"\']+)["\']',
        block,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def _safe_bundled_face(out_fonts: Path, asset_name: str | None) -> _FontFace | None:
    """Resolve a metadata asset name without allowing path traversal."""
    if not asset_name or Path(asset_name).name != asset_name:
        return None
    path = out_fonts / asset_name
    if not path.is_file() or path.is_symlink() or path.stat().st_size <= 4_096:
        return None
    return _FontFace(path=path, index=0)


def _prior_face_assets(
    block: str,
    out_fonts: Path,
) -> tuple[_FontFace, _FontFace] | None:
    """Read the 400/700 font URLs from an older fidelity block.

    Fidelity v4 and v7 did not record subset-source paths as metadata.  Their
    two ``@font-face`` URLs are therefore the authoritative custom faces whose
    geometry must survive migration.  Accept only direct ``assets/fonts``
    basenames; remote URLs and traversal never become local subset inputs.
    """
    by_weight: dict[int, _FontFace] = {}
    for face_block in re.findall(
        r"@font-face\s*\{.*?\}", block, flags=re.IGNORECASE | re.DOTALL
    ):
        weight_match = re.search(
            r"font-weight\s*:\s*(400|700)\b", face_block, flags=re.IGNORECASE
        )
        url_match = re.search(
            r"url\(\s*[\"']?([^\"')?#]+)(?:[?#][^\"')]*)?[\"']?\s*\)",
            face_block,
            flags=re.IGNORECASE,
        )
        if not weight_match or not url_match:
            continue
        raw_url = url_match.group(1).replace("\\", "/")
        parts = tuple(part for part in raw_url.split("/") if part not in {"", "."})
        if len(parts) != 3 or parts[:2] != ("assets", "fonts"):
            continue
        resolved = _safe_bundled_face(out_fonts, parts[2])
        if resolved is not None:
            by_weight[int(weight_match.group(1))] = resolved
    if 400 not in by_weight or 700 not in by_weight:
        return None
    return by_weight[400], by_weight[700]


def _font_face_is_readable(face: _FontFace) -> bool:
    """Validate that a legacy asset is an actual readable font face."""
    try:
        from fontTools.ttLib import TTFont

        collection = face.path.suffix.casefold() in {".ttc", ".otc"}
        font = TTFont(
            str(face.path),
            fontNumber=face.index if collection else -1,
            lazy=True,
        )
        font.close()
        return True
    except Exception:
        return False


def _install_immutable_subset(temporary: Path, target: Path) -> str:
    """Install a content-addressed subset without replacing different bytes."""
    subset_sha256 = _sha256_file(temporary)
    if target.is_file():
        if target.is_symlink() or _sha256_file(target) != subset_sha256:
            raise RuntimeError(
                f"content-addressed font collision at {target}; refusing overwrite"
            )
        temporary.unlink()
        return subset_sha256
    if target.exists():
        raise RuntimeError(f"font subset target is not a regular file: {target}")
    os.replace(temporary, target)
    return subset_sha256


def _resolve_source(
    spec: _SourceSpec,
) -> tuple[_FontFace, _FontFace, Path] | None:
    regular = _resolve_exact_font(spec.family, spec.regular_style)
    bold = _resolve_exact_font(spec.family, spec.bold_style)
    license_path = next(
        (path for path in spec.license_candidates if path.is_file()), None
    )
    if regular is None or bold is None or license_path is None:
        return None
    return regular, bold, license_path


def _source_candidates(text: str, default_family: str) -> list[_SourceSpec]:
    """Return the renderer's likely painted Latin faces, in priority order.

    The Chromium matrix on the production renderer has two stable classes:
    the PowerPoint-safe sans stacks paint Noto Sans CJK SC, while serif stacks
    paint DejaVu Serif.  In particular, an explicit ``--font-cjk`` Noto entry
    must never outrank the serif category for Cambria/Georgia/Times: it is a
    fallback for missing CJK glyphs, not the face painting the Latin poster.

    Keep the serif category exclusive.  For sans, retain declared-stack order
    so the installed Noto face that Chromium actually paints remains
    authoritative, with DejaVu Sans as the last licensed fallback.
    """
    candidates: list[_SourceSpec] = []
    seen: set[str] = set()

    def append(spec: _SourceSpec) -> None:
        key = spec.family.casefold()
        if key not in seen:
            candidates.append(spec)
            seen.add(key)

    default = _SOURCE_SPECS[default_family.casefold()]
    if default.family.casefold() == "dejavu serif":
        # Do not fall through to a CJK sans merely because it is declared in
        # the shared body stack.  If the renderer lacks its serif source face,
        # failing soft is safer than silently changing the poster category.
        return [default]

    for variable in ("font-latin", "font-cjk"):
        declaration = re.search(
            rf"--{variable}\s*:\s*([^;]+);",
            text,
            flags=re.IGNORECASE,
        )
        if not declaration:
            continue
        for family in _split_css_families(declaration.group(1)):
            spec = _SOURCE_SPECS.get(family.casefold())
            if spec is not None:
                append(spec)
    append(default)
    return candidates


def _source_category(spec: _SourceSpec) -> str:
    """Return the browser typography category used for migration safety."""
    return "serif" if spec.family.casefold() == "dejavu serif" else "sans"


_CSS_HEX_ESCAPE = re.compile(
    r"\\([0-9a-fA-F]{1,6})(?:\r\n|[\t\n\f\r ])?"
)


def _glyph_repertoire(text: str) -> str:
    """Return every codepoint the delivered DOM/CSS can visibly produce."""
    expanded = html.unescape(text)

    def decode_css_hex(match: re.Match[str]) -> str:
        value = int(match.group(1), 16)
        if value == 0 or value > 0x10FFFF or 0xD800 <= value <= 0xDFFF:
            return "\N{REPLACEMENT CHARACTER}"
        return chr(value)

    expanded = _CSS_HEX_ESCAPE.sub(decode_css_hex, expanded)
    repertoire = set(expanded)
    # CSS text-transform may request glyphs absent from the literal source.
    # Apply transforms to the whole string because Unicode mappings such as
    # sharp-s -> SS can expand to more than one codepoint.
    repertoire.update(expanded.lower())
    repertoire.update(expanded.upper())
    return "".join(sorted(repertoire))


def _glyph_signature(repertoire: str) -> str:
    """Fingerprint the exact expanded codepoint set baked into the fonts."""
    return hashlib.sha256(repertoire.encode("utf-8")).hexdigest()


def _build_subset_temp(
    face: _FontFace,
    target: Path,
    text: str,
) -> Path:
    """Build one hinted font subset beside its destination for atomic install."""
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise RuntimeError(
            "fonttools is required to create compact portable poster fonts"
        ) from exc

    descriptor, raw = tempfile.mkstemp(
        dir=target.parent,
        prefix=".font-subset.",
        suffix=f".font-next{target.suffix}",
    )
    os.close(descriptor)
    temporary = Path(raw)
    font = None
    try:
        collection = face.path.suffix.casefold() in {".ttc", ".otc"}
        font = TTFont(
            str(face.path),
            fontNumber=face.index if collection else -1,
            lazy=False,
            recalcTimestamp=False,
        )
        options = subset.Options()
        # Preserve all shaping features used by the source face.  Do not use
        # --no-hinting: removing hints changes glyph advances/rasterization.
        # FontTools drops the legacy `kern` table by default even when its
        # OpenType `kern` feature is retained.  Chromium's installed-font and
        # custom-webfont paths do not always choose the same one; keeping both
        # removes one avoidable source of installed/custom path divergence.
        options.layout_features = ["*"]
        options.legacy_kern = True
        options.drop_tables.append("FFTM")
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(text=text)
        subsetter.subset(font)
        font.save(str(temporary))
        temporary.chmod(0o644)
        if temporary.stat().st_size < 4_096:
            raise RuntimeError(f"implausibly small font subset: {temporary}")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if font is not None:
            font.close()


def freeze_system_font_webfont(html_path: Path) -> bool:
    """Freeze selectable OS-font stacks to redistributable browser faces.

    Preserve the first exact, open-licensed face that the declared browser
    stack can actually use (normally Noto Sans CJK SC on the Linux renderer),
    then subset that face to the poster's codepoint repertoire.  The local
    source family remains first in the browser-only override: this preserves
    the source platform's rasterization exactly.  A separately named bundled
    face follows it for clients lacking that font, retaining the same source
    metrics as closely as the browser's custom-font path permits without
    falsely registering a webfont as Calibri/Arial/etc.

    The fidelity block records the originally requested family so html2pptx
    can retain that native family in PowerPoint even though browser rendering
    deliberately uses the measured source/fallback face.

    If the HTML already supplies an independent custom ``@font-face`` for the
    selected family, it is treated as intentionally licensed and left alone.
    Any obsolete fidelity block is removed when freezing no longer applies.
    Returns ``True`` whenever the HTML file was changed.
    """
    html_path = Path(html_path)
    text = html_path.read_text(encoding="utf-8", errors="ignore")

    # Exclude our own prior block while looking for an independently supplied
    # (for example, licensed Georgia) author face.
    text_without_fidelity = _FIDELITY_PATTERN.sub("", text)
    declaration = re.search(
        r"--font-latin\s*:\s*([^;]+);", text, flags=re.IGNORECASE,
    )
    if not declaration:
        if text_without_fidelity == text:
            return False
        html_path.write_text(text_without_fidelity, encoding="utf-8")
        eprint(
            "[paper2poster] removed stale portable-font fidelity block: "
            "the poster no longer declares --font-latin."
        )
        return True
    declared_families = _split_css_families(declaration.group(1))
    if not declared_families:
        return False
    first_family = declared_families[0]
    selected = _PORTABLE_FAMILIES.get(first_family.casefold())
    if selected is None:
        if text_without_fidelity == text:
            return False
        html_path.write_text(text_without_fidelity, encoding="utf-8")
        eprint(
            "[paper2poster] removed stale portable-font fidelity block: "
            f"{first_family} uses its own browser font configuration."
        )
        return True
    requested_family, default_source_family = selected

    for face in re.findall(
        r"@font-face\s*\{.*?\}",
        text_without_fidelity,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        family = re.search(
            r"font-family\s*:\s*([^;}]+)", face, flags=re.IGNORECASE,
        )
        if (
            family
            and family.group(1).strip().strip("\"'").casefold()
            == requested_family.casefold()
        ):
            if text_without_fidelity == text:
                return False
            html_path.write_text(text_without_fidelity, encoding="utf-8")
            eprint(
                "[paper2poster] removed stale portable-font fidelity block: "
                f"the poster supplies its own {requested_family} @font-face."
            )
            return True

    out_fonts = html_path.parent / "assets" / "fonts"
    glyph_repertoire = _glyph_repertoire(text_without_fidelity)
    glyph_signature = _glyph_signature(glyph_repertoire)
    prior = _FIDELITY_PATTERN.search(text)
    prior_spec: _SourceSpec | None = None
    prior_is_compatible = False
    prior_version: str | None = None
    prior_source_order: str | None = None
    refit_version: str | None = None
    if prior:
        prior_block = prior.group(0)
        prior_requested = _data_attr(prior_block, "requested-family")
        prior_source_family = _data_attr(prior_block, "source-family")
        prior_version = _data_attr(prior_block, "fidelity-version")
        prior_source_order = _data_attr(prior_block, "source-order")
        refit_tag = re.search(
            r'<script\s+id=["\']poster-font-fidelity-refit["\'][^>]*>',
            prior_block,
            flags=re.IGNORECASE,
        )
        refit_version = (
            _data_attr(refit_tag.group(0), "fidelity-version")
            if refit_tag else None
        )
        prior_spec = (
            _SOURCE_SPECS.get(prior_source_family.casefold())
            if prior_source_family
            else None
        )
        prior_is_compatible = bool(
            prior_spec
            and prior_requested
            and prior_requested.casefold() == requested_family.casefold()
            and _source_category(prior_spec)
            == _source_category(_SOURCE_SPECS[default_source_family.casefold()])
        )

    # Fidelity v4 made its bundled DejaVu files the actual painted faces.  A v7
    # block can also explicitly retain that bundled-first contract.  In both
    # cases those exact bundle bytes—not whatever font happens to be installed
    # on today's host—are the source for migration.  A v7 local-first block is
    # deliberately *not* treated as legacy custom geometry.
    legacy_custom_source = bool(
        prior_is_compatible
        and prior_source_order is None
        and prior_version not in {"7", _FIDELITY_VERSION}
    )
    persisted_custom_source = bool(
        prior_is_compatible
        and prior_source_order
        and prior_source_order.casefold() == "bundled-first"
    )
    use_prior_bundle = legacy_custom_source or persisted_custom_source

    resolved_source: tuple[
        _SourceSpec, _FontFace, _FontFace, Path, str, str | None, str | None
    ] | None = None
    if use_prior_bundle and prior and prior_spec:
        source_regular_asset = _data_attr(
            prior.group(0), "source-regular-asset"
        )
        source_bold_asset = _data_attr(prior.group(0), "source-bold-asset")
        regular = _safe_bundled_face(out_fonts, source_regular_asset)
        bold = _safe_bundled_face(out_fonts, source_bold_asset)
        if regular is None or bold is None:
            legacy_faces = _prior_face_assets(prior.group(0), out_fonts)
            if legacy_faces is not None:
                regular, bold = legacy_faces
                source_regular_asset = regular.path.name
                source_bold_asset = bold.path.name
        existing_license = out_fonts / prior_spec.license_name
        license_path = (
            existing_license
            if existing_license.is_file()
            and not existing_license.is_symlink()
            and existing_license.stat().st_size > 100
            else next(
                (
                    path for path in prior_spec.license_candidates
                    if path.is_file()
                ),
                None,
            )
        )
        if (
            regular is not None
            and bold is not None
            and license_path is not None
            and _font_face_is_readable(regular)
            and _font_face_is_readable(bold)
        ):
            resolved_source = (
                prior_spec,
                regular,
                bold,
                license_path,
                "bundled",
                source_regular_asset,
                source_bold_asset,
            )
        else:
            # Keeping the valid prior block is safer than silently swapping its
            # geometry for a host font when a legacy bundle is incomplete.
            eprint(
                "[paper2poster] WARN: could not validate the bundled source "
                f"faces for legacy {requested_family}; preserving the prior "
                "font-fidelity block unchanged."
            )
            return False

    if resolved_source is None:
        # If the requested proprietary family is genuinely installed, it is
        # the source platform face.  We cannot redistribute it under this open-
        # font contract, so do not replace it with a different metric face.
        if _resolve_exact_font(requested_family, "Regular") is not None:
            if text_without_fidelity != text:
                html_path.write_text(text_without_fidelity, encoding="utf-8")
                eprint(
                    "[paper2poster] removed stale portable-font fidelity block: "
                    f"the renderer has native {requested_family}."
                )
                return True
            eprint(
                f"[paper2poster] WARN: {requested_family} is not portable on "
                "this host: its native face is installed but cannot be copied by "
                "this open-font bundler; continuing with the platform font stack."
            )
            return False

        for candidate in _source_candidates(
            text_without_fidelity, default_source_family
        ):
            resolved = _resolve_source(candidate)
            if resolved is not None:
                regular, bold, license_path = resolved
                resolved_source = (
                    candidate,
                    regular,
                    bold,
                    license_path,
                    "local",
                    None,
                    None,
                )
                break
    if resolved_source is None:
        eprint(
            f"[paper2poster] WARN: {requested_family} is not portable on "
            "this host: no licensed face from its rendered fallback stack "
            "could be located; continuing with the platform font stack."
        )
        return False

    (
        source_spec,
        regular,
        bold,
        license_path,
        source_origin,
        source_regular_asset,
        source_bold_asset,
    ) = resolved_source
    source_family = source_spec.family
    fallback_family = f"RS {source_family}"
    bundled_first = source_origin == "bundled"
    source_order = "bundled-first" if bundled_first else "local-first"
    browser_families = (
        f'"{fallback_family}", "{source_family}"'
        if bundled_first
        else f'"{source_family}", "{fallback_family}"'
    )
    generic_family = (
        "serif" if default_source_family.casefold() == "dejavu serif"
        else "sans-serif"
    )
    regular_source_sha256 = _sha256_file(regular.path)
    bold_source_sha256 = _sha256_file(bold.path)
    out_fonts.mkdir(parents=True, exist_ok=True)

    if prior:
        prior_block = prior.group(0)
        prior_regular_name = _data_attr(prior_block, "regular-asset")
        prior_bold_name = _data_attr(prior_block, "bold-asset")
        prior_regular_target = _safe_bundled_face(
            out_fonts, prior_regular_name
        )
        prior_bold_target = _safe_bundled_face(out_fonts, prior_bold_name)
        prior_regular_subset_sha256 = _data_attr(
            prior_block, "subset-regular-sha256"
        )
        prior_bold_subset_sha256 = _data_attr(
            prior_block, "subset-bold-sha256"
        )
        prior_subset_format_version = _data_attr(
            prior_block, "subset-format-version"
        )
        prior_generator_signature = _data_attr(
            prior_block, "subset-generator-signature"
        )
        try:
            expected_prior_names = _subset_asset_names(
                source_spec,
                regular,
                bold,
                regular_source_sha256,
                bold_source_sha256,
                glyph_signature,
                subset_format_version=prior_subset_format_version or "",
                generator_signature=prior_generator_signature,
            )
        except ValueError:
            expected_prior_names = None
        cache_assets_complete = bool(
            prior_regular_target
            and prior_bold_target
            and prior_regular_subset_sha256
            and prior_bold_subset_sha256
            and _sha256_file(prior_regular_target.path)
            == prior_regular_subset_sha256
            and _sha256_file(prior_bold_target.path)
            == prior_bold_subset_sha256
        )
        if (
            prior_is_compatible
            and prior_version == _FIDELITY_VERSION
            and refit_version == _FIDELITY_VERSION
            and (_data_attr(prior_block, "fallback-family") or "").casefold()
            == fallback_family.casefold()
            and (_data_attr(prior_block, "source-order") or "").casefold()
            == source_order
            and _data_attr(prior_block, "glyph-signature")
            == glyph_signature
            and _data_attr(prior_block, "source-regular-sha256")
            == regular_source_sha256
            and _data_attr(prior_block, "source-bold-sha256")
            == bold_source_sha256
            and _data_attr(prior_block, "source-regular-index")
            == str(regular.index)
            and _data_attr(prior_block, "source-bold-index")
            == str(bold.index)
            and expected_prior_names is not None
            and prior_regular_name == expected_prior_names[0]
            and prior_bold_name == expected_prior_names[1]
            and cache_assets_complete
            and (out_fonts / source_spec.license_name).is_file()
            and (out_fonts / source_spec.license_name).stat().st_size > 100
        ):
            return False

    regular_temp: Path | None = None
    bold_temp: Path | None = None
    regular_target: Path | None = None
    bold_target: Path | None = None
    regular_existed = False
    bold_existed = False
    try:
        generator_signature = _subset_generator_signature()
        regular_name, bold_name = _subset_asset_names(
            source_spec,
            regular,
            bold,
            regular_source_sha256,
            bold_source_sha256,
            glyph_signature,
            subset_format_version=_SUBSET_FORMAT_VERSION,
            generator_signature=generator_signature,
        )
        regular_target = out_fonts / regular_name
        bold_target = out_fonts / bold_name
        regular_existed = regular_target.is_file()
        bold_existed = bold_target.is_file()
        regular_temp = _build_subset_temp(
            regular, regular_target, glyph_repertoire
        )
        bold_temp = _build_subset_temp(bold, bold_target, glyph_repertoire)
        regular_subset_sha256 = _install_immutable_subset(
            regular_temp, regular_target
        )
        regular_temp = None
        bold_subset_sha256 = _install_immutable_subset(bold_temp, bold_target)
        bold_temp = None
        _copy_public_asset_atomic(
            license_path, out_fonts / source_spec.license_name
        )
    except Exception as exc:
        eprint(
            f"[paper2poster] WARN: could not subset licensed {source_family} "
            f"for {requested_family}: {exc}; continuing with the platform "
            "font stack."
        )
        if regular_target is not None and not regular_existed:
            regular_target.unlink(missing_ok=True)
        if bold_target is not None and not bold_existed:
            bold_target.unlink(missing_ok=True)
        return False
    finally:
        if regular_temp is not None:
            regular_temp.unlink(missing_ok=True)
        if bold_temp is not None:
            bold_temp.unlink(missing_ok=True)

    source_asset_attrs = (
        f' data-source-regular-asset="{source_regular_asset}"'
        f' data-source-bold-asset="{source_bold_asset}"'
        if bundled_first else ""
    )
    block = f'''<style id="poster-font-fidelity" data-fidelity-version="{_FIDELITY_VERSION}" data-subset-format-version="{_SUBSET_FORMAT_VERSION}" data-subset-generator-signature="{generator_signature}" data-requested-family="{requested_family}" data-source-family="{source_family}" data-fallback-family="{fallback_family}" data-source-order="{source_order}" data-glyph-signature="{glyph_signature}" data-source-regular-sha256="{regular_source_sha256}" data-source-bold-sha256="{bold_source_sha256}" data-source-regular-index="{regular.index}" data-source-bold-index="{bold.index}" data-regular-asset="{regular_name}" data-bold-asset="{bold_name}" data-subset-regular-sha256="{regular_subset_sha256}" data-subset-bold-sha256="{bold_subset_sha256}"{source_asset_attrs}>
  /* Fresh source geometry keeps the renderer's local face first. A compatible
     legacy custom-font migration keeps its bundled face first instead. */
  @font-face {{
    font-family: "{fallback_family}";
    src: url("assets/fonts/{regular_name}") format("{source_spec.css_format}");
    font-style: normal;
    font-weight: 400;
    font-display: block;
  }}
  @font-face {{
    font-family: "{fallback_family}";
    src: url("assets/fonts/{bold_name}") format("{source_spec.css_format}");
    font-style: normal;
    font-weight: 700;
    font-display: block;
  }}
  html, body {{
    font-family: {browser_families}, var(--font-cjk, {generic_family}), {generic_family} !important;
  }}
</style>
<script id="poster-font-fidelity-refit" data-fidelity-version="{_FIDELITY_VERSION}">
(() => {{
  if (window.__posterFontFidelityRefitInstalled) return;
  window.__posterFontFidelityRefitInstalled = true;
  const refitAfterLayoutAssets = () => {{
    const fontsReady = document.fonts && document.fonts.ready
      ? Promise.resolve(document.fonts.ready).catch(() => {{}})
      : Promise.resolve();
    const mathReady = (() => {{
      const mj = window.MathJax;
      if (!mj || !mj.startup || !mj.startup.promise) return Promise.resolve();
      const typeset = Promise.resolve(mj.startup.promise).then(() =>
        typeof mj.typesetPromise === "function" ? mj.typesetPromise() : null
      );
      /* A blocked/failed math engine must not prevent the portable-font refit.
         Match the renderer's bounded wait, then continue with what loaded. */
      return Promise.race([
        typeset.catch(() => {{}}),
        new Promise(resolve => setTimeout(resolve, 15000)),
      ]);
    }})();
    Promise.all([fontsReady, mathReady]).then(() => {{
      /* Use the template's existing resize -> relayout() path. Its listener
         passes fitAll into __fitPosterStage while unscaled, so figures and the
         outer scale are recomputed together after final font AND math metrics
         settle in a reopened standalone HTML poster. */
      requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    }}).catch(() => {{}});
  }};
  if (document.readyState === "complete") refitAfterLayoutAssets();
  else window.addEventListener("load", refitAfterLayoutAssets, {{ once: true }});
}})();
</script>'''
    if _FIDELITY_PATTERN.search(text):
        text = _FIDELITY_PATTERN.sub(block, text, count=1)
    elif "</head>" in text:
        text = text.replace("</head>", block + "\n</head>", 1)
    else:
        text = block + "\n" + text
    html_path.write_text(text, encoding="utf-8")
    subset_bytes = regular_target.stat().st_size + bold_target.stat().st_size
    browser_source = (
        f"bundled {fallback_family} before local {source_family}"
        if bundled_first
        else f"local {source_family}"
    )
    eprint(
        f"[paper2poster] preserved {requested_family} browser geometry with "
        f"{browser_source} + a {subset_bytes:,}-byte bundled subset "
        f"(PPTX family remains {requested_family})."
    )
    return True
