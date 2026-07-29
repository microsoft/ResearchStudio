from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_poster_slides_view as builder  # noqa: E402
import check_reel_package as checker  # noqa: E402


def write(path: Path, contents: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)


def write_zip(path: Path, files: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)


def zip_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReelDownloadBuilderTests(unittest.TestCase):
    def make_shared_bundle(self, root: Path) -> Path:
        bundle = root / "paper"
        files = {
            "poster.html": b"poster",
            "poster.png": b"png",
            "poster.pdf": b"pdf",
            "poster.pptx": b"poster-pptx",
            "video.mp4": b"video",
            "video.pptx": b"video-pptx",
            "video_no_subtitles.mp4": b"reel-internal-video",
            "blog_en.docx": b"english",
            "blog_zh.docx": b"chinese",
            "assets/_pptx_build/dom.json": b"{}",
            "assets/figures/figure1.png": b"figure",
            "assets/figures/figure1.png.bak": b"backup",
            "assets/fonts/font.woff2": b"font",
            "assets/logos/logo.png": b"logo",
            "assets/qr/code.png": b"qr",
            "assets/captions/video.vtt": b"WEBVTT",
            "assets/downloads/old.zip": b"old-download",
            ".claude/scratch.txt": b"internal",
        }
        for relative, contents in files.items():
            write(bundle / relative, contents)
        return bundle

    def test_shared_bundle_archives_are_separate_and_exclude_internal_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self.make_shared_bundle(Path(tmp))
            downloads = builder.build_downloads(
                outdir=bundle,
                poster_final_dir=bundle,
                blog_final_dir=bundle,
                video_final_dir=bundle,
            )

            self.assertEqual(
                ["All", "Poster", "Video", "Blog"],
                [item["label"] for item in downloads],
            )
            archive_dir = bundle / "assets" / "downloads"
            names = {
                name: zip_names(archive_dir / name)
                for name in (
                    "all_final.zip",
                    "poster_final.zip",
                    "video_final.zip",
                    "blog_final.zip",
                )
            }

            self.assertEqual(
                {
                    "video.mp4",
                    "video.pptx",
                    "assets/captions/video.vtt",
                },
                names["video_final.zip"],
            )
            self.assertEqual(
                {"blog_en.docx", "blog_zh.docx"},
                names["blog_final.zip"],
            )
            self.assertIn("poster.html", names["poster_final.zip"])
            self.assertIn(
                "assets/figures/figure1.png",
                names["poster_final.zip"],
            )
            self.assertNotIn("video.mp4", names["poster_final.zip"])
            self.assertNotIn("blog_en.docx", names["poster_final.zip"])

            expected_all = (
                names["poster_final.zip"]
                | names["video_final.zip"]
                | names["blog_final.zip"]
            )
            self.assertEqual(expected_all, names["all_final.zip"])
            for archive_names in names.values():
                self.assertFalse(
                    any(name.startswith("assets/downloads/") for name in archive_names)
                )
                self.assertFalse(any(name.startswith(".claude/") for name in archive_names))
                self.assertFalse(any(name.lower().endswith(".bak") for name in archive_names))

            module_hashes = {
                sha256(archive_dir / name)
                for name in (
                    "poster_final.zip",
                    "video_final.zip",
                    "blog_final.zip",
                )
            }
            self.assertEqual(3, len(module_hashes))

    def test_rebuilding_in_the_shared_bundle_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self.make_shared_bundle(Path(tmp))
            kwargs = {
                "outdir": bundle,
                "poster_final_dir": bundle,
                "blog_final_dir": bundle,
                "video_final_dir": bundle,
            }
            builder.build_downloads(**kwargs)
            archive_dir = bundle / "assets" / "downloads"
            archive_paths = sorted(archive_dir.glob("*_final.zip"))
            first_names = {path.name: zip_names(path) for path in archive_paths}
            first_sizes = {path.name: path.stat().st_size for path in archive_paths}

            builder.build_downloads(**kwargs)
            second_names = {path.name: zip_names(path) for path in archive_paths}
            second_sizes = {path.name: path.stat().st_size for path in archive_paths}

            self.assertEqual(first_names, second_names)
            self.assertEqual(first_sizes, second_sizes)
            for archive_names in second_names.values():
                self.assertFalse(
                    any("assets/downloads" in name for name in archive_names)
                )
                self.assertFalse(any(name.endswith(".zip") for name in archive_names))


