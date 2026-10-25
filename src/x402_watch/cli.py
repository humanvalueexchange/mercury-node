"""Command-line entry point for offline checks and the daily local run."""

from __future__ import annotations

import argparse
import re
import sys
import time
from contextlib import ExitStack
from datetime import date

import httpx

from .brave import BraveSearchClient, SearchError
from .config import ConfigurationError, Settings
from .db import Store
from .hailo import HailoWorker, HailoWorkerError
from .llm import LlamaDraftWriter, LocalLlamaServer, LocalModelError
from .pipeline import DailyPipeline, PipelineError
from .publisher import GitHubAppPublisher, GitHubPublishError
from .sources import PublicPageFetcher


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="x402-watch")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run one daily research cycle")
    run_parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=date.today(),
        help="current local brief date in YYYY-MM-DD form (default: local date)",
    )
    run_parser.add_argument(
        "--publish",
        action="store_true",
        help="publish to the configured private repository (requires explicit enablement)",
    )
    run_parser.add_argument(
        "--cpu-only",
        action="store_true",
        help="skip optional Hailo title/snippet triage",
    )
    check_parser = commands.add_parser(
        "check-models",
        help="run bounded local CPU and Hailo inference checks",
    )
    check_parser.add_argument(
        "--skip-hailo",
        action="store_true",
        help="check llama.cpp only",
    )
    retry_parser = commands.add_parser(
        "retry-publish",
        help="retry previously approved, validated outbox writes",
    )
    retry_parser.add_argument(
        "--confirm-publish",
        action="store_true",
        required=True,
        help="confirm that pending validated briefs may be written to GitHub",
    )
    return parser


def _run_daily(args: argparse.Namespace, settings: Settings) -> int:
    if args.date != date.today():
        raise PipelineError("Daily runs may only create the current local date")
    if args.publish:
        settings.validate_publisher()
    with ExitStack() as stack:
        store = stack.enter_context(Store(settings.database_path))
        brave_key = settings.credential("brave_api_key")
        search = stack.enter_context(
            BraveSearchClient(
                brave_key,
                endpoint=settings.brave_endpoint,
            )
        )
        fetcher = stack.enter_context(
            PublicPageFetcher(
                max_bytes=settings.max_source_bytes,
                max_redirects=settings.max_redirects,
                timeout=settings.fetch_timeout_seconds,
            )
        )
        writer = stack.enter_context(LlamaDraftWriter(settings))

        tagger = None
        if not args.cpu_only:
            try:
                tagger = stack.enter_context(HailoWorker(settings))
            except HailoWorkerError as exc:
                print(
                    f"Hailo triage unavailable; continuing with CPU-only synthesis "
                    f"({exc})",
                    file=sys.stderr,
                )

        publisher = None
        if args.publish:
            publisher = stack.enter_context(GitHubAppPublisher(settings))

        pipeline = DailyPipeline(
            settings,
            store,
            search,
            fetcher,
            writer,
            tagger=tagger,
            publisher=publisher,
        )
        report = pipeline.run(
            args.date,
            publish=args.publish,
            dry_run=not args.publish,
        )

    print(
        f"Run {report.run_id}: {report.brief_date} "
        f"({report.source_count} sources; "
        f"coverage {'complete' if report.coverage_complete else 'incomplete'})"
    )
    print(f"Private outbox: {report.brief_path}")
    if report.published_commit:
        print(f"GitHub commit: {report.published_commit}")
    if report.warnings:
        print(f"Warnings: {len(report.warnings)}; see the local run record.", file=sys.stderr)
    return 0 if report.coverage_complete else 2


def _check_models(args: argparse.Namespace, settings: Settings) -> int:
    if not settings.llama_server.is_file():
        raise LocalModelError("llama-server binary is missing")
    if not settings.llama_model.is_file():
        raise LocalModelError("The configured local GGUF model is missing")
    started = time.monotonic()
    with LocalLlamaServer(settings), httpx.Client(
        timeout=settings.model_timeout_seconds,
        trust_env=False,
    ) as client:
        try:
            response = client.post(
                f"{settings.llama_url}/v1/chat/completions",
                json={
                    "model": "local",
                    "temperature": 0,
                    "max_tokens": 8,
                    "chat_template_kwargs": {"enable_thinking": False},
                    "messages": [
                        {
                            "role": "user",
                            "content": 'Reply with the single word "ready".',
                        }
                    ],
                },
            )
        except httpx.HTTPError as exc:
            raise LocalModelError("CPU inference self-check failed") from exc
        if response.status_code != 200:
            raise LocalModelError(
                f"CPU inference self-check returned HTTP {response.status_code}"
            )
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LocalModelError(
                "CPU inference self-check returned an invalid response"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise LocalModelError("CPU inference self-check returned an empty response")
    print(f"llama.cpp CPU inference: passed in {time.monotonic() - started:.1f}s")

    if args.skip_hailo:
        print("Hailo inference: skipped by request")
        return 0
    if not settings.hailo_model.is_file():
        raise HailoWorkerError("The configured Hailo HEF model is missing")
    started = time.monotonic()
    with HailoWorker(settings) as worker:
        from .models import SearchHit

        worker.classify(
            SearchHit(
                title="Example x402 protocol documentation",
                url="https://example.com/",
                snippet="Synthetic local self-check input; not research evidence.",
            )
        )
    print(f"Hailo inference: passed in {time.monotonic() - started:.1f}s")
    return 0


def _retry_publish(settings: Settings) -> int:
    settings.validate_publisher()
    failures = 0
    with ExitStack() as stack:
        store = stack.enter_context(Store(settings.database_path))
        publisher = stack.enter_context(GitHubAppPublisher(settings))
        pending = store.pending_outbox()
        if not pending:
            print("No explicitly approved validated outbox entries are pending.")
            return 0
        for item in pending:
            path = item["path"]
            if not isinstance(path, str) or not re.fullmatch(
                r"briefs/\d{4}-\d{2}-\d{2}\.md",
                path,
            ):
                raise PipelineError("Pending outbox contains an invalid repository path")
            try:
                brief_date = date.fromisoformat(item["brief_date"])
            except (TypeError, ValueError) as exc:
                raise PipelineError("Pending outbox contains an invalid brief date") from exc
            if path != f"briefs/{brief_date.isoformat()}.md":
                raise PipelineError("Pending outbox path does not match its brief date")
            try:
                commit = publisher.publish(brief_date, item["content"])
            except GitHubPublishError as exc:
                store.update_publish_status(
                    item["run_id"],
                    "failed",
                    error=type(exc).__name__,
                    outbox_status="pending",
                )
                print(
                    f"Publish retry failed for {brief_date}: {exc}",
                    file=sys.stderr,
                )
                failures += 1
            else:
                store.update_publish_status(
                    item["run_id"],
                    "published",
                    commit,
                )
                print(f"Published {brief_date} in commit {commit}")
    return 2 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        if args.command == "run":
            return _run_daily(args, settings)
        if args.command == "check-models":
            return _check_models(args, settings)
        if args.command == "retry-publish":
            return _retry_publish(settings)
        parser.error("unknown command")
    except (
        ConfigurationError,
        GitHubPublishError,
        HailoWorkerError,
        LocalModelError,
        PipelineError,
        SearchError,
        OSError,
    ) as exc:
        print(f"x402-watch: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
