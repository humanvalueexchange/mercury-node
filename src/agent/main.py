"""
Mercury Agent — v0.3
FastAPI service exposing Mercury node status + Magma liquidity intelligence for the AI agent layer.

Endpoints:
  GET  /api/status            Full node health snapshot
  GET  /api/channels          Active + pending channel data
  GET  /api/invoices          Recent payments
  GET  /api/sync              Bitcoin sync progress
  GET  /api/peers             Connected Lightning peers
  POST /api/backup            Trigger static channel backup
  GET  /api/magma/offers      Live Magma inbound liquidity offers
  GET  /api/magma/node-score  Our node's Amboss health/reputation score
  GET  /api/magma/recommend   AI-powered channel recommendations for our pubkey
  GET  /health                Liveness check (for systemd / load balancer)

This service runs as user 'lnd' so it can read LND macaroons.
Node operations are READ-ONLY — it never signs transactions or moves funds.
Magma read access is anonymous — no API key required to start.
"""

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    import httpx
except ImportError:
    raise SystemExit("FastAPI not installed. Run: pip install fastapi uvicorn httpx")

MAGMA_GRAPHQL = "https://magma.amboss.tech/graphql"
MAGMA_API_KEY = os.getenv("MAGMA_API_KEY", "")  # optional — anonymous access works without it
LND_DIR = "/var/lib/lnd"
LND_USER = "lnd"
BACKUP_DIR = "/var/lib/mercury/backups"
AGENT_VERSION = "0.3.0"

app = FastAPI(
    title="Mercury Agent API",
    description="Read-only Lightning node API for Mercury Agent AI layer",
    version=AGENT_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── LND wrapper ───────────────────────────────────────────────────────────────

def lncli(*args, timeout=15):
    """Run lncli and return parsed JSON or raise HTTPException."""
    cmd = ["sudo", "-u", LND_USER, "lncli", f"--lnddir={LND_DIR}"] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise HTTPException(status_code=503, detail=f"lncli error: {result.stderr.strip()}")
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="LND timeout")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"LND response parse error: {e}")


