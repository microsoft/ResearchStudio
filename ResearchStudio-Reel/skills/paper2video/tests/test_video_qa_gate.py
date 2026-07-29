from __future__ import annotations

from pathlib import Path
import sys
import unittest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_video_package import Finding, findings_pass_gate  # noqa: E402


def finding(severity: str, code: str) -> Finding:
    return Finding(severity=severity, code=code, message=code)


class VideoQAGateTests(unittest.TestCase):
    def test_audio_extra_files_remains_visible_but_passes_strict_gate(self) -> None:
        findings = [finding("warning", "audio_extra_files")]
        self.assertTrue(
            findings_pass_gate(findings, fail_on_warning=True)
        )
        self.assertEqual(findings[0].severity, "warning")

    def test_other_warning_still_fails_strict_or_fail_on_warning_gate(self) -> None:
        self.assertFalse(
            findings_pass_gate(
                [finding("warning", "subtitle_duration_drift")],
                fail_on_warning=True,
            )
        )

    def test_audio_exception_does_not_hide_another_warning(self) -> None:
        self.assertFalse(
            findings_pass_gate(
                [
                    finding("warning", "audio_extra_files"),
                    finding("warning", "frame_visuals_too_small"),
                ],
                fail_on_warning=True,
            )
        )

    def test_warning_passes_when_warning_gate_is_disabled(self) -> None:
        self.assertTrue(
            findings_pass_gate(
                [finding("warning", "subtitle_duration_drift")],
                fail_on_warning=False,
            )
        )

    def test_error_always_fails_even_when_warning_gate_is_disabled(self) -> None:
        self.assertFalse(
            findings_pass_gate(
                [finding("error", "script_slide_count_mismatch")],
                fail_on_warning=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
