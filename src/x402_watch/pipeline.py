"""Daily research orchestration, validation, local outbox, and gated publishing."""

from __future__ import annotations

import fcntl
import os
import tempfile
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol, Self

from .brave import SearchError
from .config import Settings
from .db import Store
from .hailo import HailoWorkerError
from .models import (
    LANE_QUERIES,
    DraftBrief,
    EvidenceSource,
    Lane,
    SearchHit,
)
from .policy import (
    PolicyError,
    route_sensitive_sources,
    source_requires_human_routing,
    validate_draft,
)
from .render import render_brief
from .sources import (
    FetchedPage,
    SourceExtractionError,
    SourceFetchError,
    extract_source,
)
from .urls import UnsafeUrlError, canonicalize_url


class SearchClient(Protocol):
    def search(self, query: str, count: int = 5) -> list[SearchHit]: ...


class PageFetcher(Protocol):
    def fetch(self, url: str) -> FetchedPage: ...


class DraftWriter(Protocol):
    def write(
        self,
        brief_date: date,
        sources: list[EvidenceSource],
        coverage_complete: bool,
        baseline: bool,
    ) -> DraftBrief: ...


class Tagger(Protocol):
    def classify(self, hit: SearchHit): ...

    def stop(self) -> None: ...


class Publisher(Protocol):
    def publish(self, brief_date: date, markdown: str) -> str: ...


class PipelineError(RuntimeError):
    """Raised when a daily run cannot create a valid private brief."""


@dataclass(frozen=True)
class RunReport:
    run_id: str
    brief_date: date
    coverage_complete: bool
    brief_path: Path
    source_count: int
    published_commit: str | None
    warnings: tuple[str, ...]


_LANE_PRIORITY = {lane: index for index, lane in enumerate(LANE_QUERIES)}


class _RunLock:
    def __init__(self, path: Path):
        self._path = path
        self._descriptor: int | None = None

    def __enter__(self) -> Self:
        self._path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self._descriptor = os.open(
            self._path,
            os.O_CREAT | os.O_RDWR | os.O_CLOEXEC,
            0o600,
        )
        os.chmod(self._path, 0o600)
        try:
            fcntl.flock(self._descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self._descriptor)
            self._descriptor = None
            raise PipelineError("Another x402 Watch run is already active") from exc
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        if descriptor is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


