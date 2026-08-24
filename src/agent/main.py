"""
Mercury Agent — v0.5.2
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
  POST /api/magma/buy         Initiate Magma channel purchase (requires API key)
  GET  /api/routing           Forwarding history — payments routed + fees earned
  GET  /api/payments          Lightning payment history — sent + received unified
  GET  /api/magma/orders      List all Magma orders placed from this node
  GET  /health                Liveness check (for systemd / load balancer)

This service runs as user 'lnd' so it can read LND macaroons.
Node operations: reads are anonymous. /api/magma/buy requires MAGMA_API_KEY.
Magma read access is anonymous — no API key required to start.
"""

import hmac
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional

try:
    from fastapi import FastAPI, Header, HTTPException
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
BACKUP_TOKEN = os.getenv("MERCURY_BACKUP_TOKEN", "")
ORDERS_FILE = "/var/lib/mercury/magma_orders.json"
AGENT_VERSION = "0.5.5"

app = FastAPI(
    title="Mercury Agent API",
    description="Read-only Lightning node API for Mercury Agent AI layer",
    version=AGENT_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin for origin in os.getenv("MERCURY_CORS_ORIGINS", "").split(",") if origin],
    allow_methods=["GET"],
    allow_headers=[],
)

# ── Request models ────────────────────────────────────────────────────────────

try:
    from pydantic import BaseModel

    class MagmaBuyRequest(BaseModel):
        offer_id: str
        size_sat: float = 0.0
        api_key: str = ""

except ImportError:
    # Pydantic not available — define a minimal shim
    class MagmaBuyRequest:  # type: ignore
        def __init__(self, offer_id: str, size_sat: float = 0.0, api_key: str = ""):
            self.offer_id = offer_id
            self.size_sat = size_sat
            self.api_key = api_key


# ── LND wrapper ───────────────────────────────────────────────────────────────

