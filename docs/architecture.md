# Mercury Node — Architecture

**Version:** 0.1.0-draft  
**Owner:** CTO — Claude Sonnet 4.6  
**Last updated:** 2026-05-16

---

## System Overview

Mercury Node is a layered system. Each layer is independent — the intelligence layer can be removed without affecting the money layer.

```
┌─────────────────────────────────────────────────────┐
│                   USER INTERFACE                     │
│           mercury CLI  │  BTCPay Web UI              │
├─────────────────────────────────────────────────────┤
│                  INTELLIGENCE LAYER                  │
│     mercury-agent (FastAPI)  │  MCP Server           │
│     Phi-3.5-mini (Hailo-8L) │  Agent Mesh           │
├─────────────────────────────────────────────────────┤
│                   LIGHTNING LAYER                    │
│              LND (native binary)                     │
│         BTCPay Server  │  NBXplorer                 │
├─────────────────────────────────────────────────────┤
│                   BITCOIN LAYER                      │
│              Bitcoin Core (native)                   │
│              ZMQ pub: blocks + txs                   │
├─────────────────────────────────────────────────────┤
│                  HARDWARE LAYER                      │
│      Raspberry Pi 5 (16GB)  │  Hailo-8L Hat          │
│      NVMe SSD (1TB+)        │  ARM64                 │
└─────────────────────────────────────────────────────┘
```

---

## Service Architecture

All services run as independent systemd units. Start order enforced by `After=` directives.

```
bitcoind          ← foundation (starts first)
    ↓
nbxplorer         ← chain indexer (requires bitcoind)
    ↓
lnd               ← lightning (requires bitcoind)
    ↓
btcpayserver      ← payment server (requires nbxplorer + lnd)
    ↓
nginx             ← reverse proxy (requires btcpayserver)
    ↓
mercury-agent     ← intelligence (starts last, crashes alone)
```

### Service isolation guarantee
`mercury-agent` has no write access to any Bitcoin or LND wallet. It communicates via:
- LND gRPC (read-only scoped macaroon)
- BTCPay REST API (invoice creation only)
- bitcoind ZMQ (read-only subscribe)

A crash or compromise of `mercury-agent` cannot move funds.

---

## Mercury Agent Internal Architecture

```
mercury-agent (uvicorn, port 8088)
│
├── api/
│   ├── GET  /api/status          ← node health summary
│   ├── GET  /api/channels        ← LND listchannels
│   ├── GET  /api/invoices        ← LND listinvoices
│   ├── POST /api/ask             ← Hailo NL inference
│   ├── GET  /api/events          ← SSE stream
│   └── *    /mcp/...             ← MCP server endpoints
│
├── clients/
│   ├── lnd_client.py             ← gRPC (readonly.macaroon)
│   ├── btcpay_client.py          ← REST (invoice scope only)
│   └── bitcoind_zmq.py           ← ZMQ subscriber
│
├── intelligence/
│   ├── brain.py                  ← Phi-3.5-mini via llama.cpp + Hailo
│   ├── context_builder.py        ← live node state → system prompt
│   └── query_parser.py           ← intent detection (status/channels/ask)
│
└── mcp/
    ├── server.py                 ← MCP protocol handler
    ├── agent_card.py             ← /.well-known/agent.json publisher
    └── peer_discovery.py         ← Lightning gossip + mDNS discovery
```

---

## MCP Agent Mesh

### Agent Card Schema (published at `/mcp/.well-known/agent.json`)

```json
{
  "schema_version": "mercury/v1",
  "node": {
    "pubkey": "<LND_PUBKEY>",
    "alias": "<NODE_ALIAS>",
    "color": "#F7931A",
    "network": "mainnet"
  },
  "agent": {
    "name": "Mercury",
    "version": "1.0.0",
    "model": "phi-3.5-mini",
    "capabilities": ["status", "channels", "invoices", "ask", "route_query"]
  },
  "api": {
    "base_url": "https://<node-address>/mcp",
    "auth": "lightning_preimage",
    "price_per_call_msat": 100
  },
  "hardware": {
    "platform": "pi5",
    "accelerator": "hailo-8l",
    "node_type": "full"
  }
}
```

