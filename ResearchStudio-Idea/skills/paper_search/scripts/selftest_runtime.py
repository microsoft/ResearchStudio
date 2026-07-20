#!/usr/bin/env python3
"""Offline regression tests for paper-search HTTP and worker isolation.

Run: python3 scripts/selftest_runtime.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import requests

import _http_runtime
import search_papers
import search_papers_by_arxiv
import source_worker
import search_papers_by_openreview


ENV_KEYS = {
    "PAPER_SEARCH_TIMEOUT_SECONDS",
    "PAPER_SEARCH_CONNECT_TIMEOUT_SECONDS",
    "PAPER_SEARCH_MAX_ATTEMPTS",
    *(f"PAPER_SEARCH_{source.upper()}_TIMEOUT_SECONDS" for source in search_papers.ALL_SOURCES),
}


class FakeResponse:
    def __init__(self, status_code: int, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []
        self.mounts = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0) if self.responses else FakeResponse(200)

    def mount(self, prefix, adapter):
        self.mounts[prefix] = adapter


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self._saved_env = {key: os.environ[key] for key in ENV_KEYS if key in os.environ}
        for key in ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update(self._saved_env)

    def test_timeout_defaults_override_and_validation(self):
        default = _http_runtime.get_http_config("open_alex")
        self.assertEqual(default.timeout, (15.0, 300.0))
        self.assertEqual(default.max_attempts, 4)

        os.environ["PAPER_SEARCH_TIMEOUT_SECONDS"] = "90"
        os.environ["PAPER_SEARCH_OPEN_ALEX_TIMEOUT_SECONDS"] = "12.5"
        os.environ["PAPER_SEARCH_CONNECT_TIMEOUT_SECONDS"] = "2"
        overridden = _http_runtime.get_http_config("open_alex")
        self.assertEqual(overridden.timeout, (2.0, 12.5))

        os.environ["PAPER_SEARCH_MAX_ATTEMPTS"] = "0"
        with self.assertRaisesRegex(ValueError, "positive integer"):
            _http_runtime.validate_environment(["open_alex"])

    def test_timeout_environment_rejects_every_non_positive_or_malformed_value(self):
        numeric_keys = (
            "PAPER_SEARCH_TIMEOUT_SECONDS",
            "PAPER_SEARCH_CONNECT_TIMEOUT_SECONDS",
            "PAPER_SEARCH_ARXIV_TIMEOUT_SECONDS",
        )
        for key in numeric_keys:
            for value in ("", "0", "-1", "nan", "inf", "not-a-number"):
                with self.subTest(key=key, value=value):
                    os.environ[key] = value
                    with self.assertRaises(ValueError):
                        _http_runtime.validate_environment(["arxiv"])
                    os.environ.pop(key)

        for value in ("", "0", "-1", "1.5", "not-an-integer"):
            with self.subTest(key="PAPER_SEARCH_MAX_ATTEMPTS", value=value):
                os.environ["PAPER_SEARCH_MAX_ATTEMPTS"] = value
                with self.assertRaises(ValueError):
                    _http_runtime.validate_environment(["arxiv"])
                os.environ.pop("PAPER_SEARCH_MAX_ATTEMPTS")

    def test_connection_failure_is_bounded_by_connect_timeout(self):
        session = mock.Mock()
        session.request.side_effect = requests.exceptions.ConnectTimeout("no route")
        with self.assertRaises(requests.exceptions.ConnectTimeout):
            _http_runtime.request(
                session, "GET", "https://example.invalid", source="open_alex"
            )
        self.assertEqual(session.request.call_count, 1)
        self.assertEqual(session.request.call_args.kwargs["timeout"], (15.0, 300.0))

    def test_retry_is_bounded_and_passes_timeout_tuple(self):
        session = FakeSession([FakeResponse(429) for _ in range(4)])
        with mock.patch.object(_http_runtime.time, "sleep") as sleep:
            response = _http_runtime.request(
                session, "GET", "https://example.invalid", source="crossref"
            )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(session.calls), 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [3.0, 6.0, 12.0])
        self.assertTrue(all(call[2]["timeout"] == (15.0, 300.0) for call in session.calls))

    def test_external_session_gets_timeout_and_finite_adapter(self):
        session = FakeSession()
        _http_runtime.configure_external_session(session, "openreview")
        session.request("GET", "https://example.invalid")
        self.assertEqual(session.calls[0][2]["timeout"], (15.0, 300.0))
        self.assertEqual(session.mounts["https://"].max_retries.total, 3)

    def test_read_timeout_is_idle_not_total_duration(self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format, *_args):
                pass

            def do_GET(self):
                body = b"abcd"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    for index, byte in enumerate(body):
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        if self.path == "/stall" and index == 0:
                            time.sleep(0.25)
                        elif self.path == "/progress" and index < len(body) - 1:
                            time.sleep(0.07)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ["PAPER_SEARCH_TIMEOUT_SECONDS"] = "0.12"
        os.environ["PAPER_SEARCH_CONNECT_TIMEOUT_SECONDS"] = "0.12"
        os.environ["PAPER_SEARCH_MAX_ATTEMPTS"] = "1"
        session = _http_runtime.create_session()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with self.assertRaises(requests.exceptions.RequestException):
                _http_runtime.request(session, "GET", base + "/stall", source="arxiv")
            response = _http_runtime.request(
                session, "GET", base + "/progress", source="arxiv"
            )
            self.assertEqual(response.content, b"abcd")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class WorkerTests(unittest.TestCase):
    def test_worker_preserves_query_order_and_continues_after_error(self):
        calls = []

        def connector(query, start_year, end_year, max_results):
            calls.append((query, start_year, end_year, max_results))
            if query == "bad":
                raise RuntimeError("boom")
            return [
                {"title": query, "source": "arxiv"},
                {"title": "duplicate", "source": "arxiv"},
            ]

        with mock.patch.object(source_worker, "_load_source_func", return_value=connector):
            payload = source_worker.run_source(
                "arxiv", ["first", "bad", "last"], 2020, 2026, 7
            )
        self.assertEqual(
            [paper["title"] for paper in payload["papers"]],
            ["first", "duplicate", "last", "duplicate"],
        )
        self.assertEqual([call[0] for call in calls], ["first", "bad", "last"])
        self.assertTrue(all(call[3] == 7 for call in calls))
        self.assertEqual(payload["errors"][0]["query"], "bad")

    def test_atomic_result_envelope(self):
        payload = {"source": "arxiv", "papers": [{"title": "x"}], "errors": []}
        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir) / "result.json"
            source_worker.write_atomic(out, payload)
            self.assertEqual(json.loads(out.read_text()), payload)
            self.assertEqual(list(Path(temp_dir).glob("*.tmp")), [])

    @staticmethod
    def _fake_worker_command(source, queries, start_year, end_year, max_results, out_path):
        code = (
            "import json,sys,time; "
            "out,source=sys.argv[1:3]; "
            "started=time.time(); time.sleep(0.2); finished=time.time(); "
            "json.dump({'source':source,'papers':[{'source':source,'started':started,'finished':finished}],"
            "'errors':[]},open(out,'w'))"
        )
        return [sys.executable, "-c", code, str(out_path), source]

    def test_sources_overlap_in_parallel_and_serialize_when_disabled(self):
        sources = ["arxiv", "dblp"]
        with mock.patch.object(search_papers, "_worker_command", self._fake_worker_command):
            parallel = search_papers._run_source_workers(
                sources, ["q"], 2020, 2026, 1, parallel=True
            )
            serial = search_papers._run_source_workers(
                sources, ["q"], 2020, 2026, 1, parallel=False
            )
        first_p, second_p = parallel["arxiv"][0], parallel["dblp"][0]
        self.assertLess(max(first_p["started"], second_p["started"]), min(first_p["finished"], second_p["finished"]))
        first_s, second_s = serial["arxiv"][0], serial["dblp"][0]
        self.assertGreaterEqual(second_s["started"], first_s["finished"])
        self.assertEqual(list(parallel), sources)

    def test_worker_crash_and_invalid_json_do_not_cancel_other_sources(self):
        def command(source, queries, start_year, end_year, max_results, out_path):
            if source == "arxiv":
                return [sys.executable, "-c", "raise SystemExit(7)"]
            if source == "dblp":
                return [
                    sys.executable,
                    "-c",
                    "import sys; open(sys.argv[1],'w').write('not json')",
                    str(out_path),
                ]
            if source == "open_alex":
                return [sys.executable, "-c", "raise SystemExit(0)"]
            code = (
                "import json,sys; out,source=sys.argv[1:3]; "
                "json.dump({'source':source,'papers':[{'title':'ok'}],'errors':[]},open(out,'w'))"
            )
            return [sys.executable, "-c", code, str(out_path), source]

        sources = ["arxiv", "dblp", "open_alex", "crossref"]
        with mock.patch.object(search_papers, "_worker_command", command):
            result = search_papers._run_source_workers(
                sources, ["q"], 2020, 2026, 1, parallel=True
            )
        self.assertEqual(result["arxiv"], [])
        self.assertEqual(result["dblp"], [])
        self.assertEqual(result["open_alex"], [])
        self.assertEqual(result["crossref"], [{"title": "ok"}])

    def test_interrupt_terminates_all_started_workers(self):
        started = []
        original_start = search_papers._start_worker

        def command(_source, _queries, _start_year, _end_year, _max_results, _out):
            return [sys.executable, "-c", "import time; time.sleep(30)"]

        def recording_start(*args, **kwargs):
            state = original_start(*args, **kwargs)
            started.append(state[0])
            return state

        with mock.patch.object(search_papers, "_worker_command", command), mock.patch.object(
            search_papers, "_start_worker", side_effect=recording_start
        ), mock.patch.object(
            search_papers, "_collect_worker", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                search_papers._run_source_workers(
                    ["arxiv", "dblp"], ["q"], 2020, 2026, 1, parallel=True
                )

        self.assertEqual(len(started), 2)
        self.assertTrue(all(process.poll() is not None for process in started))

    def test_public_api_keeps_order_and_applies_date_filter_after_workers(self):
        raw = {
            "dblp": [{"title": "old", "publication_date": "2023-01-01"}],
            "arxiv": [{"title": "new", "publication_date": "2025-02-01"}],
        }
        with mock.patch.object(search_papers, "_run_source_workers", return_value=raw):
            result = search_papers.search_papers(
                "q",
                2023,
                2025,
                sources=["dblp", "arxiv"],
                start_date="2024-01-01",
            )
        self.assertEqual(list(result), ["dblp", "arxiv"])
        self.assertEqual(result["dblp"], [])
        self.assertEqual(result["arxiv"][0]["title"], "new")

    def test_invalid_runtime_configuration_fails_before_starting_workers(self):
        with mock.patch.dict(
            os.environ, {"PAPER_SEARCH_TIMEOUT_SECONDS": "invalid"}, clear=False
        ), mock.patch.object(search_papers, "_run_source_workers") as run_workers:
            with self.assertRaises(ValueError):
                search_papers.search_papers(
                    "q", 2023, 2025, sources=["arxiv"], parallel=True
                )
        run_workers.assert_not_called()


class OpenReviewTests(unittest.TestCase):
    def test_clients_are_configured_before_explicit_login(self):
        created = []

        class Client:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.session = FakeSession()
                self.logins = []
                created.append(self)

            def login_user(self, **kwargs):
                self.logins.append(kwargs)
                self.session.request("POST", self.kwargs["baseurl"] + "/login")

        fake_openreview = type(
            "FakeOpenReview",
            (), {"api": type("API", (), {"OpenReviewClient": Client}), "Client": Client},
        )
        env = {"OPENREVIEW_USER": "user", "OPENREVIEW_PASS": "pass"}
        with mock.patch.dict(sys.modules, {"openreview": fake_openreview}), mock.patch.dict(
            os.environ, env, clear=False
        ):
            v2, v1 = search_papers_by_openreview._openreview_clients()

        self.assertEqual(len(created), 2)
        self.assertTrue(all(set(client.kwargs) == {"baseurl"} for client in created))
        self.assertEqual(v2.logins, [{"username": "user", "password": "pass"}])
        self.assertEqual(v1.logins, [{"username": "user", "password": "pass"}])
        self.assertTrue(
            all(client.session.calls[0][2]["timeout"] == (15.0, 300.0) for client in created)
        )
        v2.session.request("GET", "https://example.invalid")
        self.assertEqual(v2.session.calls[-1][2]["timeout"], (15.0, 300.0))

    def test_full_recall_path_still_uses_get_all_notes(self):
        note = object()

        class V2:
            def get_all_notes(self, **kwargs):
                self.kwargs = kwargs
                return [note]

        class V1:
            def get_all_notes(self, **_kwargs):
                raise AssertionError("v1 fallback should not run")

        v2 = V2()
        self.assertEqual(
            search_papers_by_openreview._fetch_venue_notes(v2, V1(), "Venue"),
            [note],
        )
        self.assertEqual(v2.kwargs, {"content": {"venueid": "Venue"}})


class ArxivSchemaTests(unittest.TestCase):
    def test_mock_response_matches_legacy_fixture_output(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry>
            <id>https://arxiv.org/abs/2401.12345v2</id>
            <published>2024-01-20T00:00:00Z</published>
            <title> A Test Paper </title>
            <summary> Abstract body. </summary>
            <author><name>Alice</name></author>
            <author><name>Bob</name></author>
            <arxiv:doi>10.1000/test</arxiv:doi>
          </entry>
        </feed>"""
        response = mock.Mock()
        response.content = xml.encode("utf-8")
        with mock.patch.object(
            search_papers_by_arxiv, "request", return_value=response
        ) as request:
            papers = search_papers_by_arxiv.search_papers_by_arxiv(
                "test query", 2024, 2026, 10
            )
        response.raise_for_status.assert_called_once_with()
        self.assertEqual(request.call_args.kwargs["source"], "arxiv")
        self.assertIs(request.call_args.kwargs["before_attempt"], search_papers_by_arxiv._throttle)
        self.assertEqual(
            papers,
            [{
                "title": "A Test Paper",
                "authors": ["Alice", "Bob"],
                "year": 2024,
                "abstract": "Abstract body.",
                "url": "https://arxiv.org/abs/2401.12345v2",
                "venue": "arXiv",
                "citation_count": 0,
                "publication_date": "2024-01-20",
                "source": "arxiv",
                "doi": "10.1000/test",
                "arxiv_id": "2401.12345",
            }],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
