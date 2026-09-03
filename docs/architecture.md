# Mercury Node Architecture

**Status:** Current repository/live contract
**Snapshot:** 2026-09-02

## System overview

The reference node is a Debian 13 ARM64 Raspberry Pi 5-class host. The Bitcoin
and Lightning services form the money layer; Mercury provides a local operator
CLI, a telemetry/read-and-prepare FastAPI service, and a local llama.cpp model
service.

```text
┌──────────────────────────────────────────────────────────┐
│ Operator                                                │
│ mercury CLI                                             │
├──────────────────────────────────────────────────────────┤
│ Mercury application                                     │
│ /opt/mercury/agent/main.py  FastAPI :8088 (localhost)   │
│ /opt/mercury/llama.cpp/bin/llama-server :8089 (localhost)│
│ Qwen3.8-2B-Distill-Q4_K_M.gguf                          │
├──────────────────────────────────────────────────────────┤
│ Lightning / payments                                    │
│ LND 0.20.1-beta  │  BTCPay Server  │  NBXplorer        │
├──────────────────────────────────────────────────────────┤
│ Bitcoin                                               │
│ Bitcoin Core 30.2.0, data /mnt/blockchain/bitcoin       │
├──────────────────────────────────────────────────────────┤
│ Hardware / OS                                          │
│ Debian 13 │ ARM64 │ Pi 5-class │ 16 GiB │ Hailo-10H    │
└──────────────────────────────────────────────────────────┘
```

The Hailo-10H is part of the reference hardware. The active model contract is
native `llama.cpp`; documentation must not imply that the old Hailo-8L/Phi-3.5
pipeline is still deployed.

## Runtime services and paths

The live host runs `bitcoind`, `lnd`, `nbxplorer`, `btcpayserver`, `nginx`,
`mercury-agent`, and `mercury-llm`. The repository contains Mercury's agent and
LLM unit files; the live host's complete service provisioning is not reproduced
by the checked-in installer.

| Component | Runtime contract |
|---|---|
| Bitcoin Core | 30.2.0; user `bitcoin`; `/mnt/blockchain/bitcoin` |
| LND | 0.20.1-beta; user `lnd`; `/var/lib/lnd` |
| NBXplorer | `/opt/nbxplorer/NBXplorer.dll`; user `btcpay` |
| BTCPay Server | `/opt/btcpayserver/BTCPayServer.dll`; user `btcpay` |
| Mercury Agent | `/opt/mercury/agent`; user `lnd`; port 8088 |
| Mercury LLM | `/opt/mercury/llama.cpp`; model under `/opt/mercury/models`; port 8089 |
| Backups | `/var/lib/mercury/backups` |

`mercury-agent.service` uses `NoNewPrivileges`, `ProtectSystem=strict`, and
explicit write access only to `/var/lib/mercury` and `/var/lib/lnd`. The LLM
service binds to `127.0.0.1` and is not a public inference endpoint. The live
LLM unit currently runs as `root`; this is a hardening risk requiring separate
deployment work.

The current live listener split is:

- localhost-only: agent `127.0.0.1:8088`, LLM `127.0.0.1:8089`, Bitcoin RPC
  `127.0.0.1:8332`;
- node-facing: Bitcoin P2P `8333` on IPv4/IPv6 and Lightning peer transport
  `9735`;
- web-facing: nginx on ports `80` and `443`.

## Agent API

The implemented FastAPI routes are:

