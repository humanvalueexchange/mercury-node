"""Editorial and citation gates for private research briefs."""

from __future__ import annotations

import re

from .models import DraftBrief, EvidenceSource, HeldItem, Lane


class PolicyError(ValueError):
    """Raised when a generated draft violates a hard editorial rule."""


_HELD_TERMS = re.compile(
    r"\b("
    r"legal advice|tax advice|investment advice|financial advice|"
    r"should invest|buy this asset|sell this asset|expected returns|"
    r"tax treatment|legal interpretation|regulatory obligation|"
    r"(?:you|investors?|households?|readers?)\s+"
    r"(?:should|ought to|must)\s+"
    r"(?:buy|sell|invest|allocate|purchase|hold)|"
    r"(?:recommend|urge|advise)\s+"
    r"(?:you|investors?|households?|readers?)\s+to\s+"
    r"(?:buy|sell|invest|allocate|purchase|hold)"
    r")\b",
    re.IGNORECASE,
)
_UNAPPROVED_SCOPE = re.compile(
    r"\b2028\b.{0,60}\bagent[\s-]+mandate\b|"
    r"\bagent[\s-]+mandate\b.{0,60}\b2028\b|"
    r"\b2029\b.{0,60}\blocal[\s-]+first\b|"
    r"\blocal[\s-]+first\b.{0,60}\b2029\b|"
    r"\b2030\b.{0,60}\bposition(?:\s+decision)?\b|"
    r"\bposition(?:\s+decision)?\b.{0,60}\b2030\b|"
    r"\bfinancial\s+participation\b",
    re.IGNORECASE | re.DOTALL,
)
_BLACKROCK_REQUIRED = "analyst estimates, per BlackRock (Sept. 2026)"
_BLACKROCK_DISALLOWED = re.compile(
    r"\b(?:proprietary|exclusive|established fact)\b",
    re.IGNORECASE,
)


def requires_human_routing(text: str) -> bool:
    return bool(_HELD_TERMS.search(text))


def source_requires_human_routing(source: EvidenceSource) -> bool:
    return source.lane == Lane.GENIUS_ACT or requires_human_routing(
        f"{source.title}\n{source.excerpt}"
    )


def route_sensitive_sources(
    draft: DraftBrief,
    sources: list[EvidenceSource],
) -> DraftBrief:
    existing_ids = {
        source_id
        for item in draft.held_items
        for source_id in item.source_ids
    }
    held_items = list(draft.held_items)
    required_ids = {
        source.source_id
        for source in sources
        if source_requires_human_routing(source)
    }
    missing_ids = sorted(required_ids - existing_ids)
    if missing_ids:
        group_title = "Financial, legal, or tax items held for review"
        group_index = next(
            (
                index
                for index, item in enumerate(held_items)
                if item.title == group_title
            ),
            None,
        )
        if group_index is not None:
            grouped_item = held_items[group_index]
            combined_ids = sorted(set(grouped_item.source_ids).union(missing_ids))
            if len(combined_ids) > 20:
                raise PolicyError("Sensitive source routing exceeds the brief limit")
            held_items[group_index] = grouped_item.model_copy(
                update={"source_ids": combined_ids}
            )
        elif len(held_items) < 20:
            held_items.append(
                HeldItem(
                    title=group_title,
                    source_ids=missing_ids,
                    reason=(
                        "Held for hve-cfo/Brian review; no financial, legal, or tax "
                        "interpretation was generated."
                    ),
                )
            )
        else:
            raise PolicyError("Sensitive source could not be routed within the brief limit")
    return draft.model_copy(update={"held_items": held_items})


def validate_draft(
    draft: DraftBrief,
    sources: list[EvidenceSource],
    coverage_complete: bool,
    baseline: bool = False,
    claim_source_ids: set[str] | None = None,
) -> None:
    source_ids = {source.source_id for source in sources}
    if any(_UNAPPROVED_SCOPE.search(source.title) for source in sources):
        raise PolicyError("A source title includes unapproved editorial scope")
    if claim_source_ids is not None and not claim_source_ids.issubset(source_ids):
        raise PolicyError("Claim allowlist contains an unknown source ID")
    allowed_claim_source_ids = (
        source_ids if claim_source_ids is None else claim_source_ids
    )
    routed_source_ids = {
        source.source_id
        for source in sources
        if source_requires_human_routing(source)
    }
    if draft.no_material_change and not coverage_complete:
        raise PolicyError("Incomplete search coverage cannot claim no material change")
    if draft.no_material_change and baseline:
        raise PolicyError("A baseline run cannot claim no material change")
    if draft.no_material_change and draft.claims:
        raise PolicyError("A no-material-change brief must not contain material claims")
    if (
        coverage_complete
        and not baseline
        and not draft.no_material_change
        and not draft.claims
        and not draft.held_items
    ):
        raise PolicyError("A completed run needs material claims or a no-change result")

    for claim in draft.claims:
        if not claim.source_ids:
            raise PolicyError("Every factual claim must cite at least one source")
        if not set(claim.source_ids).issubset(allowed_claim_source_ids):
            raise PolicyError("A claim cites an unknown source ID")
        if set(claim.source_ids).intersection(routed_source_ids):
            raise PolicyError("A claim uses evidence held for human review")
        if _UNAPPROVED_SCOPE.search(
            f"{claim.text}\n{claim.why_it_matters}\n{claim.uncertainty}"
        ):
            raise PolicyError("Claim includes an unapproved future-year proposal")
        if requires_human_routing(
            f"{claim.text}\n{claim.why_it_matters}\n{claim.uncertainty}"
        ):
            raise PolicyError("Claim requires financial, legal, or tax review")
        claim_text = f"{claim.text}\n{claim.why_it_matters}\n{claim.uncertainty}"
        if re.search(r"\bBlackRock\b", claim_text, re.IGNORECASE) and (
            _BLACKROCK_REQUIRED not in claim_text
            or _BLACKROCK_DISALLOWED.search(claim_text)
        ):
            raise PolicyError(
                "BlackRock figures must be labeled as analyst estimates, per BlackRock (Sept. 2026)"
            )

    for held in draft.held_items:
        if not held.source_ids:
            raise PolicyError("Every held item must cite at least one source")
        if not set(held.source_ids).issubset(source_ids):
            raise PolicyError("A held item cites an unknown source ID")
        if _UNAPPROVED_SCOPE.search(f"{held.title}\n{held.reason}"):
            raise PolicyError("Held item includes an unapproved future-year proposal")
    represented_held_ids = {
        source_id for held in draft.held_items for source_id in held.source_ids
    }
    if not routed_source_ids.issubset(represented_held_ids):
        raise PolicyError("Sensitive source was not routed for human review")


__all__ = [
    "PolicyError",
    "requires_human_routing",
    "route_sensitive_sources",
    "source_requires_human_routing",
    "validate_draft",
]