class DailyPipeline:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        search: SearchClient,
        fetcher: PageFetcher,
        writer: DraftWriter,
        *,
        tagger: Tagger | None = None,
        publisher: Publisher | None = None,
        fetch_workers: int = 3,
    ):
        if not 1 <= fetch_workers <= 4:
            raise ValueError("Fetch worker count must be between 1 and 4")
        self._settings = settings
        self._store = store
        self._search = search
        self._fetcher = fetcher
        self._writer = writer
        self._tagger = tagger
        self._publisher = publisher
        self._fetch_workers = fetch_workers

    def run(
        self,
        brief_date: date | None = None,
        *,
        publish: bool = False,
        dry_run: bool = True,
    ) -> RunReport:
        with _RunLock(self._settings.data_dir / "daily.lock"):
            return self._run_locked(
                brief_date,
                publish=publish,
                dry_run=dry_run,
            )

    def _run_locked(
        self,
        brief_date: date | None = None,
        *,
        publish: bool = False,
        dry_run: bool = True,
    ) -> RunReport:
        today = date.today()
        target_date = brief_date or today
        if target_date != today:
            raise PipelineError("Daily runs may only create the current local date")
        if publish and (dry_run or not self._settings.publish_enabled):
            raise PipelineError(
                "Publishing requires a non-dry run and explicit publisher enablement"
            )
        if publish and self._publisher is None:
            raise PipelineError("No scoped GitHub publisher is configured")

        run_id = uuid.uuid4().hex
        started_at = datetime.now(UTC)
        self._store.start_run(run_id, target_date.isoformat(), _iso(started_at))
        baseline = not self._store.has_prior_complete_run(
            run_id,
            target_date.isoformat(),
        )
        errors: list[str] = []
        lane_status = {lane.value: "pending" for lane in Lane}
        candidates: list[tuple[Lane, SearchHit]] = []
        query_success = {lane: True for lane in Lane}

        for lane, queries in LANE_QUERIES.items():
            lane_hits = 0
            for query in queries:
                query_time = _iso(datetime.now(UTC))
                try:
                    hits = self._search.search(
                        query,
                        count=self._settings.max_search_results,
                    )
                except SearchError as exc:
                    query_success[lane] = False
                    errors.append(f"search:{lane.value}:{type(exc).__name__}")
                    self._store.record_query(
                        run_id,
                        lane.value,
                        query,
                        "error",
                        0,
                        query_time,
                        type(exc).__name__,
                    )
                    continue
                self._store.record_query(
                    run_id,
                    lane.value,
                    query,
                    "ok",
                    len(hits),
                    query_time,
                )
                lane_hits += len(hits)
                candidates.extend((lane, hit) for hit in hits)
            lane_status[lane.value] = (
                f"searched; {lane_hits} results"
                if query_success[lane]
                else f"incomplete; {lane_hits} results"
            )

        deduplicated: list[tuple[Lane, SearchHit]] = []
        seen_urls: set[str] = set()
        source_failures: set[Lane] = set()
        for lane, hit in candidates:
            try:
                canonical = canonicalize_url(hit.url)
            except UnsafeUrlError:
                source_failures.add(lane)
                errors.append(f"candidate:{lane.value}:unsafe_url")
                continue
            if canonical in seen_urls:
                continue
            seen_urls.add(canonical)
            deduplicated.append((lane, hit))

        sources: list[EvidenceSource] = []
        tagger_failed = False
        fetch_futures: dict[Future, tuple[Lane, SearchHit]] = {}
        with ThreadPoolExecutor(max_workers=self._fetch_workers) as executor:
            for lane, hit in deduplicated:
                fetch_futures[
                    executor.submit(self._fetch_and_extract, lane, hit)
                ] = (lane, hit)

            for future in as_completed(fetch_futures):
                lane, hit = fetch_futures[future]
                hailo_relevance: str | None = None
                if self._tagger is not None and not tagger_failed:
                    try:
                        hailo_relevance = self._tagger.classify(hit).relevance
                    except HailoWorkerError as exc:
                        tagger_failed = True
                        errors.append(f"hailo:{type(exc).__name__}")
                try:
                    source = future.result()
                except (SourceFetchError, SourceExtractionError) as exc:
                    source_failures.add(lane)
                    failure_code = (
                        exc.diagnostic_code
                        if isinstance(exc, SourceFetchError)
                        else "source_extraction_failed"
                    )
                    errors.append(f"source:{lane.value}:{failure_code}")
                    continue
                if hailo_relevance is not None:
                    source = source.model_copy(
                        update={"hailo_relevance": hailo_relevance}
                    )
                previous_hash = self._store.prior_source_hash(
                    run_id,
                    target_date.isoformat(),
                    source.canonical_url,
                )
                history_status = (
                    "new"
                    if previous_hash is None
                    else (
                        "unchanged"
                        if previous_hash == source.content_hash
                        else "changed"
                    )
                )
                source = source.model_copy(update={"history_status": history_status})
                self._store.save_source(run_id, source)
                sources.append(source)

        if self._tagger is not None:
            self._tagger.stop()

        coverage_complete = all(query_success.values()) and not source_failures
        sources.sort(key=_source_priority)
        evidence_sources = _deduplicate_evidence(sources)
        claimable_sources = [
            source
            for source in evidence_sources
            if not source_requires_human_routing(source)
        ]
        if self._tagger is None:
            lane_status["hailo-triage"] = "not configured; CPU path only"
        elif tagger_failed:
            lane_status["hailo-triage"] = "unavailable; CPU path continued"
        else:
            lane_status["hailo-triage"] = "completed; advisory tags only"
        for lane in source_failures:
            lane_status[lane.value] = "incomplete; one or more sources unavailable"

        try:
            draft = self._writer.write(
                target_date,
                claimable_sources,
                coverage_complete,
                baseline,
            )
            draft = route_sensitive_sources(draft, sources)
            validate_draft(
                draft,
                sources,
                coverage_complete,
                baseline,
                claim_source_ids={
                    source.source_id for source in claimable_sources
                },
            )
        except (PolicyError, ValueError) as exc:
            failure_detail = (
                f"{type(exc).__name__}: {exc}"
                if isinstance(exc, PolicyError)
                else type(exc).__name__
            )
            self._store.finish_run(
                run_id,
                _iso(datetime.now(UTC)),
                "rejected",
                coverage_complete,
                errors + [f"draft:{failure_detail}"],
            )
            run_context = f"run {run_id}"
            if errors:
                run_context += f"; diagnostics: {', '.join(errors)}"
            raise PipelineError(
                f"Generated brief failed editorial validation: {failure_detail} "
                f"({run_context})"
            ) from exc
        except Exception:
            self._store.finish_run(
                run_id,
                _iso(datetime.now(UTC)),
                "failed",
                coverage_complete,
                errors + ["draft:writer_failure"],
            )
            raise

        markdown = render_brief(
            target_date,
            run_id,
            draft,
            sources,
            coverage_complete,
            lane_status,
            baseline=baseline,
            dry_run=dry_run,
        )
        brief_path = self._write_outbox(target_date, markdown)
        self._store.save_brief(
            run_id,
            target_date.isoformat(),
            markdown,
            "passed",
            _iso(datetime.now(UTC)),
            publish_requested=publish,
        )
        published_commit: str | None = None
        if publish:
            if self._publisher is None:
                raise PipelineError("No scoped GitHub publisher is configured")
            try:
                published_commit = self._publisher.publish(target_date, markdown)
            except Exception as exc:
                self._store.update_publish_status(
                    run_id,
                    "failed",
                    error=type(exc).__name__,
                    outbox_status="pending",
                )
                self._store.finish_run(
                    run_id,
                    _iso(datetime.now(UTC)),
                    "publish_failed",
                    coverage_complete,
                    errors + ["publisher:write_failed"],
                )
                raise
            self._store.update_publish_status(run_id, "published", published_commit)

        final_status = "complete" if coverage_complete else "incomplete"
        self._store.finish_run(
            run_id,
            _iso(datetime.now(UTC)),
            final_status,
            coverage_complete,
            errors,
        )
        return RunReport(
            run_id=run_id,
            brief_date=target_date,
            coverage_complete=coverage_complete,
            brief_path=brief_path,
            source_count=len(sources),
            published_commit=published_commit,
            warnings=tuple(errors),
        )

    def _fetch_and_extract(self, lane: Lane, hit: SearchHit) -> EvidenceSource:
        page = self._fetcher.fetch(hit.url)
        return extract_source(lane, hit, page)

    def _write_outbox(self, brief_date: date, content: str) -> Path:
        directory = self._settings.outbox_dir / "briefs"
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        target = directory / f"{brief_date.isoformat()}.md"
        previous_umask = os.umask(0o077)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=directory,
                prefix=f".{brief_date.isoformat()}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, target)
            os.chmod(target, 0o600)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise PipelineError("Could not write the local private outbox") from exc
        finally:
            os.umask(previous_umask)
        return target


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _source_priority(source: EvidenceSource) -> tuple[int, int, int, int]:
    history_priority = {"changed": 0, "new": 1, "unchanged": 2}
    relevance_priority = {
        "relevant": 0,
        "uncertain": 1,
        None: 1,
        "not_relevant": 2,
    }
    return (
        0 if source.primary_source else 1,
        history_priority[source.history_status],
        relevance_priority[source.hailo_relevance],
        _LANE_PRIORITY[source.lane],
    )


def _deduplicate_evidence(sources: list[EvidenceSource]) -> list[EvidenceSource]:
    seen_hashes: set[str] = set()
    unique_sources: list[EvidenceSource] = []
    for source in sources:
        if source.content_hash in seen_hashes:
            continue
        seen_hashes.add(source.content_hash)
        unique_sources.append(source)
    return unique_sources


__all__ = ["DailyPipeline", "PipelineError", "RunReport"]
