"""Deterministic Markdown rendering for private daily briefs."""

from __future__ import annotations

from datetime import date
from urllib.parse import quote

from .models import DraftBrief, EvidenceSource

_MARKDOWN_SPECIAL = "\\`*_{}[]()!#<>|"


def _plain_text(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    for character in _MARKDOWN_SPECIAL[1:]:
        escaped = escaped.replace(character, f"\\{character}")
    return " ".join(escaped.split())


def _table_cell(value: str) -> str:
    return _plain_text(value)


def render_brief(
    brief_date: date,
    run_id: str,
    draft: DraftBrief,
    sources: list[EvidenceSource],
    coverage_complete: bool,
    lane_status: dict[str, str],
    *,
    baseline: bool = False,
    dry_run: bool = True,
) -> str:
    if baseline:
        summary = (
            "Initial baseline: no prior complete local run is available; "
            "this brief establishes the comparison set."
        )
    elif not coverage_complete:
        summary = (
            "Coverage is incomplete; no conclusion about material change is available."
        )
    elif draft.no_material_change:
        summary = (
            "No material change was identified in reviewed evidence; "
            "held items remain unevaluated by design."
        )
    else:
        summary = "Verified developments and items held for review are listed below."

    if baseline:
        result = "baseline"
    elif not coverage_complete:
        result = "incomplete coverage"
    elif draft.no_material_change:
        result = "no material change"
    else:
        result = "material items found"

    lines = [f"# x402 Watch — {brief_date.isoformat()}", ""]
    if dry_run:
        lines.extend(["**UAT dry run — not published.**", ""])
    if not coverage_complete:
        lines.extend(
            [
                "**Coverage incomplete:** do not interpret this brief as evidence of no material change.",
                "",
            ]
        )
    if baseline:
        lines.extend(
            [
                "**Baseline run:** no prior completed local brief is available for comparison.",
                "",
            ]
        )
    lines.extend(
        [
            f"- Run: `{run_id}`",
            f"- Coverage: {'complete' if coverage_complete else 'incomplete'}",
            f"- Result: {result}",
            "",
            "## Summary",
            "",
            _plain_text(summary),
            "",
        ]
    )

    if draft.claims:
        lines.extend(["## Material changes", ""])
        for index, claim in enumerate(draft.claims, start=1):
            citations = ", ".join(f"[{source_id}]" for source_id in claim.source_ids)
            lines.extend(
                [
                    f"{index}. {_plain_text(claim.text)} {citations}",
                    f"   - **Why it matters:** {_plain_text(claim.why_it_matters)}",
                    f"   - **Uncertainty:** {_plain_text(claim.uncertainty)}",
                ]
            )
        lines.append("")

    if draft.held_items:
        lines.extend(["## Held for human review", ""])
        for item in draft.held_items:
            citations = ", ".join(f"[{source_id}]" for source_id in item.source_ids)
            lines.append(
                f"- **{_plain_text(item.title)}** {citations} — "
                f"{_plain_text(item.reason)}"
            )
        lines.append("")

    lines.extend(["## Search coverage", ""])
    for lane, status in sorted(lane_status.items()):
        lines.append(f"- `{lane}`: {status}")
    lines.extend(["", "## Sources", ""])
    lines.extend(
        [
            "| ID | Publisher | Published | Retrieved (UTC) | History | Source |",
            "|---|---|---|---|---|---|",
        ]
    )
    for source in sources:
        published = source.published_at or "not stated"
        title = _table_cell(source.title)
        publisher = _table_cell(source.publisher)
        published = _table_cell(published)
        url = quote(source.url, safe=":/?&=%#@!$'()*+,;[]")
        lines.append(
            f"| {source.source_id} | {publisher} | {published} | "
            f"{source.retrieved_at} | {source.history_status} | "
            f"[{title}](<{url}>) |"
        )
    lines.extend(
        [
            "",
            "Education/opinion only; no investment advice. Protocols are monitored topics, not commitments.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = ["render_brief"]
