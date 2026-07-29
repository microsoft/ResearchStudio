from __future__ import annotations

import functools
import hashlib
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_poster_slides_view as builder  # noqa: E402
import build_reel_from_paper as bootstrap  # noqa: E402
import check_reel_package as checker  # noqa: E402
import reel_downloads  # noqa: E402
from serve_reel import RangeRequestHandler, ThreadedRangeHTTPServer  # noqa: E402


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


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
            download_manifest = read_json(
                bundle / reel_downloads.DOWNLOAD_MANIFEST_PATH
            )
            self.assertEqual(
                reel_downloads.DOWNLOAD_SCHEMA_VERSION,
                download_manifest["schema_version"],
            )
            self.assertEqual("materialized", download_manifest["delivery"])
            self.assertEqual(
                set(reel_downloads.ARCHIVE_ORDER),
                set(download_manifest["archives"]),
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

    def test_materialized_separate_sources_allow_same_relative_source_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outdir = root / "reel"
            poster = root / "poster"
            video = root / "video"
            blog = root / "blog"
            write(poster / "poster.png", b"poster")
            write(video / "video.mp4", b"video")
            write(blog / "blog_en.docx", b"blog")
            for source in (poster, video, blog):
                write(source / "manifest.json", b"{}")

            builder.build_downloads(
                outdir=outdir,
                poster_final_dir=poster,
                video_final_dir=video,
                blog_final_dir=blog,
                download_mode="materialized",
            )

            manifest = read_json(outdir / reel_downloads.DOWNLOAD_MANIFEST_PATH)
            self.assertEqual(
                [],
                reel_downloads.validate_download_manifest(
                    manifest,
                    bundle_root=outdir,
                    require_sources=False,
                ),
            )
            all_names = zip_names(
                outdir / "assets" / "downloads" / "all_final.zip"
            )
            self.assertIn("poster/manifest.json", all_names)
            self.assertIn("video/manifest.json", all_names)
            self.assertIn("blog/manifest.json", all_names)

    def test_on_demand_writes_manifest_without_persistent_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self.make_shared_bundle(Path(tmp))
            downloads = builder.build_downloads(
                outdir=bundle,
                poster_final_dir=bundle,
                blog_final_dir=bundle,
                video_final_dir=bundle,
                download_mode="on_demand",
            )

            self.assertEqual(
                [
                    {"label": "All", "href": "__download__/all"},
                    {"label": "Poster", "href": "__download__/poster"},
                    {"label": "Video", "href": "__download__/video"},
                    {"label": "Blog", "href": "__download__/blog"},
                ],
                downloads,
            )
            self.assertFalse((bundle / "assets" / "downloads").exists())
            manifest = read_json(bundle / reel_downloads.DOWNLOAD_MANIFEST_PATH)
            self.assertEqual("on_demand", manifest["delivery"])
            self.assertEqual(
                set(reel_downloads.ARCHIVE_ORDER),
                set(manifest["archives"]),
            )

            video_files = {
                item["arcname"]
                for item in manifest["archives"]["video"]["files"]
            }
            self.assertEqual(
                {
                    "video.mp4",
                    "video.pptx",
                    "assets/captions/video.vtt",
                },
                video_files,
            )
            poster_files = {
                item["arcname"]
                for item in manifest["archives"]["poster"]["files"]
            }
            self.assertIn("poster.html", poster_files)
            self.assertIn("assets/figures/figure1.png", poster_files)
            self.assertNotIn("video.mp4", poster_files)
            all_files = manifest["archives"]["all"]["files"]
            self.assertEqual(
                len(all_files),
                len({item["arcname"] for item in all_files}),
            )
            serialized = json.dumps(manifest)
            self.assertNotIn(".claude", serialized)
            self.assertNotIn("assets/downloads", serialized)
            self.assertNotIn("figure1.png.bak", serialized)
            self.assertEqual(
                [],
                reel_downloads.validate_download_manifest(
                    manifest,
                    bundle_root=bundle,
                    require_sources=True,
                ),
            )


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
            manifest = {
                "schema_version": reel_downloads.DOWNLOAD_SCHEMA_VERSION,
                "delivery": "materialized",
                "archives": {
                    kind: {
                        **reel_downloads.ARCHIVE_META[kind],
                        "files": [],
                    }
                    for kind in reel_downloads.ARCHIVE_ORDER
                },
            }
            reel_downloads.write_download_manifest(
                root / reel_downloads.DOWNLOAD_MANIFEST_PATH,
                manifest,
            )
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


class ReelOnDemandCheckerTests(unittest.TestCase):
    def make_bundle(self, root: Path) -> Path:
        bundle = ReelDownloadBuilderTests().make_shared_bundle(root)
        builder.build_downloads(
            outdir=bundle,
            poster_final_dir=bundle,
            blog_final_dir=bundle,
            video_final_dir=bundle,
            download_mode="on_demand",
        )
        return bundle

    def findings_for(self, root: Path) -> list[dict]:
        findings: list[dict] = []
        checker.validate_download_contract(findings, root)
        return findings

    def test_valid_manifest_and_sources_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_bundle(Path(tmp))
            self.assertEqual([], self.findings_for(root))

    def test_stale_persistent_zip_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_bundle(Path(tmp))
            write(root / "assets" / "downloads" / "old.zip", b"old")
            codes = {finding["code"] for finding in self.findings_for(root)}
            self.assertIn("ON_DEMAND_ARCHIVE_PERSISTED", codes)

    def test_unsafe_manifest_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_bundle(Path(tmp))
            path = root / reel_downloads.DOWNLOAD_MANIFEST_PATH
            manifest = read_json(path)
            manifest["archives"]["blog"]["files"][0]["path"] = "../secret"
            reel_downloads.write_download_manifest(path, manifest)
            codes = {finding["code"] for finding in self.findings_for(root)}
            self.assertIn("DOWNLOAD_SOURCE_PATH_UNSAFE", codes)

    def test_control_character_in_manifest_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_bundle(Path(tmp))
            path = root / reel_downloads.DOWNLOAD_MANIFEST_PATH
            manifest = read_json(path)
            manifest["archives"]["blog"]["files"][0]["arcname"] += "\n"
            reel_downloads.write_download_manifest(path, manifest)
            codes = {finding["code"] for finding in self.findings_for(root)}
            self.assertIn("DOWNLOAD_ARCHIVE_PATH_UNSAFE", codes)

    def test_cross_module_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_bundle(Path(tmp))
            path = root / reel_downloads.DOWNLOAD_MANIFEST_PATH
            manifest = read_json(path)
            leaked = dict(manifest["archives"]["video"]["files"][0])
            manifest["archives"]["poster"]["files"].append(leaked)
            reel_downloads.write_download_manifest(path, manifest)
            codes = {finding["code"] for finding in self.findings_for(root)}
            self.assertIn("DOWNLOAD_FILE_CLASSIFICATION_INVALID", codes)

    def test_missing_source_and_size_drift_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_bundle(Path(tmp))
            (root / "video.mp4").unlink()
            write(root / "blog_en.docx", b"changed-size")
            codes = {finding["code"] for finding in self.findings_for(root)}
            self.assertIn("DOWNLOAD_SOURCE_MISSING", codes)
            self.assertIn("DOWNLOAD_SOURCE_SIZE_MISMATCH", codes)


class ReelOnDemandServerTests(unittest.TestCase):
    def test_server_streams_manifest_archive_without_persisting_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = ReelDownloadBuilderTests().make_shared_bundle(Path(tmp))
            builder.build_downloads(
                outdir=root,
                poster_final_dir=root,
                blog_final_dir=root,
                video_final_dir=root,
                download_mode="on_demand",
            )
            handler = functools.partial(
                RangeRequestHandler,
                directory=str(root.resolve()),
            )
            try:
                httpd = ThreadedRangeHTTPServer(("127.0.0.1", 0), handler)
            except PermissionError:
                self.skipTest("loopback sockets are unavailable in this sandbox")
            with httpd:
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                port = int(httpd.server_address[1])
                try:
                    head = urllib.request.Request(
                        f"http://127.0.0.1:{port}/__download__/all",
                        method="HEAD",
                    )
                    with urllib.request.urlopen(head, timeout=5) as response:
                        self.assertEqual(200, response.status)
                        self.assertIn(
                            "all_final.zip",
                            response.headers["Content-Disposition"],
                        )
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/__download__/blog",
                        timeout=5,
                    ) as response:
                        payload = response.read()
                finally:
                    httpd.shutdown()
                    thread.join(timeout=2)

            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                self.assertEqual(
                    {"blog_en.docx", "blog_zh.docx"},
                    set(archive.namelist()),
                )
            self.assertFalse((root / "assets" / "downloads").exists())


