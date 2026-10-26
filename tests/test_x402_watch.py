"""Offline contract tests for the local x402 Watch pipeline."""

from __future__ import annotations

import hashlib
import io
import json
import socket
import tempfile
import unittest
from argparse import Namespace
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from x402_watch.brave import BraveSearchClient
from x402_watch.cli import _check_models, _parser, _print_warnings
from x402_watch.config import ConfigurationError, Settings
from x402_watch.db import Store
from x402_watch.hailo import HailoWorker, HailoWorkerError
from x402_watch.hailo_worker import _diagnostic_error, _parse_tag
from x402_watch.llm import LlamaDraftWriter, LocalModelError
from x402_watch.models import (
    LANE_QUERIES,
    DraftBrief,
    DraftClaim,
    EvidenceSource,
    HailoTag,
    HeldItem,
    Lane,
    SearchHit,
)
from x402_watch.pipeline import DailyPipeline, PipelineError
from x402_watch.policy import (
    PolicyError,
    route_sensitive_sources,
    validate_draft,
)
from x402_watch.publisher import GitHubAppPublisher, GitHubPublishError
from x402_watch.render import render_brief
from x402_watch.sources import (
    FetchedPage,
    PlaywrightPageFetcher,
    SourceFetchError,
    SourceFetchFailureCategory,
)
from x402_watch.urls import UnsafeUrlError, canonicalize_url, validate_public_url

_TOTAL_SEARCH_QUERY_COUNT = sum(len(queries) for queries in LANE_QUERIES.values())


def make_source(
    lane: Lane = Lane.X402_ACP,
    *,
    excerpt: str = "A primary source describes a verified protocol update.",
    url: str = "https://example.com/update",
) -> EvidenceSource:
    content_hash = hashlib.sha256(excerpt.encode()).hexdigest()
    return EvidenceSource(
        source_id=hashlib.sha256(url.encode()).hexdigest()[:16],
        lane=lane,
        title="Protocol update",
        url=url,
        canonical_url=url,
        publisher="Example",
        published_at=None,
        retrieved_at="2026-10-24T00:00:00Z",
        content_hash=content_hash,
        excerpt=excerpt,
    )


class URLPolicyTests(unittest.TestCase):
    def test_canonical_url_removes_tracking_and_fragment(self):
        actual = canonicalize_url(
            "HTTPS://Example.COM/story?utm_source=mail&z=2&a=1#details"
        )
        self.assertEqual(actual, "https://example.com/story?z=2&a=1")

    def test_canonical_url_preserves_semantic_source_query_and_rejects_port_zero(self):
        self.assertEqual(
            canonicalize_url("https://example.com/story?source=report"),
            "https://example.com/story?source=report",
        )
        with self.assertRaises(UnsafeUrlError):
            canonicalize_url("https://example.com:0/article")

    def test_public_url_rejects_private_dns_answers(self):
        def private_resolver(host, port, type):
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("127.0.0.1", port),
                )
            ]

        with self.assertRaises(UnsafeUrlError):
            validate_public_url("https://example.com/", resolver=private_resolver)

    def test_nonstandard_ports_are_rejected(self):
        with self.assertRaises(UnsafeUrlError):
            canonicalize_url("https://example.com:8443/article")


class ConfigurationTests(unittest.TestCase):
    def test_model_endpoint_must_be_loopback(self):
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                {"X402_WATCH_LLAMA_URL": "http://192.0.2.10:8090"}
            )

    def test_model_endpoint_normalizes_localhost_and_rejects_paths(self):
        settings = Settings.from_env(
            {"X402_WATCH_LLAMA_URL": "http://localhost:8090/"}
        )
        self.assertEqual(settings.llama_url, "http://127.0.0.1:8090")
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                {"X402_WATCH_LLAMA_URL": "http://127.0.0.1:8090/api"}
            )
        with self.assertRaises(ConfigurationError):
            Settings.from_env({"X402_WATCH_LLAMA_URL": "http://127.0.0.1"})

    def test_credential_loader_fails_closed_without_credential_directory(self):
        settings = Settings(credentials_dir=None)
        with self.assertRaises(ConfigurationError):
            settings.credential("brave_api_key")

    def test_brave_key_cannot_be_sent_to_a_non_brave_endpoint(self):
        with self.assertRaises(ConfigurationError):
            BraveSearchClient("test-key", endpoint="https://example.com/search")


class SearchQueryTests(unittest.TestCase):
    def test_each_lane_has_a_primary_domain_scoped_query(self):
        for lane, queries in LANE_QUERIES.items():
            self.assertTrue(
                any(
                    "site:" in query
                    and not query.startswith("site:www.donvitocodes.com/ai-news ")
                    for query in queries
                ),
                lane.value,
            )

    def test_each_lane_has_a_domain_scoped_don_vito_discovery_query(self):
        lane_terms = {
            Lane.X402_ACP: ("x402", "Agentic Commerce Protocol"),
            Lane.GENIUS_ACT: ("GENIUS Act",),
            Lane.STABLECOIN_VOLUME: ("stablecoin", "card network"),
            Lane.STRIPE_OPENROUTER: ("Stripe", "OpenRouter"),
        }
        for lane, queries in LANE_QUERIES.items():
            scoped_queries = [
                query
                for query in queries
                if query.startswith("site:www.donvitocodes.com/ai-news ")
            ]
            self.assertEqual(len(scoped_queries), 1, lane.value)
            self.assertGreater(len(queries), len(scoped_queries), lane.value)
            for term in lane_terms[lane]:
                self.assertIn(term.lower(), scoped_queries[0].lower(), lane.value)

    def test_agent_commerce_search_avoids_ambiguous_acp_abbreviation(self):
        query_text = " ".join(LANE_QUERIES[Lane.X402_ACP])
        self.assertNotRegex(query_text, r"\bACP\b")
        self.assertIn('"Agentic Commerce Protocol"', query_text)


