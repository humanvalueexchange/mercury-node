"""Offline contract tests for the local x402 Watch pipeline."""

from __future__ import annotations

import hashlib
import json
import socket
import tempfile
import unittest
from argparse import Namespace
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from x402_watch.brave import BraveSearchClient
from x402_watch.cli import _check_models
from x402_watch.config import ConfigurationError, Settings
from x402_watch.db import Store
from x402_watch.hailo import HailoWorker, HailoWorkerError
from x402_watch.hailo_worker import _parse_tag
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
from x402_watch.sources import FetchedPage, PublicPageFetcher, SourceFetchError
from x402_watch.urls import UnsafeUrlError, canonicalize_url, validate_public_url


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


class SourceFetcherTests(unittest.TestCase):
    def test_redirect_to_private_address_is_rejected_before_second_request(self):
        requests = []
        resolved_hosts = []

        def handler(request):
            requests.append(request)
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/private"},
            )

        def resolver(host, port, type):
            resolved_hosts.append(host)
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

        client = httpx.Client(transport=httpx.MockTransport(handler))
        fetcher = PublicPageFetcher(client=client, resolver=resolver)
        try:
            with self.assertRaises(SourceFetchError):
                fetcher.fetch("https://example.com/")
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].url.host, "93.184.216.34")
            self.assertEqual(requests[0].headers["host"], "example.com")
            self.assertEqual(
                requests[0].extensions["sni_hostname"],
                b"example.com",
            )
            self.assertEqual(resolved_hosts, ["example.com", "127.0.0.1"])
        finally:
            client.close()

    def test_extreme_content_length_is_rejected_without_integer_overflow(self):
        def handler(request):
            return httpx.Response(
                200,
                headers={
                    "content-type": "text/html",
                    "content-length": "9" * 5000,
                },
            )

        def public_resolver(host, port, type):
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("93.184.216.34", port),
                )
            ]

        client = httpx.Client(transport=httpx.MockTransport(handler))
        fetcher = PublicPageFetcher(client=client, resolver=public_resolver)
        try:
            with self.assertRaises(SourceFetchError):
                fetcher.fetch("https://example.com/")
        finally:
            client.close()

    def test_compressed_source_response_is_rejected(self):
        def handler(request):
            return httpx.Response(
                200,
                headers={
                    "content-type": "text/html",
                    "content-encoding": "gzip",
                },
                content=b"not decompressed",
            )

        def public_resolver(host, port, type):
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("93.184.216.34", port),
                )
            ]

        client = httpx.Client(transport=httpx.MockTransport(handler))
        fetcher = PublicPageFetcher(client=client, resolver=public_resolver)
        try:
            with self.assertRaises(SourceFetchError):
                fetcher.fetch("https://example.com/")
        finally:
            client.close()


class HailoWorkerTests(unittest.TestCase):
    def test_parse_tag_removes_hailo_chat_end_token(self):
        self.assertEqual(
            _parse_tag("not_relevant.<|im_end|>"),
            {"relevance": "not_relevant"},
        )
        with self.assertRaises(ValueError):
            _parse_tag("unrecognized<|im_end|>")

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
        self.assertIn("no summary field", captured["messages"][0]["content"])

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
                        Namespace(skip_hailo=True),
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

    def test_genius_act_source_is_automatically_held(self):
        source = make_source(Lane.GENIUS_ACT)
        draft = route_sensitive_sources(
            DraftBrief(),
            [source],
        )
        self.assertEqual(len(draft.held_items), 1)
        self.assertIn(source.source_id, draft.held_items[0].source_ids)
        validate_draft(draft, [source], coverage_complete=True)

    def test_sensitive_routing_respects_held_source_limit(self):
        sources = [
            make_source(url=f"https://example.com/{index}")
            for index in range(20)
        ]
        sensitive = make_source(
            Lane.GENIUS_ACT,
            url="https://example.com/financial",
        )
        draft = DraftBrief(
            held_items=[
                HeldItem(
                    title="Financial, legal, or tax items held for review",
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
            self.assertEqual(first.source_count, len(LANE_QUERIES))
            first_text = first.brief_path.read_text(encoding="utf-8")
            self.assertIn("Baseline run", first_text)
            self.assertIn("not published", first_text)

            second = pipeline.run(target_date)
            self.assertTrue(second.coverage_complete)
            self.assertEqual(second.source_count, len(LANE_QUERIES))
            second_text = second.brief_path.read_text(encoding="utf-8")
            self.assertIn("no material change", second_text.lower())
            self.assertIn("unchanged", second_text)
            store.close()


if __name__ == "__main__":
    unittest.main()