### Discovery Mechanisms (precedence order)

1. **Lightning Gossip** — automatic, zero-config. Channel peers exchange MCP capability advertisements via LND custom messages on channel open.
2. **mDNS / DNS-SD** — LAN discovery via `_mercury._tcp.local`. Useful for home lab multi-node setups.
3. **Mercury Registry** — opt-in public directory at `registry.mercury-node.dev`. Sovereignty-first: opt-in only, node works without it.

### Agent-to-Agent Payment Protocol

```
Node A asks Node B a question:

1. A → looks up B's agent card (via gossip, mDNS, or registry)
2. A → requests invoice from B for 100 mSat
3. B → returns BOLT11 invoice
4. A → pays invoice (atomic Lightning payment)
5. A → receives preimage (= API auth token, valid 60 seconds)
6. A → sends query to B's /mcp/query endpoint with preimage as bearer token
7. B → validates preimage (verifies payment), executes query, returns response
```

This protocol is:
- **Spam-resistant** by design (costs SATs)
- **Trustless** (payment proves intent)
- **Sovereign** (no central auth server)
- **Revenue-generating** (every query earns the answering node 100 mSat)

---

## Data Flows

### Payment received (customer → Mercury)
```
Customer wallet
    → Lightning payment (BOLT11)
    → LND (invoice settled)
    → mercury-agent event monitor (SubscribeInvoices gRPC)
    → Telegram alert + Apollo #mercury-ops post
    → BTCPay marks invoice settled
```

### `mercury ask` query
```
User: mercury ask "rebalance advice"
    → mercury CLI → POST /api/ask
    → context_builder: fetch live channel state from LND
    → brain.py: inject context into Phi-3.5-mini system prompt
    → Hailo-8L inference (<500ms)
    → response printed to terminal
```

### Agent-to-agent mesh query
```
mercury ask "what fee rate is my ACINQ peer using?"
    → mercury-agent detects peer query intent
    → peer_discovery: find ACINQ node's Mercury agent card
    → pay 100 mSat to ACINQ Mercury node
    → query /mcp/query with preimage
    → ACINQ Mercury agent returns fee data
    → Response printed to terminal
```

---

## Security Model

| Principle | Implementation |
|---|---|
| Keys never leave hardware | LND wallet on-device, seed phrase hardware-only |
| Agent is read-only by default | Scoped LND macaroon (readonly.macaroon) |
| Agent-to-agent auth is trustless | Lightning preimage proves payment |
| No cloud dependency | All inference runs locally on Hailo |
| Network exposure minimal | nginx reverse proxy, LND gRPC localhost-only |
| SSH keys-only | PasswordAuthentication disabled by installer |

---

## Hardware Specifications

| Component | Minimum | Recommended |
|---|---|---|
| Raspberry Pi 5 | **16GB RAM** | 16GB RAM |
| NVMe SSD | 500GB | 2TB |
| Hailo-8L Hat | Required for AI | Required for AI |
| NVMe Hat | M.2 Hat+ | M.2 Hat+ |
| Power | 27W USB-C | 27W USB-C |

**The 8GB Pi 5 is not supported.** Bitcoin Core + LND + BTCPay + Mercury Agent requires ~6-8GB RAM under load. The 8GB variant has insufficient headroom.

---

## Resource Usage (Pi 5 16GB, steady-state)

| Service | RAM | CPU | Disk |
|---|---|---|---|
| bitcoind | ~400MB | 2-5% | 600GB+ (full chain) |
| lnd | ~200MB | <1% | ~5GB |
| nbxplorer | ~300MB | <1% | ~2GB |
| btcpayserver | ~400MB | <1% | ~1GB |
| nginx | ~50MB | <1% | — |
| mercury-agent | ~200MB | <1% | — |
| Phi-3.5-mini (Hailo) | ~2.2GB (HBM) | 0% CPU | 2.2GB |
| **Total** | **~3.7GB** | **<10%** | **~610GB** |

16GB RAM provides ~12GB headroom for OS, caches, and IBD spike activity.