class CliDiagnosticsTests(unittest.TestCase):
    def test_cli_prints_sanitized_warning_codes(self):
        output = io.StringIO()
        with patch("sys.stderr", output):
            _print_warnings(("source:stablecoin-vs-card-volume:http_status_429",))
        self.assertEqual(
            output.getvalue(),
            "Warnings:\n  source:stablecoin-vs-card-volume:http_status_429\n",
        )


class SourceFetcherTests(unittest.TestCase):
    def _fake_playwright(
        self,
        *,
        status: int = 200,
        html: bytes = b"<html><body><p>Rendered update</p></body></html>",
        content_type: str = "text/html",
        content_length: str | None = None,
        final_url: str = "https://example.com/article",
        followups: tuple[tuple[str, str, str, bool], ...] = (),
    ):
        response = Mock()
        response.status = status
        response.header_value.side_effect = lambda name: {
            "content-type": content_type,
            "content-length": content_length,
        }.get(name)
        routes = []
        page = Mock()
        page.url = final_url
        page.content.return_value = html.decode("utf-8")

        def goto(url, **kwargs):
            initial_request = SimpleNamespace(
                url=url,
                method="GET",
                resource_type="document",
                redirected_from=None,
            )
            requests = [(initial_request, None)]
            previous_request = initial_request
            for followup_url, method, resource_type, is_redirect in followups:
                request = SimpleNamespace(
                    url=followup_url,
                    method=method,
                    resource_type=resource_type,
                    redirected_from=previous_request if is_redirect else None,
                )
                requests.append((request, None))
                if is_redirect:
                    previous_request = request
            for request, _ in requests:
                route = Mock()
                route.request = request
                routes.append(route)
                context.route_handler(route)
            return response

        page.goto.side_effect = goto
        context = Mock()
        context.route.side_effect = lambda _pattern, handler: setattr(
            context,
            "route_handler",
            handler,
        )
        context.new_page.return_value = page
        browser = Mock()
        browser.new_context.return_value = context
        launch = Mock(return_value=browser)
        manager = MagicMock()
        manager.__enter__.return_value = SimpleNamespace(
            chromium=SimpleNamespace(launch=launch)
        )
        return manager, launch, browser, context, page, routes

    @staticmethod
    def _public_resolver(host, port, type):
        address = "127.0.0.1" if host == "127.0.0.1" else "93.184.216.34"
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, port),
            )
        ]

    def test_playwright_fetch_returns_rendered_html_in_a_fresh_context(self):
        manager, launch, browser, context, page, routes = self._fake_playwright()
        with (
            patch("x402_watch.sources.sync_playwright", return_value=manager),
            patch.dict(
                "os.environ",
                {
                    "PATH": "/usr/bin",
                    "SYSTEMD_CREDENTIALS_DIRECTORY": "/run/credentials/private",
                },
                clear=True,
            ),
        ):
            fetcher = PlaywrightPageFetcher(resolver=self._public_resolver)
            result = fetcher.fetch("https://example.com/article?utm_source=test")

        self.assertEqual(result.url, "https://example.com/article")
        self.assertEqual(
            result.html,
            b"<html><body><p>Rendered update</p></body></html>",
        )
        self.assertEqual(result.content_type, "text/html")
        launch.assert_called_once()
        browser.new_context.assert_called_once_with(
            accept_downloads=False,
            service_workers="block",
        )
        self.assertNotIn(
            "SYSTEMD_CREDENTIALS_DIRECTORY",
            launch.call_args.kwargs["env"],
        )
        self.assertEqual(page.goto.call_args.args, ("https://example.com/article",))
        self.assertEqual(page.goto.call_args.kwargs["wait_until"], "domcontentloaded")
        self.assertGreater(page.goto.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(page.goto.call_args.kwargs["timeout"], 20_000)
        self.assertTrue(routes[0].continue_.called)
        context.close.assert_called_once()
        browser.close.assert_called_once()

    def test_http_status_error_has_a_sanitized_diagnostic_code(self):
        manager, *_ = self._fake_playwright(
            status=403,
            html=b"Private response detail",
        )
        with patch("x402_watch.sources.sync_playwright", return_value=manager):
            fetcher = PlaywrightPageFetcher(resolver=self._public_resolver)
            with self.assertRaises(SourceFetchError) as context:
                fetcher.fetch("https://example.com/article?token=fixture-secret")
            self.assertEqual(context.exception.diagnostic_code, "http_status_403")
            self.assertNotIn("fixture-secret", context.exception.diagnostic_code)
            self.assertNotIn("Private response detail", context.exception.diagnostic_code)

    def test_private_redirect_is_blocked_before_browser_continues_it(self):
        manager, _, _, _, _, routes = self._fake_playwright(
            followups=(
                ("http://127.0.0.1/private", "GET", "document", True),
            )
        )
        with patch("x402_watch.sources.sync_playwright", return_value=manager):
            fetcher = PlaywrightPageFetcher(resolver=self._public_resolver)
            with self.assertRaises(SourceFetchError) as context:
                fetcher.fetch("https://example.com/article")

        self.assertEqual(
            context.exception.category,
            SourceFetchFailureCategory.UNSAFE_URL,
        )
        self.assertTrue(routes[1].abort.called)
        self.assertFalse(routes[1].continue_.called)

    def test_redirect_limit_is_enforced(self):
        manager, _, _, _, _, routes = self._fake_playwright(
            followups=(
                ("https://example.com/step-one", "GET", "document", True),
                ("https://example.com/step-two", "GET", "document", True),
            )
        )
        with patch("x402_watch.sources.sync_playwright", return_value=manager):
            fetcher = PlaywrightPageFetcher(
                max_redirects=1,
                resolver=self._public_resolver,
            )
            with self.assertRaises(SourceFetchError) as context:
                fetcher.fetch("https://example.com/article")

        self.assertEqual(
            context.exception.category,
            SourceFetchFailureCategory.REDIRECT_LIMIT,
        )
        self.assertTrue(routes[2].abort.called)

    def test_rendered_document_byte_limit_is_enforced(self):
        manager, *_ = self._fake_playwright(html=b"x" * 1025)
        with patch("x402_watch.sources.sync_playwright", return_value=manager):
            fetcher = PlaywrightPageFetcher(
                max_bytes=1024,
                resolver=self._public_resolver,
            )
            with self.assertRaises(SourceFetchError) as context:
                fetcher.fetch("https://example.com/article")

        self.assertEqual(
            context.exception.category,
            SourceFetchFailureCategory.RESPONSE_TOO_LARGE,
        )

    def test_non_get_browser_requests_are_blocked(self):
        manager, _, _, _, _, routes = self._fake_playwright(
            followups=(("https://example.com/submit", "POST", "xhr", False),)
        )
        with patch("x402_watch.sources.sync_playwright", return_value=manager):
            fetcher = PlaywrightPageFetcher(resolver=self._public_resolver)
            with self.assertRaises(SourceFetchError) as context:
                fetcher.fetch("https://example.com/article")

        self.assertEqual(
            context.exception.category,
            SourceFetchFailureCategory.UNSAFE_REQUEST,
        )
        self.assertTrue(routes[1].abort.called)


class HailoWorkerTests(unittest.TestCase):
    def test_parse_tag_removes_hailo_chat_end_token(self):
        self.assertEqual(
            _parse_tag("not_relevant.<|im_end|>"),
            {"relevance": "not_relevant"},
        )
        with self.assertRaises(ValueError):
            _parse_tag("unrecognized<|im_end|>")

    def test_worker_diagnostic_redacts_model_and_evidence_text(self):
        model_path = "/opt/x402-watch/model.hef"
        evidence = ("private title", "private source snippet")
        diagnostic = _diagnostic_error(
            "model_load",
            RuntimeError(
                f"Could not load {model_path} for {evidence[0]}: {evidence[1]}"
            ),
            model_path=model_path,
            evidence=evidence,
        )
        self.assertEqual(diagnostic["stage"], "model_load")
        self.assertEqual(diagnostic["exception"], "RuntimeError")
        self.assertNotIn(model_path, diagnostic["message"])
        self.assertNotIn(evidence[0], diagnostic["message"])
        self.assertNotIn(evidence[1], diagnostic["message"])

    def test_worker_diagnostic_omits_inference_exception_text(self):
        diagnostic = _diagnostic_error(
            "inference",
            RuntimeError("failure while processing private source text"),
            evidence=("private source text",),
        )
        self.assertEqual(diagnostic["message"], "")
        hailo_error = _diagnostic_error(
            "inference",
            RuntimeError("HAILO_OUT_OF_PHYSICAL_DEVICES for private source text"),
            evidence=("private source text",),
        )
        self.assertEqual(hailo_error["message"], "HAILO_OUT_OF_PHYSICAL_DEVICES")

    def test_worker_spawn_error_is_reported_as_optional_hailo_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / "python"
            model = Path(directory) / "model.hef"
            python.write_text("placeholder", encoding="utf-8")
            model.write_bytes(b"placeholder")
            data_dir = Path(directory) / "state"
            worker = HailoWorker(
                Settings(data_dir=data_dir, hailo_python=python, hailo_model=model)
            )
            with patch(
                "x402_watch.hailo.subprocess.Popen",
                side_effect=OSError("cannot execute"),
            ) as spawn:
                with self.assertRaises(HailoWorkerError):
                    worker.start()
                hailo_home = data_dir / "hailo-home"
                self.assertTrue(hailo_home.is_dir())
                self.assertEqual(
                    spawn.call_args.kwargs["env"]["HOME"],
                    str(hailo_home),
                )

    def test_worker_startup_response_preserves_sanitized_cause(self):
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / "python"
            model = Path(directory) / "model.hef"
            python.write_text("placeholder", encoding="utf-8")
            model.write_bytes(b"placeholder")
            process = SimpleNamespace(
                stdin=io.StringIO(),
                stdout=io.StringIO(
                    json.dumps(
                        {
                            "ok": False,
                            "error": {
                                "stage": "runtime_import",
                                "exception": "ModuleNotFoundError",
                                "message": "No module named 'hailo_platform'",
                            },
                        }
                    )
                    + "\n"
                ),
                poll=Mock(return_value=1),
                returncode=1,
            )
            selector = MagicMock()
            selector.select.return_value = [(None, None)]
            worker = HailoWorker(
                Settings(
                    data_dir=Path(directory) / "state",
                    hailo_python=python,
                    hailo_model=model,
                )
            )
            with (
                patch("x402_watch.hailo.subprocess.Popen", return_value=process),
                patch(
                    "x402_watch.hailo.selectors.DefaultSelector",
                    return_value=selector,
                ),
                self.assertRaises(HailoWorkerError) as raised,
            ):
                worker.start()

        self.assertEqual(
            raised.exception.diagnostic,
            "runtime_import:ModuleNotFoundError: No module named 'hailo_platform'",
        )

    def test_inference_diagnostic_redacts_evidence_paths_urls_and_secrets(self):
        hit = SearchHit(
            title="Private evidence title",
            url="https://example.com/article",
            snippet="Private evidence snippet",
        )
        response = {
            "ok": False,
            "error": {
                "stage": "inference",
                "exception": "HailoRTException",
                "message": (
                    f"Failed for {hit.title} {hit.snippet} at /tmp/model.hef; "
                    "token=fixture-secret; "
                    "{\"api_key\":\"fixture-json-secret\"}; "
                    "https://example.com/article?key=fixture-secret"
                ),
            },
        }
        process = SimpleNamespace(
            stdin=io.StringIO(),
            stdout=io.StringIO(json.dumps(response) + "\n"),
            poll=Mock(return_value=1),
            returncode=1,
        )
        selector = MagicMock()
        selector.select.return_value = [(None, None)]
        worker = HailoWorker(Settings())
        worker._process = process
        worker._selector = selector

        with self.assertRaises(HailoWorkerError) as raised:
            worker.classify(hit)
        worker.stop()

        self.assertTrue(raised.exception.diagnostic.startswith("inference:"))
        for sensitive_value in (
            hit.title,
            hit.snippet,
            "/tmp/model.hef",
            "fixture-secret",
            "fixture-json-secret",
            "https://example.com",
        ):
            self.assertNotIn(sensitive_value, raised.exception.diagnostic)


class LocalPromptTests(unittest.TestCase):
    def test_writer_receives_bounded_evidence_without_full_urls(self):
        captured = {}

        def handler(request):
            captured.update(json.loads(request.read()))
            captured["request_timeout"] = request.extensions.get("timeout")
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"claims":[],"held_items":[],'
                                    '"no_material_change":true}'
                                )
                            }
                        }
                    ]
                },
            )

        source = make_source().model_copy(
            update={
                "title": "t" * 500,
                "publisher": "p" * 300,
                "published_at": "d" * 128,
                "excerpt": "e" * 1800,
            }
        )
        client = httpx.Client(transport=httpx.MockTransport(handler))
        writer = LlamaDraftWriter(Settings(), client=client)
        try:
            draft = writer._write(date.today(), [source], True, False)
        finally:
            writer.close()
            client.close()
        payload = json.loads(captured["messages"][1]["content"])
        evidence = payload["evidence"][0]
        self.assertTrue(draft.no_material_change)
        self.assertEqual(
            captured["chat_template_kwargs"],
            {"enable_thinking": False},
        )
        self.assertEqual(captured["max_tokens"], 2600)
        self.assertEqual(captured["request_timeout"]["read"], 2400.0)
        self.assertNotIn("url", evidence)
        self.assertEqual(len(evidence["title"]), 180)
        self.assertEqual(len(evidence["publisher"]), 80)
        self.assertEqual(len(evidence["published_at"]), 48)
        self.assertEqual(len(evidence["excerpt"]), 400)
        self.assertLessEqual(len(captured["messages"][1]["content"]), 20_000)
        system_prompt = captured["messages"][0]["content"]
        self.assertIn("no summary field", system_prompt)
        self.assertIn("allowed_source_ids", system_prompt)
        self.assertIn("held_items for Hans's review", system_prompt)
        self.assertNotIn("hve-cfo", system_prompt)
        self.assertIn(
            "Don Vito Codes AI News only as a secondary discovery source",
            system_prompt,
        )
        self.assertEqual(payload["allowed_source_ids"], [source.source_id])
        response_format = captured["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        schema = response_format["json_schema"]["schema"]
        for definition_name in ("DraftClaim", "HeldItem"):
            self.assertEqual(
                schema["$defs"][definition_name]["properties"]["source_ids"][
                    "items"
                ]["enum"],
                [source.source_id],
            )

    def test_writer_constrains_empty_evidence_to_empty_item_lists(self):
        captured = {}

        def handler(request):
            captured.update(json.loads(request.read()))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"claims":[],"held_items":[],'
                                    '"no_material_change":false}'
                                )
                            }
                        }
                    ]
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        writer = LlamaDraftWriter(Settings(), client=client)
        try:
            writer._write(date.today(), [], False, False)
        finally:
            writer.close()
            client.close()
        payload = json.loads(captured["messages"][1]["content"])
        schema = captured["response_format"]["json_schema"]["schema"]
        self.assertEqual(payload["allowed_source_ids"], [])
        self.assertEqual(schema["properties"]["claims"]["maxItems"], 0)
        self.assertEqual(schema["properties"]["held_items"]["maxItems"], 0)

    def test_writer_rejects_evidence_over_the_prompt_budget(self):
        def handler(request):
            self.fail("Oversized evidence must not be sent to the model")

        source = make_source().model_copy(
            update={
                "title": "t" * 500,
                "publisher": "p" * 300,
                "published_at": "d" * 128,
                "excerpt": "e" * 1800,
            }
        )
        client = httpx.Client(transport=httpx.MockTransport(handler))
        writer = LlamaDraftWriter(Settings(), client=client)
        try:
            with self.assertRaises(LocalModelError):
                writer._write(date.today(), [source] * 40, True, False)
        finally:
            writer.close()
            client.close()

    def test_writer_reports_cpu_inference_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout("timed out")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        writer = LlamaDraftWriter(Settings(), client=client)
        try:
            with self.assertRaisesRegex(
                LocalModelError,
                "inference timed out after 2400s",
            ):
                writer._write(date.today(), [make_source()], True, False)
        finally:
            writer.close()
            client.close()