| Method | Route | Contract |
|---|---|---|
| GET | `/health` | Liveness and agent version |
| GET | `/api/status` | LND, wallet, channel, service, and uptime summary |
| GET | `/api/channels` | Active and pending channels |
| GET | `/api/invoices?last=N` | Recent invoices |
| GET | `/api/sync` | Chain and graph synchronization |
| GET | `/api/peers` | Connected LND peers |
| POST | `/api/backup` | Export an SCB; requires `X-Mercury-Backup-Token` |
| GET | `/api/routing?limit=N&days=D` | Forwarding history and fees |
| GET | `/api/payments?limit=N` | Unified sent/received payment history |
| GET | `/api/magma/offers` | Public Magma offer query |
| GET | `/api/magma/node-score` | Amboss graph visibility |
| GET | `/api/magma/recommend` | Read-only offer recommendations |
| POST | `/api/magma/buy` | Creates an Amboss order; requires `MAGMA_API_KEY` |
| GET | `/api/magma/orders` | Cached/live order status |
| GET | `/api/tools` | Available typed operation catalog |
| POST | `/api/tools/{name}/prepare` | Prepare a short-lived operation plan |
| POST | `/api/tools/{name}/execute` | Confirmation-gated execution endpoint |

The agent invokes `lncli --lnddir=/var/lib/lnd` as the `lnd` service user.
The implemented node routes read LND state and export backups; the tool catalog
and prepare endpoints expose operation plans. The execute endpoint does not
execute agent-originated fund movement: it requires explicit confirmation and
returns the approval boundary to the Mercury CLI. The Magma buy route can
create a remote order but returns a payment invoice for explicit human
approval rather than paying it.

## CLI architecture

The executable `src/cli/mercury` retains a conventional argparse subcommand
dispatch table for the operational commands. It calls `lncli`, `bitcoin-cli`,
systemd, the local agent API, and the local/DGX Ollama-compatible model
endpoints as appropriate.

The registry refactor is intentionally incomplete:

- `src/cli/mercury_cli/registry.py` defines `Permission`, `ToolSpec`, and
  `ToolRegistry`;
- permission levels are `READ_ONLY`, `PREPARE_ONLY`, and
  `EXPLICIT_CONFIRMATION`;
- only `node.status` is currently registered by the CLI;
- the remaining commands are not registry-backed, and the registry does not
  yet generate or expose the HTTP API;
- `tests/test_registry.py` covers registration, duplicate names, lookup, and
  confirmation enforcement.

Therefore the registry is an architectural foundation, not a completed command
authorization layer.

## Data flows

### Status and telemetry

```text
mercury status
  ├─> lncli getinfo / walletbalance / listchannels
  ├─> systemctl is-active for stack services
  └─> render terminal output
```

The API follows the same pattern through `mercury-agent`; it does not proxy
arbitrary shell commands.

### Local AI query

```text
mercury ask "..."
  ├─> collect current LND/Bitcoin context
  ├─> POST OpenAI-compatible request to 127.0.0.1:8089
  ├─> llama-server loads Qwen3.8-2B-Distill
  └─> print response
```

If configured and reachable, the CLI can also use its DGX Spark Ollama URL as a
fallback. That remote Ollama endpoint is an operator configuration, not a
required Mercury service.

### Backup

`mercury backup` and authenticated `POST /api/backup` call
`lncli exportchanbackup --all` and write a timestamped file under
`/var/lib/mercury/backups` with directory mode `0700` and file mode `0600`.
Backups must be copied off-device securely; they are not a substitute for the
wallet seed.

## Security boundaries

The agent is not a wallet custodian and has no code path that autonomously pays
a Lightning invoice or sends an on-chain transaction. However, the process runs
as `lnd` to access LND state, so compromise of the host, LND account, wallet
credentials, or environment files remains in scope. Fund-moving CLI operations
are operator commands and require review/confirmation.

The default security posture is localhost binding, restricted systemd writes,
root-readable secret environment configuration, and no public MCP or registry
surface. See [SECURITY.md](../SECURITY.md) for the threat model and operator
requirements.

## Explicitly not implemented

The repository does not currently implement an MCP server, agent cards,
Lightning-preimage API authentication, automatic Lightning gossip/mDNS
discovery, agent-to-agent payments, or a public Mercury Registry. Those are
future design options and must not be presented as deployed features.