class ReelDownloadCheckerTests(unittest.TestCase):
    def make_valid_archives(self, root: Path) -> Path:
        downloads = root / "assets" / "downloads"
        write_zip(downloads / "poster_final.zip", {"poster.html": b"poster"})
        write_zip(downloads / "video_final.zip", {"video.mp4": b"video"})
        write_zip(downloads / "blog_final.zip", {"blog_en.docx": b"blog"})
        write_zip(
            downloads / "all_final.zip",
            {
                "poster.html": b"poster",
                "video.mp4": b"video",
                "blog_en.docx": b"blog",
            },
        )
        return downloads

    def findings_for(self, root: Path) -> list[dict]:
        findings: list[dict] = []
        checker.validate_download_archives(findings, root)
        return findings

    def test_valid_separate_archives_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_valid_archives(root)
            self.assertEqual([], self.findings_for(root))

    def test_static_gate_runs_download_archive_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(checker, "validate_download_archives") as archive_gate:
                checker.validate_static(root, contract={})
            archive_gate.assert_called_once()
            self.assertEqual(root.resolve(), archive_gate.call_args.args[1])

    def test_corrupt_archive_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloads = self.make_valid_archives(root)
            (downloads / "video_final.zip").write_bytes(b"not-a-zip")

            codes = {finding["code"] for finding in self.findings_for(root)}
            self.assertIn("DOWNLOAD_ARCHIVE_INVALID", codes)

    def test_identical_module_archives_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloads = self.make_valid_archives(root)
            shared_bytes = (downloads / "poster_final.zip").read_bytes()
            (downloads / "video_final.zip").write_bytes(shared_bytes)
            (downloads / "blog_final.zip").write_bytes(shared_bytes)

            codes = {finding["code"] for finding in self.findings_for(root)}
            self.assertIn("DOWNLOAD_MODULE_ARCHIVES_IDENTICAL", codes)

    def test_cross_module_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloads = self.make_valid_archives(root)
            write_zip(
                downloads / "poster_final.zip",
                {
                    "poster.html": b"poster",
                    "video.mp4": b"leaked-video",
                },
            )

            codes = {finding["code"] for finding in self.findings_for(root)}
            self.assertIn("DOWNLOAD_ARCHIVE_CROSS_MODULE_FILE", codes)

    def test_internal_nested_download_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloads = self.make_valid_archives(root)
            write_zip(
                downloads / "blog_final.zip",
                {
                    "blog_en.docx": b"blog",
                    "assets/downloads/old.zip": b"nested",
                },
            )

            codes = {finding["code"] for finding in self.findings_for(root)}
            self.assertIn("DOWNLOAD_ARCHIVE_INTERNAL_FILE", codes)


class ReelCopyNormalizationTests(unittest.TestCase):
    def test_katex_and_backups_are_normalized_only_in_reel_copies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            original_html = (
                '<html><head>'
                '<link href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">'
                '<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>'
                '<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>'
                "</head><body></body></html>"
            )
            (source / "poster.html").parent.mkdir(parents=True)
            (source / "poster.html").write_text(original_html, encoding="utf-8")
            write(source / "assets" / "figures" / "keep.png", b"keep")
            write(source / "assets" / "figures" / "remove.png.bak", b"backup")

            reel = root / "reel"
            builder.copy_poster_bundle(source, reel)
            copied_html_path = reel / "assets" / "poster" / "poster.html"
            builder.prepare_poster_for_local_open(
                copied_html_path,
                root / "unused-mathjax-cache",
            )

            self.assertEqual(
                original_html,
                (source / "poster.html").read_text(encoding="utf-8"),
            )
            self.assertTrue(
                (source / "assets" / "figures" / "remove.png.bak").is_file()
            )
            copied_html = copied_html_path.read_text(encoding="utf-8")
            self.assertNotIn("cdn.jsdelivr.net/npm/katex", copied_html)
            self.assertIn("katex/katex.min.css", copied_html)
            self.assertTrue(
                (copied_html_path.parent / "katex" / "katex.min.css").is_file()
            )
            self.assertFalse(
                (
                    reel
                    / "assets"
                    / "poster"
                    / "assets"
                    / "figures"
                    / "remove.png.bak"
                ).exists()
            )

            blog_figures = root / "blog-figures"
            write(blog_figures / "keep.png", b"keep")
            write(blog_figures / "remove.png.bak", b"backup")
            mapping = builder.copy_blog_assets(reel, blog_figures)
            self.assertIn("keep.png", mapping)
            self.assertNotIn("remove.png.bak", mapping)
            self.assertTrue((blog_figures / "remove.png.bak").is_file())
            self.assertFalse(
                (reel / "assets" / "blog" / "figures" / "remove.png.bak").exists()
            )


if __name__ == "__main__":
    unittest.main()