class ModelCheckTests(unittest.TestCase):
    def _run_check(self, content: str):
        captured = {}

        def handler(request):
            captured.update(json.loads(request.read()))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": content,
                            }
                        }
                    ]
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            server = Path(directory) / "llama-server"
            model = Path(directory) / "model.gguf"
            server.touch()
            model.touch()
            client = httpx.Client(transport=httpx.MockTransport(handler))
            try:
                with (
                    patch(
                        "x402_watch.cli.LocalLlamaServer",
                        return_value=nullcontext(),
                    ),
                    patch("x402_watch.cli.httpx.Client", return_value=client),
                ):
                    result = _check_models(
                        Namespace(skip_cpu=False, skip_hailo=True),
                        Settings(llama_server=server, llama_model=model),
                    )
            finally:
                client.close()
        return result, captured

    def test_check_models_disables_qwen_thinking_and_requires_content(self):
        result, request = self._run_check("ready")
        self.assertEqual(result, 0)
        self.assertEqual(
            request["chat_template_kwargs"],
            {"enable_thinking": False},
        )

    def test_check_models_rejects_empty_model_content(self):
        with self.assertRaisesRegex(LocalModelError, "empty response"):
            self._run_check("")

    def test_check_models_can_run_hailo_only_without_cpu_models(self):
        with tempfile.TemporaryDirectory() as directory:
            hailo_model = Path(directory) / "model.hef"
            hailo_model.touch()
            missing = Path(directory) / "missing"
            worker = Mock()
            worker.classify.return_value = HailoTag(relevance="uncertain")
            settings = Settings(
                llama_server=missing,
                llama_model=missing,
                hailo_model=hailo_model,
            )
            output = io.StringIO()
            with (
                patch(
                    "x402_watch.cli.HailoWorker",
                    return_value=nullcontext(worker),
                ),
                patch("x402_watch.cli.LocalLlamaServer") as cpu_server,
                patch("sys.stdout", output),
            ):
                result = _check_models(
                    Namespace(skip_cpu=True, skip_hailo=False),
                    settings,
                )

        self.assertEqual(result, 0)
        cpu_server.assert_not_called()
        worker.classify.assert_called_once()
        self.assertIn("CPU inference: skipped by request", output.getvalue())

    def test_model_check_skip_options_are_mutually_exclusive(self):
        parsed = _parser().parse_args(["check-models", "--skip-cpu"])
        self.assertTrue(parsed.skip_cpu)
        self.assertFalse(parsed.skip_hailo)

        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            _parser().parse_args(["check-models", "--skip-cpu", "--skip-hailo"])