def lncli(*args, timeout=15):
    """Run lncli and return parsed JSON or raise HTTPException."""
    # Service runs as lnd user — call lncli directly (no sudo needed)
    cmd = ["lncli", f"--lnddir={LND_DIR}"] + list(args)
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
    pending_data = lncli("pendingchannels")

    services = {
        "bitcoind":   systemctl_active("bitcoind"),
        "lnd":        systemctl_active("lnd"),
        "btcpayserver": systemctl_active("btcpayserver"),
        "nbxplorer":  systemctl_active("nbxplorer"),
        "nginx":      systemctl_active("nginx"),
    }

    active_channels = channel_data.get("channels", [])
    active_count = int(info.get("num_active_channels", 0))
    open_count = len(active_channels)
    pending_count = sum(
        len(pending_data.get(key, []))
        for key in (
            "pending_open_channels",
            "pending_closing_channels",
            "pending_force_closing_channels",
            "waiting_close_channels",
        )
    )

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
            "open": open_count,
            "pending": pending_count,
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
    pending_types = (
        ("pending_open_channels", "opening"),
        ("pending_closing_channels", "closing"),
        ("pending_force_closing_channels", "force_closing"),
        ("waiting_close_channels", "waiting_close"),
    )
    for key, state in pending_types:
        for p in pending.get(key, []):
            ch = p.get("channel", p)
            pending_out.append({
                "state": state,
                "remote_pubkey": ch.get("remote_node_pub") or ch.get("remote_node_pubkey"),
                "local_balance_sat": int(ch.get("local_balance", 0)),
                "capacity_sat": int(ch.get("capacity", 0)),
                "confirmation_height": p.get("confirmation_height"),
                "commit_fee_sat": int(p.get("commit_fee", 0)),
            })

    return {
        "active": channels_out,
        "pending": pending_out,
        "summary": {
            "active_count": sum(1 for c in channels_out if c["active"]),
            "open_count": len(channels_out),
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
def trigger_backup(x_mercury_backup_token: Optional[str] = Header(default=None)):
    if not BACKUP_TOKEN:
        raise HTTPException(status_code=503, detail="Backup API is not configured")
    if not x_mercury_backup_token or not hmac.compare_digest(
        x_mercury_backup_token, BACKUP_TOKEN
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.chmod(BACKUP_DIR, 0o700)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    path = f"{BACKUP_DIR}/channels-{ts}.bak"
    data = lncli("exportchanbackup", "--all")
    with open(path, "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as f:
        json.dump(data, f)
    os.chmod(path, 0o600)
    return {"status": "ok", "path": path, "ts": ts}


@app.get("/api/routing")
def get_routing_history(limit: int = 50, days: int = 30):
    """
    Return forwarding history (routing events) from LND.
    Shows payments we routed for other nodes, fees earned per hop.
    """
    # Build time window: start_time = now - days
    start_ts = int(time.time()) - (days * 86400)
    data = lncli(
        "fwdinghistory",
        f"--start_time={start_ts}",
        f"--max_events={limit}",
        "--index_offset=0",
    )
    events = data.get("forwarding_events", [])

    # Build chan_id → alias map from active channels
    try:
        ch_data = lncli("listchannels")
        chan_map = {}
        for ch in ch_data.get("channels", []):
            cid = ch.get("chan_id", "")
            pk  = ch.get("remote_pubkey", "")
            # We'll resolve alias via peers later; use pubkey prefix for now
            chan_map[cid] = pk[:16] + "..."
    except Exception:
        chan_map = {}

    result = []
    total_fees_msat = 0
    for e in events:
        amt_in   = int(e.get("amt_in", 0))
        amt_out  = int(e.get("amt_out", 0))
        fee_msat = int(e.get("fee_msat", 0))
        ts       = int(e.get("timestamp", 0))
        chan_in   = e.get("chan_id_in", "")
        chan_out  = e.get("chan_id_out", "")
        total_fees_msat += fee_msat
        result.append({
            "timestamp":    ts,
            "amt_in_sat":   amt_in,
            "amt_out_sat":  amt_out,
            "fee_msat":     fee_msat,
            "fee_sat":      round(fee_msat / 1000, 3),
            "chan_in":       chan_map.get(chan_in, chan_in[-8:] if len(chan_in) > 8 else chan_in),
            "chan_out":      chan_map.get(chan_out, chan_out[-8:] if len(chan_out) > 8 else chan_out),
        })

    # Most recent first
    result.sort(key=lambda x: x["timestamp"], reverse=True)

    return {
        "events":           result,
        "total":            len(result),
        "total_fees_sat":   round(total_fees_msat / 1000, 3),
        "days":             days,
    }


@app.get("/api/payments")
def get_payments(limit: int = 50):
    """
    Return unified Lightning payment history — sent + received.
    Sent:     lncli listpayments (SUCCEEDED)
    Received: lncli listinvoices (SETTLED)
    Returns combined timeline sorted newest-first.
    """
    result = []

    # Sent payments
    try:
        pay_data = lncli("listpayments", f"--max_payments={limit}", "--include_incomplete=false")
        for p in pay_data.get("payments", []):
            if p.get("status") != "SUCCEEDED":
                continue
            ts_ns  = int(p.get("creation_time_ns", 0))
            ts     = ts_ns // 1_000_000_000
            amt    = int(p.get("value_sat", 0))
            fee    = int(p.get("fee_sat", 0))
            memo   = ""
            req    = p.get("payment_request", "")
            result.append({
                "direction":  "sent",
                "amount_sat": amt,
                "fee_sat":    fee,
                "memo":       memo,
                "timestamp":  ts,
                "status":     "succeeded",
                "payment_hash": p.get("payment_hash", "")[:16],
            })
    except Exception:
        pass

    # Received payments (settled invoices)
    try:
        inv_data = lncli("listinvoices", f"--num_max_invoices={limit}", "--reversed=true")
        for inv in inv_data.get("invoices", []):
            if inv.get("state") != "SETTLED":
                continue
            settle_ts = int(inv.get("settle_date", 0))
            amt       = int(inv.get("amt_paid_sat", inv.get("value", 0)))
            memo      = inv.get("memo", "")
            # Skip internal rebalance invoices
            if memo == "mercury-rebalance":
                continue
            result.append({
                "direction":  "received",
                "amount_sat": amt,
                "fee_sat":    0,
                "memo":       memo,
                "timestamp":  settle_ts,
                "status":     "settled",
                "payment_hash": inv.get("r_hash", "")[:16],
            })
    except Exception:
        pass

    result.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"payments": result[:limit], "total": len(result)}


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
    Anonymous access — no API key required.
    """
    query = """
    {
      market {
        offer {
          offers {
            total
            list {
              id
              status
              total_amount { satoshi { sats } }
              fees { fixed { sats } variable { sats } }
              node { alias }
            }
          }
        }
      }
    }
    """
    try:
        data = await magma_query(query)
        raw = data.get("market", {}).get("offer", {}).get("offers", {})
        all_offers = raw.get("list", [])
        def offer_size(o):
            try:
                return int(o["total_amount"]["satoshi"]["sats"])
            except (TypeError, KeyError):
                return 0

        filtered = [o for o in all_offers if min_sat <= offer_size(o) <= max_sat]
        return {
            "offers": [
                {
                    "id": o["id"],
                    "status": o["status"],
                    "size_sat": offer_size(o),
                    "fee_fixed_sat": int((o.get("fees") or {}).get("fixed", {}).get("sats", 0) or 0),
                    "fee_variable_sat": int((o.get("fees") or {}).get("variable", {}).get("sats", 0) or 0),
                    "node_alias": (o.get("node") or {}).get("alias", "unknown"),
                }
                for o in filtered
            ],
            "count": len(filtered),
            "total_market": raw.get("total", 0),
            "filter": {"min_sat": min_sat, "max_sat": max_sat},
            "note": "anonymous_access" if not MAGMA_API_KEY else "authenticated",
        }
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"Magma unreachable: {e}")


@app.get("/api/magma/node-score")
async def get_magma_node_score():
    """
    Fetch HVE-Mercury's visibility and info on the Amboss graph.
    """
    info = lncli("getinfo")
    if not info:
        raise HTTPException(status_code=503, detail="LND unavailable")
    pubkey = info.get("identity_pubkey")

    query = """
    query GetNodeInfo($uri: String!) {
      node {
        node_info(connection_uri: $uri) {
          pubkey
          visible_in_graph
          amboss { min_channel_size }
        }
      }
    }
    """
    try:
        data = await magma_query(query, {"uri": pubkey})
        node = data.get("node", {}).get("node_info", {})
        amboss = node.get("amboss", {}) or {}
        return {
            "pubkey": pubkey,
            "alias": info.get("alias"),
            "visible_in_graph": node.get("visible_in_graph", False),
            "min_channel_size_sat": amboss.get("min_channel_size"),
            "note": "Claim node on amboss.space to unlock full score + profile" if not node.get("visible_in_graph") else "Node visible in graph",
        }
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"Magma unreachable: {e}")


@app.get("/api/magma/recommend")
async def get_magma_recommendations():
    """
    Return top Magma offers Mercury actually qualifies for, sorted by total fee.
    Uses authenticated getOffers with conditions filtering based on Mercury's live capacity.
    Human approval required before any action.
    """
    # Get Mercury's current total channel capacity
    channels_data = lncli("listchannels")
    channels = channels_data.get("channels", []) if channels_data else []
    node_capacity = sum(int(c.get("capacity", 0)) for c in channels)

    api_key = MAGMA_API_KEY
    env_path = os.path.expanduser("~/.mercury/amboss.env")
    if not api_key and os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("MAGMA_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")

    query = """
    {
      getOffers {
        list {
          id
          account
          min_size
          max_size
          fee_rate
          base_fee
          status
          conditions { condition operator value }
        }
      }
    }
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    AMBOSS_GRAPHQL = "https://api.amboss.space/graphql"

    # Pre-build alias map from local LND graph
    alias_map: dict = {}
    try:
        graph = lncli("describegraph")
        for n in (graph or {}).get("nodes", []):
            pub = n.get("pub_key", "")
            alias = n.get("alias", "")
            if pub and alias:
                alias_map[pub] = alias
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(AMBOSS_GRAPHQL, json={"query": query}, headers=headers)
            r.raise_for_status()
            data = r.json()

        offers = data.get("data", {}).get("getOffers", {}).get("list", [])

        TARGET_SIZE = 5_000_000  # default buy target for fee calculation
        qualifying = []
        for o in offers:
            if o.get("status") not in (None, "ACTIVE", "ENABLED", "active", "enabled"):
                if o.get("status") and o.get("status").upper() not in ("ACTIVE", "ENABLED"):
                    pass  # include anyway — status field varies

            conds = o.get("conditions") or []
            blocked = False
            for c in conds:
                cond = c.get("condition", "")
                val = c.get("value", "")
                op = c.get("operator", "")
                if cond == "NODE_CAPACITY":
                    req_cap = int(val)
                    if op in ("GREATER_THAN", "GREATER_THAN_OR_EQUAL_TO"):
                        if node_capacity < req_cap:
                            blocked = True
            if blocked:
                continue

            mx = int(o.get("max_size") or 0)
            mn = int(o.get("min_size") or 0)
            fr = int(o.get("fee_rate") or 0)
            bf = int(o.get("base_fee") or 0)
            if mx < 1_000_000:
                continue
            buy_size = min(TARGET_SIZE, mx)
            if buy_size < mn:
                continue

            total_fee = bf + int(fr * buy_size / 1_000_000)
            qualifying.append({
                "offer_id":       o["id"],
                "node_alias":     alias_map.get(str(o.get("account","")), str(o.get("account","unknown"))[:20]),
                "node_pubkey":    str(o.get("account","")),
                "size_sat":       buy_size,
                "max_size":       mx,
                "fee_rate_ppm":   fr,
                "fee_fixed_sat":  bf,
                "total_fee_sat":  total_fee,
            })

        qualifying.sort(key=lambda x: x["total_fee_sat"])
        return {
            "recommendations":  qualifying[:10],
            "count":            len(qualifying),
            "node_capacity_sat": node_capacity,
            "action_required":  "human_approval",
            "note": (
                f"Filtered to offers Mercury qualifies for "
                f"(node capacity: {node_capacity:,} SAT). "
                "READ-ONLY — human approval required before purchasing."
            ),
        }
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"Magma unreachable: {e}")


@app.post("/api/magma/buy")
async def buy_magma_channel(req: MagmaBuyRequest):
    """
    Initiate a Magma channel purchase via the Amboss API.
    Requires a valid MAGMA_API_KEY (passed in request body or from server env).
    Returns the fee invoice (BOLT11) to pay to complete the channel open.
    """
    api_key = req.api_key or MAGMA_API_KEY
    if not api_key:
        raise HTTPException(
            status_code=403,
            detail="MAGMA_API_KEY not configured. Visit amboss.space to create an account and generate a key.",
        )

    # Get our node pubkey for the buy request
    info = lncli("getinfo")
    our_pubkey = info.get("identity_pubkey", "")
    if not our_pubkey:
        raise HTTPException(status_code=503, detail="Could not retrieve node pubkey from LND")

    # Amboss Magma GraphQL mutation — market.order.create (correct v2 API)
    # Introspected from magma.amboss.tech/graphql: nested mutation structure.
    mutation = """
    mutation CreateManualOrder($input: CreateManualOrderInput!) {
      market {
        order {
          create(input: $input) {
            id
            status
            payment {
              id
              pending
              lightning {
                invoice
                pending
              }
            }
          }
        }
      }
    }
    """
    variables = {
        "input": {
            "offer_id":        req.offer_id,
            "size":            str(req.size_sat),
            "pubkey":          our_pubkey,
            "payment_method":  "SATS",
        }
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {"query": mutation, "variables": variables}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(MAGMA_GRAPHQL, json=payload, headers=headers)
            if r.status_code >= 400:
                try:
                    body = r.json()
                    err_detail = body.get("errors", [{}])[0].get("message", r.text[:300])
                except Exception:
                    err_detail = r.text[:300]
                raise HTTPException(
                    status_code=502,
                    detail=f"Amboss HTTP {r.status_code}: {err_detail}"
                )
            data = r.json()

        if "errors" in data:
            err_msg = "; ".join(e.get("message", str(e)) for e in data["errors"])
            raise HTTPException(status_code=502, detail=f"Amboss error: {err_msg}")

        order = (data.get("data") or {}).get("market", {}).get("order", {}).get("create")
        if not order:
            raise HTTPException(status_code=502, detail="Amboss returned empty order — offer may have expired or size is invalid")

        order_id = order.get("id", "")
        order_status = order.get("status", "")
        payment = order.get("payment") or {}
        lightning = payment.get("lightning") or {}
        invoice = lightning.get("invoice", "")

        # Persist order locally for `magma status`
        _save_magma_order({
            "order_id":    order_id,
            "offer_id":    req.offer_id,
            "size_sat":    int(req.size_sat),
            "status":      order_status or "submitted",
            "created_at":  datetime.now(timezone.utc).isoformat(),
        })

        return {
            "status": order_status or "submitted",
            "purchase_id": order_id,
            "invoice": invoice,
            "note": (
                "Order placed. Pay the invoice below to complete the channel open. "
                "Then run `mercury channels` to see it appear as pending."
                if invoice else
                "Order placed with Amboss. The liquidity provider will open a channel "
                "to your node shortly. Run `mercury channels` to see it appear as pending."
            ),
        }
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Amboss API error: {e.response.status_code}")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"Amboss unreachable: {e}")


# ── Magma order persistence ────────────────────────────────────────────────────

def _load_magma_orders() -> list:
    """Load locally cached Magma orders from disk."""
    try:
        os.makedirs(os.path.dirname(ORDERS_FILE), exist_ok=True)
        with open(ORDERS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_magma_order(order: dict):
    """Append a new Magma order to the local orders file."""
    orders = _load_magma_orders()
    # Deduplicate by order_id
    orders = [o for o in orders if o.get("order_id") != order.get("order_id")]
    orders.append(order)
    os.makedirs(os.path.dirname(ORDERS_FILE), exist_ok=True)
    with open(ORDERS_FILE, "w") as f:
        json.dump(orders, f, indent=2)


@app.get("/api/magma/orders")
async def get_magma_orders():
    """
    Return all Magma inbound liquidity orders placed from this node.
    Reads locally cached orders then refreshes status from Amboss for each.
    """
    api_key = MAGMA_API_KEY
    cached = _load_magma_orders()
    if not cached:
        return {"orders": [], "total": 0}

    results = []
    for o in cached:
        offer_id = o.get("offer_id", "")
        order_id = o.get("order_id", "")
        live_status = o.get("status", "unknown")
        seller_alias = o.get("seller_alias", "")

        # Try to refresh status from Amboss via get_offer → orders
        if offer_id and api_key:
            try:
                query = """
                query GetOfferOrders($offer_id: String!) {
                  market {
                    offer {
                      get_offer(offer_id: $offer_id) {
                        node { alias }
                        orders {
                          list {
                            id
                            status
                            amount { sat }
                            created_at
                          }
                        }
                      }
                    }
                  }
                }
                """
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                }
                async with httpx.AsyncClient(timeout=15) as client:
                    r = await client.post(
                        MAGMA_GRAPHQL,
                        json={"query": query, "variables": {"offer_id": offer_id}},
                        headers=headers,
                    )
                    data = r.json()

                offer_data = (
                    (data.get("data") or {})
                    .get("market", {})
                    .get("offer", {})
                    .get("get_offer") or {}
                )
                if not seller_alias:
                    seller_alias = (offer_data.get("node") or {}).get("alias", "")

                for ord_item in (offer_data.get("orders") or {}).get("list") or []:
                    if ord_item.get("id") == order_id:
                        live_status = ord_item.get("status", live_status)
                        break
            except Exception:
                pass  # fall back to cached status

        results.append({
            "order_id":    order_id,
            "offer_id":    offer_id,
            "size_sat":    o.get("size_sat", 0),
            "status":      live_status,
            "seller":      seller_alias,
            "created_at":  o.get("created_at", ""),
        })

    # Most recent first
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"orders": results, "total": len(results)}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("MERCURY_AGENT_HOST", "127.0.0.1"),
        port=8088,
        log_level="info",
        access_log=True,
    )