def systemctl_active(service: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


def get_uptime() -> str:
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
        d, h, m = int(secs // 86400), int((secs % 86400) // 3600), int((secs % 3600) // 60)
        if d > 0:
            return f"{d}d {h}h {m}m"
        elif h > 0:
            return f"{h}h {m}m"
        return f"{m}m"
    except Exception:
        return "unknown"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": AGENT_VERSION, "ts": int(time.time())}


@app.get("/api/status")
def get_status():
    info = lncli("getinfo")
    wallet = lncli("walletbalance")
    channel_data = lncli("listchannels")

    services = {
        "bitcoind":   systemctl_active("bitcoind"),
        "lnd":        systemctl_active("lnd"),
        "btcpayserver": systemctl_active("btcpayserver"),
        "nbxplorer":  systemctl_active("nbxplorer"),
        "nginx":      systemctl_active("nginx"),
    }

    active_channels = channel_data.get("channels", [])
    active_count = len([c for c in active_channels if c.get("active")])

    return {
        "version": AGENT_VERSION,
        "ts": int(time.time()),
        "node": {
            "alias": info.get("alias"),
            "pubkey": info.get("identity_pubkey"),
            "block_height": info.get("block_height"),
            "synced_to_chain": info.get("synced_to_chain"),
            "synced_to_graph": info.get("synced_to_graph"),
            "num_active_channels": info.get("num_active_channels"),
            "num_pending_channels": info.get("num_pending_channels"),
            "lnd_version": info.get("version"),
        },
        "wallet": {
            "confirmed_sat": int(wallet.get("confirmed_balance", 0)),
            "unconfirmed_sat": int(wallet.get("unconfirmed_balance", 0)),
            "locked_sat": int(wallet.get("locked_balance", 0)),
        },
        "channels": {
            "active": active_count,
            "pending": info.get("num_pending_channels", 0),
        },
        "services": services,
        "uptime": get_uptime(),
    }


@app.get("/api/channels")
def get_channels():
    active = lncli("listchannels")
    pending = lncli("pendingchannels")

    channels_out = []
    for c in active.get("channels", []):
        local = int(c["local_balance"])
        capacity = int(c["capacity"])
        pct = round(local / capacity * 100, 1) if capacity > 0 else 0
        channels_out.append({
            "chan_id": c.get("chan_id"),
            "remote_pubkey": c.get("remote_pubkey"),
            "local_balance_sat": local,
            "remote_balance_sat": int(c["remote_balance"]),
            "capacity_sat": capacity,
            "local_pct": pct,
            "active": c.get("active", False),
            "total_satoshis_sent": int(c.get("total_satoshis_sent", 0)),
            "total_satoshis_received": int(c.get("total_satoshis_received", 0)),
        })

    pending_out = []
    for p in pending.get("pending_open_channels", []):
        ch = p.get("channel", {})
        pending_out.append({
            "remote_pubkey": ch.get("remote_node_pub"),
            "local_balance_sat": int(ch.get("local_balance", 0)),
            "capacity_sat": int(ch.get("capacity", 0)),
            "confirmation_height": p.get("confirmation_height"),
            "commit_fee_sat": int(p.get("commit_fee", 0)),
        })

    return {
        "active": channels_out,
        "pending": pending_out,
        "summary": {
            "active_count": len(channels_out),
            "pending_count": len(pending_out),
            "total_local_sat": sum(c["local_balance_sat"] for c in channels_out),
            "total_remote_sat": sum(c["remote_balance_sat"] for c in channels_out),
        }
    }


@app.get("/api/invoices")
def get_invoices(last: int = 20):
    data = lncli("listinvoices", "--reversed", f"--num_max_invoices={min(last, 100)}")
    out = []
    for inv in data.get("invoices", []):
        state = inv.get("state", "UNKNOWN")
        settle_ts = int(inv.get("settle_date", 0))
        out.append({
            "payment_hash": inv.get("r_hash"),
            "memo": inv.get("memo", ""),
            "value_sat": int(inv.get("value", 0)),
            "state": state,
            "created_at": int(inv.get("creation_date", 0)),
            "settled_at": settle_ts if state == "SETTLED" else None,
            "expiry": int(inv.get("expiry", 3600)),
        })
    return {"invoices": out, "count": len(out)}


@app.get("/api/sync")
def get_sync():
    info = lncli("getinfo")
    return {
        "synced_to_chain": info.get("synced_to_chain"),
        "synced_to_graph": info.get("synced_to_graph"),
        "block_height": info.get("block_height"),
        "best_header_timestamp": info.get("best_header_timestamp"),
    }


@app.get("/api/peers")
def get_peers():
    data = lncli("listpeers")
    peers = []
    for p in data.get("peers", []):
        peers.append({
            "pubkey": p.get("pub_key"),
            "address": p.get("address"),
            "bytes_sent": int(p.get("bytes_sent", 0)),
            "bytes_recv": int(p.get("bytes_recv", 0)),
            "sat_sent": int(p.get("sat_sent", 0)),
            "sat_recv": int(p.get("sat_recv", 0)),
            "sync_type": p.get("sync_type"),
        })
    return {"peers": peers, "count": len(peers)}


@app.post("/api/backup")
def trigger_backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    path = f"{BACKUP_DIR}/channels-{ts}.bak"
    data = lncli("exportchanbackup", "--all")
    with open(path, "w") as f:
        json.dump(data, f)
    return {"status": "ok", "path": path, "ts": ts}



# ── Magma helpers ─────────────────────────────────────────────────────────────

async def magma_query(query: str, variables: dict = None):
    """Execute a GraphQL query against the Amboss Magma API."""
    headers = {"Content-Type": "application/json"}
    if MAGMA_API_KEY:
        headers["Authorization"] = f"Bearer {MAGMA_API_KEY}"
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(MAGMA_GRAPHQL, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            raise HTTPException(status_code=502, detail=f"Magma error: {data['errors']}")
        return data.get("data", {})


@app.get("/api/magma/offers")
async def get_magma_offers(min_sat: int = 100000, max_sat: int = 5000000):
    """
    Fetch live inbound liquidity offers from Magma marketplace.
    Returns offers sized between min_sat and max_sat.
    Anonymous access — no API key required.
    """
    query = """
    query GetOffers($minSize: Float, $maxSize: Float) {
      getOffers(where: { min_channel_size: { gte: $minSize }, max_channel_size: { lte: $maxSize } }) {
        id
        node_pubkey
        min_channel_size
        max_channel_size
        base_fee
        fee_rate
        min_block_length
        order_quantity
        status
      }
    }
    """
    try:
        data = await magma_query(query, {"minSize": min_sat, "maxSize": max_sat})
        offers = data.get("getOffers", [])
        return {
            "offers": offers,
            "count": len(offers),
            "filter": {"min_sat": min_sat, "max_sat": max_sat},
            "note": "anonymous_access" if not MAGMA_API_KEY else "authenticated",
        }
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"Magma unreachable: {e}")


@app.get("/api/magma/node-score")
async def get_magma_node_score():
    """
    Fetch HVE-Mercury's Amboss node health score and reputation metrics.
    Requires our pubkey — uses node info from LND getinfo.
    """
    info, _ = lncli("getinfo"), None
    info = lncli("getinfo")[0]
    if not info:
        raise HTTPException(status_code=503, detail="LND unavailable")
    pubkey = info.get("identity_pubkey")

    query = """
    query GetNodeScore($pubkey: String!) {
      getNode(pubkey: $pubkey) {
        alias
        capacity
        channel_count
        amboss_health {
          score
          grade
          last_update
        }
      }
    }
    """
    try:
        data = await magma_query(query, {"pubkey": pubkey})
        node = data.get("getNode", {})
        return {
            "pubkey": pubkey,
            "alias": node.get("alias"),
            "capacity_sat": node.get("capacity"),
            "channel_count": node.get("channel_count"),
            "health": node.get("amboss_health", {}),
        }
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"Magma unreachable: {e}")


@app.get("/api/magma/recommend")
async def get_magma_recommendations():
    """
    Pull Magma AI channel recommendations for our node.
    Returns top peers to open channels with for optimal routing position.
    Read-only intelligence — human approval required before any action.
    """
    info = lncli("getinfo")[0]
    if not info:
        raise HTTPException(status_code=503, detail="LND unavailable")
    pubkey = info.get("identity_pubkey")

    query = """
    query GetRecommendations($pubkey: String!) {
      getNodeRecommendations(pubkey: $pubkey) {
        node_pubkey
        alias
        score
        reason
        suggested_size_sat
        expected_routing_volume_sat
      }
    }
    """
    try:
        data = await magma_query(query, {"pubkey": pubkey})
        recs = data.get("getNodeRecommendations", [])
        return {
            "pubkey": pubkey,
            "recommendations": recs,
            "count": len(recs),
            "action_required": "human_approval",
            "note": "READ-ONLY — recommendations only, no channels opened automatically",
        }
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"Magma unreachable: {e}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8088,
        log_level="info",
        access_log=True,
    )
