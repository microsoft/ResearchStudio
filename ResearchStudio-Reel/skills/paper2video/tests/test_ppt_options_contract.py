from __future__ import annotations

from pathlib import Path
import sys
import unittest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from ppt_options_contract import (  # noqa: E402
    PPT_MASTER_MODES,
    PPT_MASTER_VISUAL_STYLES,
    PPT_OPTIONS_PUBLIC_CATALOG,
    PptOptionsValidationError,
    export_flags_from_options,
    fallback_resolved_ppt_options,
    merge_resolved_ppt_options,
    parse_json_object,
    validate_resolved_ppt_options,
)


def requested(**overrides):
    values = {
        "duration": "5",
        "ppt_page_count": "auto",
        "ppt_mode": "auto",
        "ppt_visual_style": "auto",
        "ppt_delivery_purpose": "presentation",
        "ppt_audience": "",
        "ppt_color": "",
        "ppt_typography": "",
        "ppt_icons": "auto",
        "ppt_formula_policy": "mixed",
        "ppt_image_usage": ["auto"],
    }
    values.update(overrides)
    return values


def valid_resolution(**overrides):
    values = {
        "page_count": 10,
        "mode": "narrative",
        "visual_style": "editorial",
        "delivery_purpose": "presentation",
        "target_audience": "Machine learning researchers and engineers",
        "color_direction": (
            "Light editorial palette with background #F8FAFC and accent #2563EB"
        ),
        "typography_direction": "Aptos headings with Aptos body text",
        "icon_library": "tabler-outline",
        "formula_policy": "mixed",
        "image_usage": ["provided", "placeholder"],
        "image_ai_path": "not-used",
    }
    values.update(overrides)
    return values


class PptOptionContractTests(unittest.TestCase):
    def test_public_catalog_is_the_source_of_backend_enums(self) -> None:
        mode_ids = tuple(
            option["id"]
            for option in PPT_OPTIONS_PUBLIC_CATALOG["narrative_modes"]
        )
        style_ids = (
            "auto",
            *tuple(
                option["id"]
                for group in PPT_OPTIONS_PUBLIC_CATALOG["visual_style_groups"]
                for option in group["options"]
            ),
        )
        self.assertEqual(PPT_MASTER_MODES, mode_ids)
        self.assertEqual(PPT_MASTER_VISUAL_STYLES, style_ids)
        self.assertEqual(len(mode_ids), len(set(mode_ids)))
        self.assertEqual(len(style_ids), len(set(style_ids)))

    def test_invalid_invented_enum_values_are_rejected(self) -> None:
        for key, value in (
            ("mode", "flat"),
            ("visual_style", "minimal-editorial"),
        ):
            payload = valid_resolution(**{key: value})
            with self.subTest(key=key, value=value):
                with self.assertRaises(PptOptionsValidationError):
                    validate_resolved_ppt_options(
                        payload,
                        requested(),
                        image_api_available=False,
                    )

    def test_explicit_user_values_cannot_be_replaced(self) -> None:
        with self.assertRaises(PptOptionsValidationError):
            validate_resolved_ppt_options(
                valid_resolution(mode="narrative"),
                requested(ppt_mode="instructional"),
                image_api_available=False,
            )

    def test_valid_auto_resolution_is_locked_into_video_options(self) -> None:
        original = requested()
        resolved = validate_resolved_ppt_options(
            valid_resolution(),
            original,
            image_api_available=False,
        )
        merged = merge_resolved_ppt_options(original, resolved)
        self.assertEqual(merged["ppt_mode"], "narrative")
        self.assertEqual(merged["ppt_visual_style"], "editorial")
        self.assertEqual(merged["ppt_page_count"], "10")
        self.assertEqual(merged["_ppt_user_request"]["ppt_color"], "")

    def test_fallback_uses_only_catalog_values(self) -> None:
        resolved = fallback_resolved_ppt_options(
            requested(duration="8"),
            image_api_available=False,
        )
        self.assertEqual(resolved["page_count"], 16)
        self.assertIn(resolved["mode"], PPT_MASTER_MODES)
        self.assertIn(resolved["visual_style"], PPT_MASTER_VISUAL_STYLES)
        self.assertNotIn("ai", resolved["image_usage"])

    def test_ai_path_matches_image_sources(self) -> None:
        with self.assertRaises(PptOptionsValidationError):
            validate_resolved_ppt_options(
                valid_resolution(image_usage=["ai"], image_ai_path="not-used"),
                requested(),
                image_api_available=True,
            )

    def test_parser_requires_one_clean_json_object(self) -> None:
        parsed = parse_json_object('```json\n{"mode": "narrative"}\n```')
        self.assertEqual(parsed, {"mode": "narrative"})
        with self.assertRaises(PptOptionsValidationError):
            parse_json_object('{"mode": "narrative"} trailing prose')

    def test_export_flags_preserve_grouping_and_optional_switches(self) -> None:
        self.assertEqual(
            export_flags_from_options(
                {
                    "ppt_transition": "wipe",
                    "ppt_animation": "fade",
                    "ppt_animation_trigger": "on-click",
                    "ppt_native_objects": True,
                    "ppt_strict_line_fidelity": True,
                }
            ),
            [
                "-t wipe",
                "-a fade",
                "--animation-trigger on-click",
                "--native-objects",
                "--no-merge",
            ],
        )


if __name__ == "__main__":
    unittest.main()
