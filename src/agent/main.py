"""
Mercury Agent — v0.2
FastAPI service exposing Mercury node status for the AI agent layer (Phi-3.5-mini / Ollama).

Endpoints:
  GET  /api/status       Full node health snapshot
  GET  /api/channels     Active + pending channel data
  GET  /api/invoices     Recent payments
  GET  /api/sync         Bitcoin sync progress
  GET  /api/peers        Connected Lightning peers
  POST /api/backup       Trigger static channel backup
  GET  /health           Liveness check (for systemd / load balancer)

This service runs as user 'lnd' so it can read LND macaroons.
It is intentionally READ-ONLY — it never signs transactions or moves funds.
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
except ImportError:
    raise SystemExit("FastAPI not installed. Run: pip install fastapi uvicorn")

LND_DIR = "/var/lib/lnd"
LND_USER = "lnd"
BACKUP_DIR = "/var/lib/mercury/backups"
AGENT_VERSION = "0.2.0"

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


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8088,
        log_level="info",
        access_log=True,
    )
