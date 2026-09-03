"""Bounded, secret-free node snapshots for local model prompts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen


class SnapshotBuilder:
    def __init__(
        self,
        config: Any,
        *,
        agent_get: Callable[[str], dict[str, Any]] | None = None,
        lncli_runner: Callable[..., tuple[dict[str, Any] | None, str | None]] | None = None,
    ) -> None:
        self.config = config
        self.agent_get = agent_get or self._agent_get
        self.lncli_runner = lncli_runner

    def build(self) -> dict[str, Any]:
        status = self._safe_agent("/api/status")
        channels_payload = self._safe_agent("/api/channels")
        if not status and self.lncli_runner:
            status = self._lncli_status()
        if not channels_payload and self.lncli_runner:
            channels_payload = self._lncli("listchannels")

        snapshot = self._shape(status, channels_payload)
        snapshot["ts"] = datetime.now(timezone.utc).isoformat()
        snapshot["fresh"] = bool(status or channels_payload)
        if not snapshot["channels"]:
            snapshot["notes"].append("zero_channels")
        return self._bounded(snapshot)

    def _safe_agent(self, path: str) -> dict[str, Any]:
        try:
            value = self.agent_get(path)
            return value if isinstance(value, dict) else {}
        except (OSError, URLError, RuntimeError, ValueError, TypeError):
            return {}

    def _agent_get(self, path: str) -> dict[str, Any]:
        request = Request(f"{self.config.agent_url.rstrip('/')}{path}")
        with urlopen(request, timeout=1.5) as response:
            value = json.loads(response.read())
        return value if isinstance(value, dict) else {}

    def _lncli(self, *args: str) -> dict[str, Any]:
        value, _ = self.lncli_runner(*args, timeout=1.5)
        return value if isinstance(value, dict) else {}

    def _lncli_status(self) -> dict[str, Any]:
        info = self._lncli("getinfo")
        wallet = self._lncli("walletbalance")
        return {
            "node": info,
            "wallet": {
                "confirmed_sat": self._int(wallet.get("confirmed_balance")),
                "unconfirmed_sat": self._int(wallet.get("unconfirmed_balance")),
            },
        }

    def _shape(
        self, status: dict[str, Any], channels_payload: dict[str, Any]
    ) -> dict[str, Any]:
        node = status.get("node") or status
        wallet = status.get("wallet") or {}
        raw_channels = channels_payload.get("active")
        if raw_channels is None:
            raw_channels = channels_payload.get("channels") or []
        channels = [self._channel(channel) for channel in raw_channels if isinstance(channel, dict)]
        total_local = sum(channel["local_sat"] for channel in channels)
        total_remote = sum(channel["remote_sat"] for channel in channels)
        total_capacity = total_local + total_remote
        active = sum(1 for channel in channels if channel["active"])
        return {
            "chain": {
                "height": self._int(node.get("block_height") or node.get("blockheight")),
                "synced": bool(node.get("synced_to_chain", node.get("synced", False))),
            },
            "wallet": {
                "confirmed_sat": self._int(wallet.get("confirmed_sat", wallet.get("confirmed_balance"))),
                "unconfirmed_sat": self._int(wallet.get("unconfirmed_sat", wallet.get("unconfirmed_balance"))),
            },
            "channels": channels,
            "totals": {
                "active": active,
                "local_sat": total_local,
                "remote_sat": total_remote,
                "inbound_pct": round(total_remote / total_capacity * 100, 1) if total_capacity else 0,
                "outbound_pct": round(total_local / total_capacity * 100, 1) if total_capacity else 0,
            },
            "notes": [],
        }

    def _channel(self, channel: dict[str, Any]) -> dict[str, Any]:
        local = self._int(channel.get("local_sat", channel.get("local_balance")))
        remote = self._int(channel.get("remote_sat", channel.get("remote_balance")))
        capacity = self._int(channel.get("capacity_sat", channel.get("capacity"))) or local + remote
        return {
            "alias": str(channel.get("alias") or channel.get("peer_alias") or "unknown")[:80],
            "chan_id": str(channel.get("chan_id") or "")[:80],
            "capacity_sat": capacity,
            "local_sat": local,
            "remote_sat": remote,
            "local_pct": round(local / capacity * 100, 1) if capacity else 0,
            "active": bool(channel.get("active", False)),
            "initiator": bool(channel.get("initiator", False)),
        }

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _bounded(snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot["notes"].append("channels_truncated")
        encoded = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=True)
        if len(encoded) <= 4096:
            snapshot["notes"].pop()
            return snapshot
        channels = snapshot["channels"]
        while channels and len(json.dumps(snapshot, separators=(",", ":"), ensure_ascii=True)) > 4096:
            channels.pop()
        return snapshot


def prompt_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Project the validated snapshot into a compact, model-facing shape."""
    channels = snapshot.get("channels")
    compact_channels = []
    if isinstance(channels, list):
        for channel in channels:
            if not isinstance(channel, dict):
                continue
            compact_channels.append(
                {
                    "alias": channel.get("alias"),
                    "chan_id": channel.get("chan_id"),
                    "capacity_sat": channel.get("capacity_sat"),
                    "local_sat": channel.get("local_sat"),
                    "remote_sat": channel.get("remote_sat"),
                    "local_pct": channel.get("local_pct"),
                    "active": channel.get("active"),
                }
            )
    chain = snapshot.get("chain")
    wallet = snapshot.get("wallet")
    totals = snapshot.get("totals")
    return {
        "chain": {
            key: chain[key]
            for key in ("height", "synced")
            if isinstance(chain, dict) and key in chain
        },
        "wallet": {
            key: wallet[key]
            for key in ("confirmed_sat", "unconfirmed_sat")
            if isinstance(wallet, dict) and key in wallet
        },
        "channels": compact_channels,
        "totals": {
            key: totals[key]
            for key in (
                "active",
                "local_sat",
                "remote_sat",
                "inbound_pct",
                "outbound_pct",
            )
            if isinstance(totals, dict) and key in totals
        },
        "notes": [
            note for note in snapshot.get("notes", []) if isinstance(note, str)
        ],
        "fresh": snapshot.get("fresh", False),
    }