class OutboxTests(unittest.TestCase):
    def test_new_same_day_brief_supersedes_older_pending_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "x402-watch.sqlite3")
            brief_date = date.today().isoformat()
            store.start_run("older", brief_date, "2026-10-24T00:00:00Z")
            store.save_brief(
                "older",
                brief_date,
                "# older",
                "passed",
                "2026-10-24T00:01:00Z",
                publish_requested=True,
            )
            store.start_run("newer", brief_date, "2026-10-24T00:02:00Z")
            store.save_brief(
                "newer",
                brief_date,
                "# newer",
                "passed",
                "2026-10-24T00:03:00Z",
                publish_requested=True,
            )
            pending = store.pending_outbox()
            self.assertEqual([item["run_id"] for item in pending], ["newer"])
            store.close()


class RenderingTests(unittest.TestCase):
    def test_untrusted_html_and_dates_are_escaped_in_markdown(self):
        source = make_source().model_copy(
            update={
                "title": "<script>alert(1)</script>",
                "published_at": "2026-10-24\n| injected column |",
            }
        )
        markdown = render_brief(
            date.today(),
            "run-id",
            DraftBrief(no_material_change=True),
            [source],
            True,
            {"x402-acp-adoption": "searched; 1 result"},
            dry_run=False,
        )
        self.assertNotIn("<script>", markdown)
        self.assertIn("\\<script\\>", markdown)
        self.assertIn("2026-10-24 \\| injected column \\|", markdown)


class GitHubPublisherTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        credentials = Path(self._directory.name) / "credentials"
        credentials.mkdir()
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        ).private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        (credentials / "github_app_private_key").write_bytes(private_key)
        self._settings = Settings(
            credentials_dir=credentials,
            publish_enabled=True,
            github_app_id="12345",
            github_installation_id="67890",
        )

    def tearDown(self):
        self._directory.cleanup()

    def test_publisher_requires_official_api_root(self):
        settings = Settings(
            github_api="https://api.github.com/not-the-api",
            publish_enabled=True,
            github_app_id="12345",
            github_installation_id="67890",
        )
        with self.assertRaises(ConfigurationError):
            GitHubAppPublisher(settings)

    def test_invalid_branch_ref_is_rejected_before_publication(self):
        settings = Settings(
            github_branch="release/../main",
            publish_enabled=True,
            github_app_id="12345",
            github_installation_id="67890",
        )
        with self.assertRaises(ConfigurationError):
            GitHubAppPublisher(settings)

    def test_private_daily_brief_uses_repository_scoped_token(self):
        writes = []

        def handler(request):
            if request.method == "POST":
                self.assertEqual(
                    request.url.path,
                    "/app/installations/67890/access_tokens",
                )
                self.assertTrue(request.headers["authorization"].startswith("Bearer "))
                self.assertEqual(
                    json.loads(request.read()),
                    {
                        "repositories": ["x402-watch"],
                        "permissions": {"contents": "write"},
                    },
                )
                return httpx.Response(
                    201,
                    json={
                        "token": "installation-token",
                        "repository_selection": "selected",
                        "repositories": [
                            {"full_name": "HansHWestphal/x402-watch"}
                        ],
                        "permissions": {
                            "contents": "write",
                            "metadata": "read",
                        },
                    },
                )
            if request.method == "GET" and request.url.path.endswith(
                "/repos/HansHWestphal/x402-watch"
            ):
                self.assertEqual(
                    request.headers["authorization"],
                    "Bearer installation-token",
                )
                return httpx.Response(200, json={"private": True})
            if request.method == "GET" and "/contents/briefs/" in request.url.path:
                return httpx.Response(404, json={"message": "Not Found"})
            if request.method == "PUT":
                writes.append(request)
                return httpx.Response(
                    201,
                    json={"commit": {"sha": "a" * 40}},
                )
            self.fail(f"Unexpected GitHub request: {request.method} {request.url}")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        publisher = GitHubAppPublisher(self._settings, client=client)
        try:
            commit = publisher.publish(date(2026, 10, 24), "# private brief")
        finally:
            client.close()
        self.assertEqual(commit, "a" * 40)
        self.assertEqual(len(writes), 1)
        write_body = writes[0].read()
        self.assertIn(b'"branch":"main"', write_body)
        self.assertIn(b'"content"', write_body)

    def test_publisher_rejects_unrestricted_installation_token(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(
                201,
                json={
                    "token": "installation-token",
                    "repository_selection": "all",
                    "repositories": [
                        {"full_name": "HansHWestphal/x402-watch"},
                        {"full_name": "another/private-repo"},
                    ],
                    "permissions": {"contents": "write"},
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        publisher = GitHubAppPublisher(self._settings, client=client)
        try:
            with self.assertRaises(GitHubPublishError):
                publisher.publish(date(2026, 10, 24), "# private brief")
        finally:
            client.close()
        self.assertEqual(len(requests), 1)

    def test_publisher_refuses_to_write_to_a_public_repository(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "POST":
                return httpx.Response(
                    201,
                    json={
                        "token": "installation-token",
                        "repository_selection": "selected",
                        "repositories": [
                            {"full_name": "HansHWestphal/x402-watch"}
                        ],
                        "permissions": {"contents": "write"},
                    },
                )
            if request.method == "GET":
                return httpx.Response(200, json={"private": False})
            self.fail(f"Unexpected GitHub request: {request.method} {request.url}")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        publisher = GitHubAppPublisher(self._settings, client=client)
        try:
            with self.assertRaises(GitHubPublishError):
                publisher.publish(date.today(), "# private brief")
        finally:
            client.close()
        self.assertEqual([request.method for request in requests], ["POST", "GET"])


class EditorialPolicyTests(unittest.TestCase):
    def test_incomplete_coverage_cannot_claim_no_change(self):
        draft = DraftBrief(
            no_material_change=True,
        )
        with self.assertRaises(PolicyError):
            validate_draft(draft, [], coverage_complete=False)

    def test_baseline_cannot_claim_no_change(self):
        draft = DraftBrief(
            no_material_change=True,
        )
        with self.assertRaises(PolicyError):
            validate_draft(draft, [], coverage_complete=True, baseline=True)

    def test_claim_must_cite_a_known_source(self):
        source = make_source()
        draft = DraftBrief(
            claims=[
                DraftClaim(
                    text="A protocol update was published.",
                    source_ids=["unknown-source"],
                    uncertainty="The long-term effect is not yet known.",
                    why_it_matters="It may affect future adoption.",
                )
            ],
        )
        with self.assertRaises(PolicyError):
            validate_draft(draft, [source], coverage_complete=True)

    def test_explicit_empty_claim_allowlist_does_not_fall_back_to_all_sources(self):
        source = make_source()
        draft = DraftBrief(
            claims=[
                DraftClaim(
                    text="A protocol update was published.",
                    source_ids=[source.source_id],
                    uncertainty="The long-term effect is not yet known.",
                    why_it_matters="It may affect future adoption.",
                )
            ]
        )
        with self.assertRaises(PolicyError):
            validate_draft(
                draft,
                [source],
                coverage_complete=True,
                claim_source_ids=set(),
            )

    def test_completed_run_without_findings_requires_no_change_result(self):
        with self.assertRaises(PolicyError):
            validate_draft(DraftBrief(), [], coverage_complete=True)

    def test_unapproved_proposal_in_source_title_blocks_rendering(self):
        source = make_source().model_copy(
            update={"title": "The 2028 agent-mandate proposal"}
        )
        with self.assertRaises(PolicyError):
            validate_draft(
                DraftBrief(no_material_change=True),
                [source],
                coverage_complete=True,
            )

    def test_blackrock_claim_requires_the_approved_attribution(self):
        source = make_source()
        claim = DraftClaim(
            text="BlackRock estimates stablecoin growth.",
            source_ids=[source.source_id],
            uncertainty="The estimate may change.",
            why_it_matters="It is one analyst view.",
        )
        draft = DraftBrief(claims=[claim])
        with self.assertRaises(PolicyError):
            validate_draft(draft, [source], coverage_complete=True)

    def test_blackrock_claim_cannot_call_estimates_proprietary_or_established(self):
        source = make_source()
        claim = DraftClaim(
            text=(
                "Analyst estimates, per BlackRock (Sept. 2026), are "
                "proprietary data."
            ),
            source_ids=[source.source_id],
            uncertainty="The estimate may change.",
            why_it_matters="It is one analyst view.",
        )
        with self.assertRaises(PolicyError):
            validate_draft(
                DraftBrief(claims=[claim]),
                [source],
                coverage_complete=True,
            )

    def test_household_investment_recommendation_is_routed(self):
        source = make_source()
        claim = DraftClaim(
            text="Households should buy this token.",
            source_ids=[source.source_id],
            uncertainty="The price may change.",
            why_it_matters="It could produce a return.",
        )
        with self.assertRaises(PolicyError):
            validate_draft(
                DraftBrief(claims=[claim]),
                [source],
                coverage_complete=True,
            )

    def test_neutral_genius_act_source_is_not_automatically_held(self):
        source = make_source(Lane.GENIUS_ACT)
        claim = DraftClaim(
            text="The source reports an implementation update.",
            source_ids=[source.source_id],
            uncertainty="The scope of the update is not established.",
            why_it_matters="Hans can review the cited development.",
        )
        draft = route_sensitive_sources(
            DraftBrief(claims=[claim]),
            [source],
        )
        self.assertEqual(draft.held_items, [])
        self.assertEqual(draft.claims, [claim])
        validate_draft(draft, [source], coverage_complete=True)

    def test_sensitive_genius_act_source_is_held_for_hans(self):
        source = make_source(
            Lane.GENIUS_ACT,
            excerpt="This source contains a legal interpretation of the rule.",
        )
        draft = route_sensitive_sources(DraftBrief(), [source])
        self.assertEqual(len(draft.held_items), 1)
        self.assertIn(source.source_id, draft.held_items[0].source_ids)
        self.assertEqual(
            draft.held_items[0].title,
            "Financial, legal, or tax items held for Hans's review",
        )
        self.assertIn("Hans's review", draft.held_items[0].reason)
        validate_draft(draft, [source], coverage_complete=True)

    def test_sensitive_routing_respects_held_source_limit(self):
        sources = [
            make_source(url=f"https://example.com/{index}")
            for index in range(20)
        ]
        sensitive = make_source(
            Lane.GENIUS_ACT,
            excerpt="This source contains a legal interpretation of the rule.",
            url="https://example.com/financial",
        )
        draft = DraftBrief(
            held_items=[
                HeldItem(
                    title="Financial, legal, or tax items held for Hans's review",
                    source_ids=[source.source_id for source in sources],
                    reason="Held for human review.",
                )
            ]
        )
        with self.assertRaises(PolicyError):
            route_sensitive_sources(draft, [*sources, sensitive])


class _FakeSearch:
    def search(self, query: str, count: int = 5) -> list[SearchHit]:
        path = hashlib.sha256(query.encode()).hexdigest()[:12]
        return [
            SearchHit(
                title=f"Update {path}",
                url=f"https://example.com/{path}",
                snippet="A short source description.",
            )
        ]


class _FakeFetcher:
    def fetch(self, url: str) -> FetchedPage:
        html = (
            b"<html><head><title>Verified update</title></head><body>"
            b"<article><h1>Verified update</h1>"
            b"<p>A primary source describes a verified protocol update.</p>"
            b"<p>The evidence is included only for a local fixture test.</p>"
            b"</article></body></html>"
        )
        return FetchedPage(url=url, html=html, content_type="text/html")


class _DistinctFakeFetcher(_FakeFetcher):
    def fetch(self, url: str) -> FetchedPage:
        page = super().fetch(url)
        marker = url.rsplit("/", 1)[-1]
        html = page.html.replace(
            b"</article>",
            f"<p>Fixture record {marker}</p></article>".encode("ascii"),
        )
        return FetchedPage(url=url, html=html, content_type=page.content_type)


class _OneFailureFetcher(_FakeFetcher):
    def __init__(self, failed_url: str):
        self._failed_url = failed_url

    def fetch(self, url: str) -> FetchedPage:
        if url == self._failed_url:
            raise SourceFetchError(
                "Source returned HTTP 403 for https://example.com/?token=fixture-secret",
                category=SourceFetchFailureCategory.HTTP_STATUS,
                status_code=403,
            )
        return super().fetch(url)


class _FakeTagger:
    def classify(self, hit: SearchHit) -> HailoTag:
        return HailoTag(relevance="not_relevant")

    def stop(self) -> None:
        return None


class _FixtureWriter:
    def write(
        self,
        brief_date: date,
        sources: list[EvidenceSource],
        coverage_complete: bool,
        baseline: bool,
    ) -> DraftBrief:
        if baseline:
            source = next(source for source in sources if source.lane == Lane.X402_ACP)
            return DraftBrief(
                claims=[
                    DraftClaim(
                        text="A source page contains the recorded update.",
                        source_ids=[source.source_id],
                        uncertainty="The fixture does not assess real-world materiality.",
                        why_it_matters="It exercises citation validation only.",
                    )
                ],
            )
        return DraftBrief(no_material_change=True)


class _InvalidDraftWriter:
    def write(
        self,
        brief_date: date,
        sources: list[EvidenceSource],
        coverage_complete: bool,
        baseline: bool,
    ) -> DraftBrief:
        return DraftBrief(
            claims=[
                DraftClaim(
                    text="A synthetic claim has an unknown citation.",
                    source_ids=["unknown-source"],
                    uncertainty="This is a fixture-only policy test.",
                    why_it_matters="It verifies useful rejection reporting.",
                )
            ]
        )


class _RecordingWriter:
    def __init__(self):
        self.received_sources: list[EvidenceSource] = []

    def write(
        self,
        brief_date: date,
        sources: list[EvidenceSource],
        coverage_complete: bool,
        baseline: bool,
    ) -> DraftBrief:
        self.received_sources = sources
        source = next(source for source in sources if source.lane == Lane.X402_ACP)
        return DraftBrief(
            claims=[
                DraftClaim(
                    text="A safe source records a verified protocol update.",
                    source_ids=[source.source_id],
                    uncertainty="The fixture cannot assess its real-world impact.",
                    why_it_matters="It verifies source filtering in the pipeline.",
                )
            ]
        )


class PipelineTests(unittest.TestCase):
    def test_daily_pipeline_rejects_backdated_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory))
            store = Store(settings.database_path)
            pipeline = DailyPipeline(
                settings,
                store,
                _FakeSearch(),
                _FakeFetcher(),
                _FixtureWriter(),
            )
            with self.assertRaises(PipelineError):
                pipeline.run(date.fromordinal(date.today().toordinal() - 1))
            store.close()

    def test_full_coverage_builds_local_outbox_and_hailo_cannot_drop_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory))
            store = Store(settings.database_path)
            pipeline = DailyPipeline(
                settings,
                store,
                _FakeSearch(),
                _FakeFetcher(),
                _FixtureWriter(),
                tagger=_FakeTagger(),
            )
            target_date = date.today()
            first = pipeline.run(target_date)
            self.assertTrue(first.coverage_complete)
            self.assertEqual(first.source_count, _TOTAL_SEARCH_QUERY_COUNT)
            first_text = first.brief_path.read_text(encoding="utf-8")
            self.assertIn("Baseline run", first_text)
            self.assertIn("not published", first_text)

            second = pipeline.run(target_date)
            self.assertTrue(second.coverage_complete)
            self.assertEqual(second.source_count, _TOTAL_SEARCH_QUERY_COUNT)
            second_text = second.brief_path.read_text(encoding="utf-8")
            self.assertIn("no material change", second_text.lower())
            self.assertIn("unchanged", second_text)
            store.close()

    def test_hailo_startup_failure_is_reported_while_cpu_path_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory))
            store = Store(settings.database_path)
            diagnostic = "runtime_import:ModuleNotFoundError: hailo_platform"
            pipeline = DailyPipeline(
                settings,
                store,
                _FakeSearch(),
                _FakeFetcher(),
                _FixtureWriter(),
                tagger_error=HailoWorkerError(
                    "Hailo worker failed",
                    diagnostic=diagnostic,
                ),
            )
            try:
                report = pipeline.run(date.today())
                brief = report.brief_path.read_text(encoding="utf-8")
                self.assertTrue(report.coverage_complete)
                self.assertEqual(report.source_count, _TOTAL_SEARCH_QUERY_COUNT)
                self.assertIn(f"hailo:{diagnostic}", report.warnings)
                self.assertIn(
                    f"unavailable; CPU path continued ({diagnostic})",
                    brief,
                )
            finally:
                store.close()

    def test_hailo_inference_failure_is_reported_while_cpu_path_continues(self):
        class FailingTagger(_FakeTagger):
            def classify(self, hit: SearchHit) -> HailoTag:
                raise HailoWorkerError(
                    "Hailo inference failed",
                    diagnostic="inference:HailoRTException: error_code_42",
                )

        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory))
            store = Store(settings.database_path)
            pipeline = DailyPipeline(
                settings,
                store,
                _FakeSearch(),
                _FakeFetcher(),
                _FixtureWriter(),
                tagger=FailingTagger(),
            )
            try:
                report = pipeline.run(date.today())
                brief = report.brief_path.read_text(encoding="utf-8")
                diagnostic = "inference:HailoRTException: error_code_42"
                self.assertTrue(report.coverage_complete)
                self.assertEqual(report.source_count, _TOTAL_SEARCH_QUERY_COUNT)
                self.assertIn(f"hailo:{diagnostic}", report.warnings)
                self.assertIn(
                    f"unavailable; CPU path continued ({diagnostic})",
                    brief,
                )
            finally:
                store.close()

    def test_policy_rejection_reports_the_safe_policy_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory))
            store = Store(settings.database_path)
            genius_query = LANE_QUERIES[Lane.GENIUS_ACT][0]
            failed_url = (
                "https://example.com/"
                f"{hashlib.sha256(genius_query.encode()).hexdigest()[:12]}"
            )
            pipeline = DailyPipeline(
                settings,
                store,
                _FakeSearch(),
                _OneFailureFetcher(failed_url),
                _InvalidDraftWriter(),
            )
            try:
                with self.assertRaises(PipelineError) as raised:
                    pipeline.run(date.today())
                error_text = str(raised.exception)
                self.assertIn(
                    "PolicyError: A claim cites an unknown source ID",
                    error_text,
                )
                self.assertIn(
                    "source:genius-act-implementation:http_status_403",
                    error_text,
                )
                self.assertNotIn("example.com", error_text)
                self.assertNotIn("fixture-secret", error_text)
            finally:
                store.close()

    def test_neutral_genius_sources_are_available_for_claim_synthesis(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory))
            store = Store(settings.database_path)
            writer = _RecordingWriter()
            pipeline = DailyPipeline(
                settings,
                store,
                _FakeSearch(),
                _DistinctFakeFetcher(),
                writer,
            )
            try:
                report = pipeline.run(date.today())
                self.assertTrue(report.coverage_complete)
                self.assertEqual(report.source_count, _TOTAL_SEARCH_QUERY_COUNT)
                self.assertIn(
                    Lane.GENIUS_ACT,
                    {source.lane for source in writer.received_sources},
                )
                brief = report.brief_path.read_text(encoding="utf-8")
                self.assertNotIn("held for Hans's review", brief)
            finally:
                store.close()

    def test_source_failure_reports_only_sanitized_category(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory))
            store = Store(settings.database_path)
            genius_query = LANE_QUERIES[Lane.GENIUS_ACT][0]
            failed_url = (
                "https://example.com/"
                f"{hashlib.sha256(genius_query.encode()).hexdigest()[:12]}"
            )
            pipeline = DailyPipeline(
                settings,
                store,
                _FakeSearch(),
                _OneFailureFetcher(failed_url),
                _FixtureWriter(),
            )
            try:
                report = pipeline.run(date.today())
                self.assertFalse(report.coverage_complete)
                self.assertIn(
                    "source:genius-act-implementation:http_status_403",
                    report.warnings,
                )
                warning_text = " ".join(report.warnings)
                self.assertNotIn("example.com", warning_text)
                self.assertNotIn("fixture-secret", warning_text)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
