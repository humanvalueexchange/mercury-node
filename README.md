# Mercury Node 🪐

**The world's simplest AI-first Bitcoin Lightning node.**

Buy a Raspberry Pi 5 (16GB) + Hailo-8L Hat. Run one command. Get a fully sovereign, AI-powered Bitcoin node with an intelligent agent living inside it — working for you 24/7.

```bash
curl -fsSL https://get.mercury-node.dev/install | bash
```

> No cloud. No KYC. No counterparty.  
> Just your own AI-powered Bitcoin & Lightning node that actually talks back to you.

---

## What is Mercury Node?

Mercury Node is a complete, open-source Bitcoin and Lightning stack with a built-in AI agent — running entirely on your own hardware, with your own keys, under your own control.

No cloud. No custodian. No counterparty. Just you, your Pi, and your Bitcoin.

```
$ mercury status

🟢 Mercury Node v1.0.0
─────────────────────────────────────
Node      HVE-Mercury
Network   mainnet | block 949,677 ✅
Wallet    1,247,891 SAT confirmed
Channels  3 active | avg balance 54%
Uptime    14 days, 6 hours
─────────────────────────────────────

$ mercury ask "should I rebalance any channels right now?"

Your ACINQ channel is well-balanced at 58% local.
Your WoS channel is getting low at 18% — recommend
rebalancing 30,000 SAT to restore routing balance.
```

---

## What's Inside

| Layer | Technology |
|---|---|
| Bitcoin full node | Bitcoin Core (native, ARM64) |
| Lightning Network | LND (native, ARM64) |
| Payment server | BTCPay Server |
| Chain indexer | NBXplorer |
| Reverse proxy | nginx |
| AI agent brain | Phi-3.5-mini on Hailo-8L (13 TOPS, <2W) |
| Agent API | FastAPI (mercury-agent service) |
| CLI | `mercury` — terminal-native control |
| Agent mesh | MCP server (agent-to-agent Lightning discovery) |

---

## Hardware Requirements

| Component | Spec | Where to buy |
|---|---|---|
| **Raspberry Pi 5** | **16GB RAM** (8GB not supported) | raspberrypi.com |
| **Hailo-8L AI Hat** | M.2 form factor | hailo.ai |
| **NVMe SSD** | 1TB minimum (2TB recommended) | Any M.2 NVMe |
| **NVMe Hat** | Pi 5 M.2 Hat+ | raspberrypi.com |
| **Power supply** | 27W USB-C (official Pi 5 PSU) | raspberrypi.com |
| **Case** | Optional — keep it cool | Any Pi 5 case |
| **microSD** | 32GB+ (OS only) | Any Class 10 |

**Estimated BOM cost: ~$250–300 USD**

> Full hardware assembly guide with photos: [docs/hardware-assembly.md](docs/hardware-assembly.md)

---

## Quick Start

### 1. Flash the OS
Flash **Raspberry Pi OS Lite (64-bit, Bookworm)** to microSD using Raspberry Pi Imager.
Enable SSH in the imager settings. Boot your Pi.

### 2. Run the installer
SSH into your Pi and run:
```bash
curl -fsSL https://get.mercury-node.dev/install | bash
```

The installer will:
- Detect your hardware (Pi 5 + Hailo required)
- Install the full Bitcoin + Lightning stack
- Walk you through your wallet seed ceremony (write down your 24 words)
- Start the Mercury agent
- Print your first `mercury status`

**Initial sync takes approximately 72 hours.** Your Lightning node is usable immediately — the Bitcoin chain syncs in the background.

### 3. You're sovereign

```bash
mercury status          # Node health at a glance
mercury channels        # Lightning channel overview
mercury invoices        # Recent payments
mercury ask "..."       # Ask your node anything
```

---

## The Mercury CLI

```bash
# Node operations
mercury status                    # Full health summary
mercury sync                      # Show IBD / sync progress

# Lightning
mercury channels                  # List active channels with balance %
mercury invoices [--last N]       # Recent invoices
mercury pay <BOLT11>              # Send a Lightning payment
mercury invoice <SAT> [memo]      # Create a Lightning invoice

# AI interface
mercury ask "<question>"          # Natural language node query
mercury ask "rebalance advice"    # Get channel rebalancing recommendation
mercury ask "show routing fees"   # Fee revenue summary

# Administration
mercury logs [service]            # Live log tail (lnd, btcpay, bitcoind, agent)
mercury restart [service]         # Restart a service
mercury backup                    # Export static channel backup
mercury update                    # Update Mercury Node to latest version
```

---

## The Agent Mesh (MCP)

Every Mercury Node publishes an MCP server. When two Mercury nodes open a Lightning channel to each other, their agents discover each other automatically — no directory, no configuration.

Agent-to-agent queries cost 100 mSat each. Intelligence flows over the same rails as money.

```bash
# Ask your node to query a peer's node
mercury ask "what fee rate is peer 03864ef using on their channels?"
# → Mercury pays 100 mSat, queries peer's agent, returns the answer
```

This is the foundation of a global Lightning-native AI mesh. Every Mercury Node is a node in it.

---

## Roadmap

| Version | Status | What ships |
|---|---|---|
| v0.1 | 🔨 In development | One-command install, full Bitcoin stack |
| v0.2 | Planned | `mercury` CLI, FastAPI agent, Telegram alerts |
| v0.3 | Planned | `mercury ask`, Phi-3.5-mini on Hailo-8L |
| v0.4 | Planned | MCP server, local peer discovery |
| v1.0 | Planned | Agent-to-agent Lightning mesh, public registry, public launch |

---

## Philosophy

Mercury Node is built on four principles:

1. **Sovereignty first.** Your keys. Your node. Your Bitcoin. No exceptions.
2. **Closest to metal.** Native binaries only. No Docker. No Snap. Every abstraction removed is one fewer failure point.
3. **Intelligence should be cheap and local.** AI inference runs on Hailo at <2W. You don't need a cloud API to have an intelligent node.
4. **Open source is the only option.** A sovereign money system deserves sovereign software. Audit everything.

---

## Built by Human Value Exchange

Mercury Node is the flagship open-source project of [Human Value Exchange](https://hvecorp.com) — a Bitcoin-only AI company building sovereign financial infrastructure.

Our production Mercury node has been running since 2026. This code runs our treasury.

---

## Contributing

Mercury Node is currently in private development. **Public launch targeted for July 2026.**

⭐ **Star this repo to be notified at launch.**

📬 **[Join the early access waitlist →](https://mercury-node.dev/waitlist)**  
Be the first to know when Mercury Node ships. First 100 nodes get dedicated onboarding support.

---

## License

MIT — use it, fork it, build on it.

---

*"We don't just run a Bitcoin node. We have an AI agent that lives inside it and works for us 24/7."*
