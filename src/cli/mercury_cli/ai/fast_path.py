"""Closed, snapshot-only replies for narrowly defined status questions."""

from __future__ import annotations

import re
from typing import Any


_ZERO_CHANNELS = {
    "what channels do i have",
    "what channels are active",
    "how many channels do i have",
    "how many active channels do i have",
}
_SYNC_STATUS = {
    "is the node ready",
    "is my node ready",
    "is the node synced",
    "is my node synced",
    "what is the sync status",
    "what is the node status",
    "what is current node status",
}
_LIQUIDITY = {
    "what is my inbound and outbound liquidity",
    "what are my inbound and outbound percentages",
    "show inbound and outbound liquidity",
}


def deterministic_reply(question: str, snapshot: dict[str, Any]) -> str | None:
    """Return a bounded fact-only reply, or None for DualEngine fallback."""
    normalized = _normalize(question)
    if snapshot.get("fresh") is not True:
        return None
    if normalized in _ZERO_CHANNELS:
        return _zero_channels(snapshot)
    if normalized in _SYNC_STATUS:
        return _sync_status(snapshot)
    if normalized in _LIQUIDITY:
        return _liquidity(snapshot)
    return None


def _zero_channels(snapshot: dict[str, Any]) -> str | None:
    totals = snapshot.get("totals")
    if not isinstance(totals, dict) or totals.get("active") != 0:
        return None
    return (
        "No active channels; cannot rebalance; opening is a human "
        "`mercury` channel command."
    )


def _sync_status(snapshot: dict[str, Any]) -> str | None:
    chain = snapshot.get("chain")
    wallet = snapshot.get("wallet")
    if not isinstance(chain, dict) or not isinstance(wallet, dict):
        return None
    required = ("height", "synced")
    wallet_required = ("confirmed_sat", "unconfirmed_sat")
    if any(key not in chain for key in required) or any(
        key not in wallet for key in wallet_required
    ):
        return None
    if type(chain["height"]) is not int or type(chain["synced"]) is not bool:
        return None
    if not all(type(wallet[key]) is int for key in wallet_required):
        return None
    state = "synced" if chain["synced"] else "not synced"
    return (
        f"Node is {state} at height {chain['height']}. "
        f"Wallet totals are {wallet['confirmed_sat']} confirmed sat and "
        f"{wallet['unconfirmed_sat']} unconfirmed sat."
    )


def _liquidity(snapshot: dict[str, Any]) -> str | None:
    totals = snapshot.get("totals")
    if not isinstance(totals, dict) or totals.get("active", 0) < 1:
        return None
    fields = ("local_sat", "remote_sat", "inbound_pct", "outbound_pct")
    if not all(type(totals.get(field)) in (int, float) for field in fields):
        return None
    return (
        f"Local liquidity is {totals['local_sat']} sat "
        f"({totals['outbound_pct']}% outbound); remote liquidity is "
        f"{totals['remote_sat']} sat ({totals['inbound_pct']}% inbound)."
    )


def _normalize(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower().rstrip("?!."))