class ReelPublishTests(unittest.TestCase):
    def test_on_demand_publish_removes_old_archives_and_rebuilds_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = ReelDownloadBuilderTests().make_shared_bundle(base)
            staging = base / "staging"
            write(staging / "reel.html", b"<html></html>")
            write(staging / "content_alignment.json", b"{}")
            write(
                staging / "manifest.json",
                json.dumps(
                    {
                        "schema_version": "paper2reel.v1",
                        "local_open": {"supported": True},
                    }
                ).encode(),
            )
            write(
                staging / reel_downloads.DOWNLOAD_MANIFEST_PATH,
                b"{}",
            )
            write(target / "assets" / "downloads" / "legacy.zip", b"legacy")

            bootstrap.sync_reel_into_bundle(
                staging,
                target,
                download_mode="on_demand",
            )

            self.assertFalse((target / "assets" / "downloads").exists())
            manifest = read_json(target / reel_downloads.DOWNLOAD_MANIFEST_PATH)
            self.assertEqual("on_demand", manifest["delivery"])
            self.assertEqual(
                [],
                reel_downloads.validate_download_manifest(
                    manifest,
                    bundle_root=target,
                    require_sources=True,
                ),
            )
            root_manifest = read_json(target / "manifest.json")
            reel_files = root_manifest["files"]["reel"]
            self.assertEqual(
                reel_downloads.DOWNLOAD_MANIFEST_PATH.as_posix(),
                reel_files["downloads_manifest"],
            )
            self.assertNotIn("downloads_dir", reel_files)


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
