"""Typed evidence and draft contracts shared by the local pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Lane(str, Enum):
    X402_ACP = "x402-acp-adoption"
    GENIUS_ACT = "genius-act-implementation"
    STABLECOIN_VOLUME = "stablecoin-vs-card-volume"
    STRIPE_OPENROUTER = "stripe-openrouter-follow-through"


LANE_QUERIES: dict[Lane, tuple[str, ...]] = {
    Lane.X402_ACP: (
        (
            '("x402" OR "Agentic Commerce Protocol") '
            '(adoption OR announcement OR release OR integration) '
            '(site:coinbase.com OR site:docs.cdp.coinbase.com OR '
            'site:x402.org OR site:stripe.com)'
        ),
        'site:www.donvitocodes.com/ai-news ("x402" OR "Agentic Commerce Protocol")',
    ),
    Lane.GENIUS_ACT: (
        (
            '"GENIUS Act" (implementation OR guidance OR rulemaking) '
            '(site:congress.gov OR site:fdic.gov OR site:federalreserve.gov OR '
            'site:occ.gov OR site:sec.gov OR site:treasury.gov)'
        ),
        'site:www.donvitocodes.com/ai-news "GENIUS Act"',
    ),
    Lane.STABLECOIN_VOLUME: (
        (
            "stablecoin transaction volume card network payment volume "
            "(site:federalreserve.gov OR site:mastercard.com OR site:sec.gov OR "
            "site:treasury.gov OR site:visa.com)"
        ),
        "site:www.donvitocodes.com/ai-news stablecoin card network volume",
    ),
    Lane.STRIPE_OPENROUTER: (
        (
            '"Stripe" "OpenRouter" (integration OR partnership OR follow-up OR launch) '
            '(site:openrouter.ai OR site:stripe.com)'
        ),
        "site:www.donvitocodes.com/ai-news Stripe OpenRouter",
    ),
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchHit(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=4096)
    snippet: str = Field(default="", max_length=4000)
    published_hint: str | None = Field(default=None, max_length=128)


class EvidenceSource(StrictModel):
    source_id: str = Field(min_length=8, max_length=64)
    lane: Lane
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=4096)
    canonical_url: str = Field(min_length=1, max_length=4096)
    publisher: str = Field(min_length=1, max_length=300)
    published_at: str | None = Field(default=None, max_length=128)
    retrieved_at: str = Field(min_length=1, max_length=64)
    content_hash: str = Field(min_length=64, max_length=64)
    excerpt: str = Field(min_length=1, max_length=1800)
    primary_source: bool = False
    history_status: Literal["new", "unchanged", "changed"] = "new"
    hailo_relevance: Literal["relevant", "not_relevant", "uncertain"] | None = None


class DraftClaim(StrictModel):
    text: str = Field(min_length=1, max_length=1200)
    source_ids: list[str] = Field(min_length=1, max_length=12)
    uncertainty: str = Field(min_length=1, max_length=500)
    why_it_matters: str = Field(min_length=1, max_length=700)


class HeldItem(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    source_ids: list[str] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=500)


class DraftBrief(StrictModel):
    claims: list[DraftClaim] = Field(default_factory=list, max_length=20)
    held_items: list[HeldItem] = Field(default_factory=list, max_length=20)
    no_material_change: bool = False


class HailoTag(StrictModel):
    relevance: Literal["relevant", "not_relevant", "uncertain"]


__all__ = [
    "LANE_QUERIES",
    "DraftBrief",
    "DraftClaim",
    "EvidenceSource",
    "HailoTag",
    "HeldItem",
    "Lane",
    "SearchHit",
]
