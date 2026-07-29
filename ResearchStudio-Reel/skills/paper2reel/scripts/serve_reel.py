#!/usr/bin/env python3
"""Serve a paper2reel bundle with byte-range support.

HTML5 video seeking depends on HTTP Range requests. Python's stock
``python -m http.server`` does not reliably serve MP4 files with
``206 Partial Content`` in our deployment, so paper2reel uses this server for
both local preview and browser QA.
"""

from __future__ import annotations

import argparse
import http
import http.server
import os
import re
import shutil
import socketserver
import tempfile
import urllib.parse
import zipfile
from pathlib import Path
from typing import BinaryIO

from reel_downloads import archive_files, read_download_manifest


RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")
DOWNLOAD_ROUTE_RE = re.compile(r"^/__download__/(all|poster|video|blog)/?$")


class RangeRequestHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler with single byte-range support."""

    range_start: int | None = None
    range_end: int | None = None

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def end_headers(self) -> None:
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def _download_kind(self) -> str | None:
        path = urllib.parse.urlsplit(self.path).path
        match = DOWNLOAD_ROUTE_RE.fullmatch(path)
        return match.group(1) if match else None

    def _download_spec(self, kind: str) -> tuple[str, list[tuple[Path, str]]]:
        bundle_root = Path(self.directory).resolve()
        manifest = read_download_manifest(bundle_root)
        return archive_files(manifest, kind, bundle_root=bundle_root)

    def _serve_download(self, kind: str, *, head_only: bool) -> None:
        try:
            filename, files = self._download_spec(kind)
        except ValueError as exc:
            self.send_error(http.HTTPStatus.CONFLICT, str(exc))
            return

        if head_only:
            self.send_response(http.HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as stream:
            with zipfile.ZipFile(
                stream,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                allowZip64=True,
            ) as archive:
                for source, arcname in files:
                    archive.write(source, arcname)
            size = stream.tell()
            stream.seek(0)
            self.send_response(http.HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            shutil.copyfileobj(stream, self.wfile, length=64 * 1024)

    def do_HEAD(self) -> None:  # noqa: N802
        kind = self._download_kind()
        if kind is None:
            super().do_HEAD()
            return
        self._serve_download(kind, head_only=True)

    def do_GET(self) -> None:  # noqa: N802
        kind = self._download_kind()
        if kind is None:
            super().do_GET()
            return
        self._serve_download(kind, head_only=False)

    def _parse_range(self, header: str, size: int) -> tuple[int, int] | None:
        match = RANGE_RE.match(header.strip())
        if not match:
            return None
        start_s, end_s = match.groups()
        if start_s == "" and end_s == "":
            return None
        if start_s == "":
            suffix = int(end_s)
            if suffix <= 0:
                return None
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
        if start >= size or end < start:
            return None
        return start, min(end, size - 1)

    def send_head(self) -> BinaryIO | None:
        self.range_start = None
        self.range_end = None
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            parts = urllib.parse.urlsplit(self.path)
            if not parts.path.endswith("/"):
                self.send_response(http.HTTPStatus.MOVED_PERMANENTLY)
                new_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path + "/", parts.query, parts.fragment))
                self.send_header("Location", new_url)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            for index in ("index.html", "index.htm"):
                index_path = os.path.join(path, index)
                if os.path.isfile(index_path):
                    path = index_path
                    break
            else:
                return self.list_directory(path)

        ctype = self.guess_type(path)
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(http.HTTPStatus.NOT_FOUND, "File not found")
            return None

        fs = os.fstat(f.fileno())
        size = fs.st_size
        range_header = self.headers.get("Range")
        if range_header:
            parsed = self._parse_range(range_header, size)
            if parsed is None:
                f.close()
                self.send_response(http.HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            start, end = parsed
            self.range_start = start
            self.range_end = end
            self.send_response(http.HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-type", ctype)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
            self.end_headers()
            f.seek(start)
            return f

        self.send_response(http.HTTPStatus.OK)
        self.send_header("Content-type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
        self.end_headers()
        return f

    def copyfile(self, source: BinaryIO, outputfile: BinaryIO) -> None:
        if self.range_start is None or self.range_end is None:
            shutil.copyfileobj(source, outputfile)
            return
        remaining = self.range_end - self.range_start + 1
        while remaining > 0:
            chunk = source.read(min(64 * 1024, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)


class ThreadedRangeHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a paper2reel bundle with HTTP Range support.")
    parser.add_argument("bundle_dir", type=Path, help="paper2reel bundle containing reel.html")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8900)
    args = parser.parse_args()

    bundle_dir = args.bundle_dir.resolve()
    if not bundle_dir.is_dir():
        raise SystemExit(f"[serve_reel] bundle directory missing: {bundle_dir}")
    handler = lambda *a, **kw: RangeRequestHandler(*a, directory=str(bundle_dir), **kw)
    with ThreadedRangeHTTPServer((args.host, args.port), handler) as httpd:
        host, port = httpd.server_address
        print(f"[serve_reel] serving {bundle_dir}")
        print(f"[serve_reel] http://{host}:{port}/reel.html")
        print("[serve_reel] Range support enabled for video seeking")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
