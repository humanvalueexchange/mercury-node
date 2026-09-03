# Mercury Node

Mercury Node is a self-hosted Bitcoin and Lightning operator console with a local
AI assistant. The current reference deployment is a **Debian GNU/Linux 13
(trixie), ARM64 Raspberry Pi 5-class node** with a Hailo-10H PCIe accelerator.

> **Deployment status:** This repository is under active development. The live
> reference host and the checked-in installer are not identical; do not use the
> installer with production funds without reviewing its limitations below.

## Current reference stack

| Layer | Current contract |
|---|---|
| Operating system | Debian 13 (trixie), `aarch64`/ARM64 |
| Hardware | Raspberry Pi 5-class ARM64 host, 16 GiB RAM |
| AI accelerator | Hailo-10H PCIe co-processor |
| Local model | `Qwen3.8-2B-Distill-Q4_K_M.gguf` via native `llama.cpp` |
| LLM service | `llama-server` on `127.0.0.1:8089` |
| Approved split planner | `hailo-ollama` on `127.0.0.1:8000` (repository contract; live promotion remains pending) |
| Bitcoin | Bitcoin Core 30.2.0; data at `/mnt/blockchain/bitcoin` |
| Lightning | LND 0.20.1-beta; data at `/var/lib/lnd` |
| Agent | FastAPI service, version 0.5.5, on `127.0.0.1:8088` |
| Application layout | `/opt/mercury` |
| Supporting services | NBXplorer, BTCPay Server, nginx |

See [docs/current-state.md](docs/current-state.md) for the dated live snapshot,
[docs/architecture.md](docs/architecture.md) for service boundaries, and
[docs/hardware-bom.md](docs/hardware-bom.md) for the reference hardware.

The controlled split-inference branch includes Hailo readiness/prewarm units,
deadline-aware CPU merge fallback, and three narrowly bounded snapshot-only
status responses. These repository artifacts do not authorize live service
enablement or promotion.

## Layout

The live deployment keeps Mercury application files under:

```text
/opt/mercury/
├── agent/main.py
├── llama.cpp/bin/llama-server
├── llama.cpp/lib/
└── models/Qwen3.8-2B-Distill-Q4_K_M.gguf
```

The agent's systemd unit runs as `lnd` from `/opt/mercury/agent`. The local LLM
unit runs `llama-server` on localhost port 8089. Bitcoin data is on the separate
blockchain volume mounted at `/mnt/blockchain`.

## CLI

The checked-in CLI is `mercury`. Its interactive shell includes the version
display; the argparse command list is available with `mercury --help`.
These are the implemented node-facing commands:

```bash
mercury status [--ai]
mercury health [--ai]
mercury sync [--ai]
mercury channels [--ai]
mercury invoices [--last N] [--recent|--pending]
mercury payments [--limit N] [--ai]
mercury peers [--ai]
mercury routing [DAYS] [--ai]
mercury transactions [--limit N] [--all] [--ai]
mercury logs [lnd|bitcoind|btcpayserver|nbxplorer|nginx|mercury-agent]
mercury backup
mercury ask "<question>"
mercury shell
```

Payment and channel operations are also implemented:

```bash
mercury invoice <SAT> [memo]
mercury charge <SAT> [memo]
mercury pay <BOLT11>
mercury deposit [--amount SAT]
mercury send <BITCOIN_ADDRESS> <SAT>
mercury channel open <peer-alias|pubkey@host:port> <SAT>
mercury channel close <alias|channel_point>
mercury rebalance [--amount SAT] [--dry-run]
mercury fees [set <PPM> [BASE_MSAT]]
mercury nodes
mercury magma [offers|score|recommend|buy|status|auth]
```

`pay`, `send`, channel changes, fee changes, and Magma purchases can affect
funds or node state. Review the command's confirmation prompt and the
transaction/invoice details before approving.

The CLI also contains operator integrations such as `alerts`, `post`,
`post-share`, `suggest`, `vote`, `rank-backlog`, `recommend`, and `tonight`.
Those commands are not part of the node's public HTTP API.

## Agent API

The FastAPI service listens on localhost by default:

```bash
curl http://127.0.0.1:8088/health
curl http://127.0.0.1:8088/api/status
```

Implemented routes are:

```text
GET  /health
GET  /api/status
GET  /api/channels
GET  /api/invoices?last=N
GET  /api/sync
GET  /api/peers
POST /api/backup
GET  /api/routing?limit=N&days=D
GET  /api/payments?limit=N
GET  /api/magma/offers?min_sat=N&max_sat=N
GET  /api/magma/node-score
GET  /api/magma/recommend
POST /api/magma/buy
GET  /api/magma/orders
GET  /api/tools
POST /api/tools/{name}/prepare
POST /api/tools/{name}/execute
```

Read routes are intentionally operational telemetry. `POST /api/backup`
requires the `X-Mercury-Backup-Token` header and a configured
`MERCURY_BACKUP_TOKEN`. `POST /api/magma/buy` requires `MAGMA_API_KEY`; it
creates an Amboss order and returns an invoice, but does not autonomously pay it.
The Magma endpoint additionally requires `X-Mercury-CLI-Approval: confirmed`,
which is only sent after the CLI confirmation prompt.
The tool routes expose the Hermes-style prepare/confirm boundary for agent
integrations. Preparation creates a short-lived token and never broadcasts;
write execution remains explicitly approved through the Mercury CLI.

## Installer limitations

`install.sh` is now a verified partial installer for Bitcoin Core, LND, the
Mercury agent, and the CLI. It installs under `/opt/mercury`, verifies the
published Bitcoin Core/LND checksums, preserves existing wallet configuration,
and refuses unsupported flags or unmanaged service-unit replacements.

It intentionally does not install BTCPay Server, NBXplorer, nginx, llama.cpp,
models, Hailo drivers, or UTXO snapshots. Review the script and complete those
optional components independently before using it as a production deployment.

## Registry and MCP status

The registry refactor is partially landed: `ToolRegistry`, `ToolSpec`, and
permission types exist, and `node.status` is registered and tested. The rest of
the CLI still uses its existing dispatch table; registry discovery and complete
CLI/API migration are not finished.

There is no checked-in MCP server, agent-card endpoint, Lightning-paid
agent-to-agent mesh, or public Mercury Registry implementation. Older Hailo-8L,
Phi-3.5, MCP, and automatic peer-discovery descriptions are obsolete design
claims, not current capabilities.

## Security

The node is designed so the money layer remains independent from the AI layer.
Keep LND RPC, the agent, and the LLM bound to localhost unless an authenticated
reverse-proxy design is in place. Protect the wallet seed, LND credentials,
environment files, and static channel backups as secrets. See
[SECURITY.md](SECURITY.md).

## License

MIT.
