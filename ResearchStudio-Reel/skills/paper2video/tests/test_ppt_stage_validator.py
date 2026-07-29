from __future__ import annotations

from pathlib import Path
import sys
import unittest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from ppt_stage_validator import (  # noqa: E402
    audit_descriptive_options,
    audit_export_flags,
)


LOCK_TEXT = """\
<!-- ppt-master-schema: spec-lock/v1 -->
# Execution Lock

## communication
- audience: ML and AI researchers following foundation-model and embodied-agent work

## colors
- bg: #0B1120
- primary: #38E1D6
- accent: #7C5CFF
- text: #C7D6EE

## typography
- font_family: Inter, "Helvetica Neue", Arial, sans-serif
- title_family: Inter, "Helvetica Neue", Arial, sans-serif
- body_family: Inter, "Helvetica Neue", Arial, sans-serif
- body: 24
- title: 46
"""

DESIGN_TEXT = """\
# SIMA 2 Video Deck - Design Spec

| Item | Value |
| --- | --- |
| Target Audience | Machine-learning and AI researchers, embodied-agent and RL practitioners following foundation-model work |

## Color Scheme

| Role | HEX |
| --- | --- |
| Background | #0B1120 |
| Primary | #38E1D6 |
| Accent | #7C5CFF |
| Body text | #C7D6EE |

## Typography System

| Role | English |
| --- | --- |
| Title | Inter |
| Body | Inter |
"""

AUTO_APPLIED = {
    "target_audience": (
        "Machine-learning and AI researchers following foundation-model "
        "and embodied-agent work"
    ),
    "typography_direction": (
        "Single clean sans (Inter) for titles and body, with JetBrains Mono labels"
    ),
    "color_direction": (
        "Dark-tech palette: #0B1120 background, #38E1D6 primary, "
        "#7C5CFF accent, #C7D6EE body text"
    ),
}


class DescriptiveOptionValidatorTests(unittest.TestCase):
    def test_official_spec_lock_v1_color_keys_are_supported(self) -> None:
        audit_descriptive_options(AUTO_APPLIED, {}, LOCK_TEXT, DESIGN_TEXT)

    def test_historical_long_color_keys_remain_supported(self) -> None:
        legacy_lock = (
            LOCK_TEXT
            .replace("- bg:", "- background:")
            .replace("- text:", "- body_text:")
        )
        audit_descriptive_options(AUTO_APPLIED, {}, legacy_lock, DESIGN_TEXT)

    def test_generated_body_color_alias_remains_supported(self) -> None:
        legacy_lock = LOCK_TEXT.replace("- text:", "- body:")
        audit_descriptive_options(AUTO_APPLIED, {}, legacy_lock, DESIGN_TEXT)

    def test_body_and_body_text_aliases_cannot_conflict(self) -> None:
        conflicting_lock = LOCK_TEXT.replace(
            "- text: #C7D6EE",
            "- body: #C7D6EE\n- body_text: #FFFFFF",
        )
        with self.assertRaisesRegex(RuntimeError, "conflicting aliases for body_text"):
            audit_descriptive_options(
                AUTO_APPLIED,
                {},
                conflicting_lock,
                DESIGN_TEXT,
            )

    def test_conflicting_color_aliases_are_rejected(self) -> None:
        conflicting_lock = LOCK_TEXT.replace(
            "- bg: #0B1120",
            "- bg: #0B1120\n- background: #FFFFFF",
        )
        with self.assertRaisesRegex(RuntimeError, "conflicting aliases for background"):
            audit_descriptive_options(
                AUTO_APPLIED,
                {},
                conflicting_lock,
                DESIGN_TEXT,
            )

    def test_missing_color_role_names_the_semantic_role(self) -> None:
        missing_text_lock = LOCK_TEXT.replace("- text: #C7D6EE\n", "")
        with self.assertRaisesRegex(RuntimeError, "body_text"):
            audit_descriptive_options(
                AUTO_APPLIED,
                {},
                missing_text_lock,
                DESIGN_TEXT,
            )

    def test_real_auto_output_allows_equivalent_non_verbatim_audience(self) -> None:
        audit_descriptive_options(AUTO_APPLIED, {}, LOCK_TEXT, DESIGN_TEXT)

    def test_auto_audience_must_still_agree_with_execution_lock(self) -> None:
        applied = {**AUTO_APPLIED, "target_audience": "Primary-school art teachers"}
        with self.assertRaisesRegex(
            RuntimeError,
            "Auto target audience is inconsistent",
        ):
            audit_descriptive_options(applied, {}, LOCK_TEXT, DESIGN_TEXT)

    def test_explicit_audience_cannot_be_ignored(self) -> None:
        requested = "Undergraduate biology students"
        applied = {**AUTO_APPLIED, "target_audience": requested}
        with self.assertRaisesRegex(
            RuntimeError,
            "did not record the requested target audience",
        ):
            audit_descriptive_options(
                applied,
                {"ppt_audience": requested},
                LOCK_TEXT,
                DESIGN_TEXT,
            )

    def test_explicit_typography_cannot_be_ignored(self) -> None:
        requested = "Use Comic Sans for every text role"
        applied = {**AUTO_APPLIED, "typography_direction": requested}
        with self.assertRaisesRegex(
            RuntimeError,
            "did not record the requested typography",
        ):
            audit_descriptive_options(
                applied,
                {"ppt_typography": requested},
                LOCK_TEXT,
                DESIGN_TEXT,
            )

    def test_explicit_color_cannot_be_ignored(self) -> None:
        requested = "Use a warm coral and cream palette"
        applied = {**AUTO_APPLIED, "color_direction": requested}
        with self.assertRaisesRegex(
            RuntimeError,
            "did not record the requested color",
        ):
            audit_descriptive_options(
                applied,
                {"ppt_color": requested},
                LOCK_TEXT,
                DESIGN_TEXT,
            )


class ExportFlagValidatorTests(unittest.TestCase):
    def test_accepts_tokenized_production_receipt(self) -> None:
        audit_export_flags(["-t", "fade", "-a", "none"], ["-t fade", "-a none"])

    def test_accepts_grouped_receipt(self) -> None:
        audit_export_flags(["-t fade", "-a none"], ["-t fade", "-a none"])

    def test_rejects_an_option_that_was_not_applied(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "export flags mismatch"):
            audit_export_flags(
                ["-t", "none", "-a", "none"],
                ["-t fade", "-a none"],
            )


if __name__ == "__main__":
    unittest.main()
