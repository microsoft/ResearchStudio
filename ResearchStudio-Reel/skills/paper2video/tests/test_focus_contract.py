from __future__ import annotations

from pathlib import Path
import sys
import unittest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from focus_contract import normalize_video_focus  # noqa: E402


class FocusContractTests(unittest.TestCase):
    def test_all_pointer_spotlight_combinations_map_to_renderer_styles(self) -> None:
        expected = {
            ("cursor", "spotlight"): "spotlight_cursor",
            ("cursor", "box"): "box_cursor",
            ("cursor", "none"): "cursor",
            ("laser", "spotlight"): "spotlight_laser",
            ("laser", "box"): "box_laser",
            ("laser", "none"): "laser",
            ("none", "spotlight"): "spotlight",
            ("none", "box"): "box",
            ("none", "none"): "none",
        }
        for (pointer, spotlight), combined in expected.items():
            with self.subTest(pointer=pointer, spotlight=spotlight):
                self.assertEqual(
                    normalize_video_focus(pointer, spotlight),
                    (pointer, spotlight, combined),
                )

    def test_legacy_combined_value_is_still_accepted(self) -> None:
        self.assertEqual(
            normalize_video_focus(legacy_style="box_cursor"),
            ("cursor", "box", "box_cursor"),
        )

    def test_invalid_values_fall_back_to_current_default(self) -> None:
        self.assertEqual(
            normalize_video_focus("wand", "blur"),
            ("laser", "spotlight", "spotlight_laser"),
        )


if __name__ == "__main__":
    unittest.main()
