# Mercury Node — Roadmap

**Vision:** The world's simplest AI-first Bitcoin Lightning node.  
**Public launch target:** Q3 2026

---

## Release Plan

### v0.1 — Foundation
*Target: Week 3 (June 6, 2026)*

The Bitcoin stack, fully automated.

- [ ] `install.sh` — 5-phase installer with hardware detection
- [ ] Hailo-8L driver installation and pinning
- [ ] Bitcoin Core (native ARM64, mainnet)
- [ ] LND (native ARM64, auto-unlock)
- [ ] NBXplorer + BTCPay Server
- [ ] nginx reverse proxy
- [ ] Wallet seed ceremony (interactive, secure)
- [ ] Systemd service units for all 5 services
- [ ] `--snapshot` flag for fast IBD
- [ ] `--verify` flag for checksum audit
- [ ] Basic `mercury status` command (shell script)

**Success criteria:** Fresh Pi 5 → fully operational Bitcoin+Lightning node in one command.

---

### v0.2 — CLI Agent
*Target: Week 5 (June 20, 2026)*

Mercury gets a voice.

- [ ] `mercury-agent` FastAPI service (systemd managed)
- [ ] `mercury` CLI binary (`/usr/local/bin/mercury`)
- [ ] `mercury status` — full node health (LND + bitcoind + services)
- [ ] `mercury channels` — channel list with balance percentages
- [ ] `mercury invoices [--last N]` — recent payment history
- [ ] `mercury sync` — IBD / sync progress bar
- [ ] `mercury logs [service]` — live log tail
- [ ] `mercury backup` — static channel backup export
- [ ] Telegram alert on payment received
- [ ] Daily health digest (cron, 06:30)
- [ ] LND readonly macaroon scoping (agent never has wallet write access)

**Success criteria:** `mercury status` returns clean output in <1 second. Payment received fires Telegram within 5 seconds.

---

### v0.3 — Intelligence
*Target: Week 7 (July 4, 2026)*

Mercury gets a brain.

- [ ] Phi-3.5-mini model download in installer
- [ ] `hailo_inference.py` — llama.cpp + Hailo-8L backend
- [ ] `context_builder.py` — live node state injected into system prompt
- [ ] `mercury ask "<question>"` — natural language node queries
- [ ] Response latency target: <3 seconds on Hailo
- [ ] Graceful fallback if Hailo unavailable (CPU inference, slower)
- [ ] Context types: channel health, payment history, routing, balance, general BTC

**Success criteria:** `mercury ask "how are my channels?"` returns accurate, actionable response in <3 seconds.

---

### v0.4 — MCP Server
*Target: Week 9 (July 18, 2026)*

Mercury joins the mesh.

- [ ] MCP server at `/mcp/` endpoint
- [ ] Agent card at `/.well-known/agent.json`
- [ ] mDNS discovery (`_mercury._tcp.local`)
- [ ] Lightning payment-gated API (100 mSat/call)
- [ ] Preimage-based auth (pay → get token → query)
- [ ] `/mcp/query` endpoint (read-only node data)
- [ ] Peer agent discovery via LND custom messages
- [ ] `mercury peers` — list discovered Mercury peer agents

**Success criteria:** Two Mercury nodes on same LAN discover each other via mDNS. Payment-gated query succeeds end-to-end.

---

### v1.0 — Public Launch
*Target: Week 12 (August 8, 2026)*

Mercury is ready for the world.

- [ ] All v0.x milestones complete and stable
- [ ] Agent-to-agent Lightning query working across internet (not just LAN)
- [ ] Mercury Registry opt-in (registry.mercury-node.dev)
- [ ] `mercury update` — self-update command
- [ ] Full test suite (install smoke test, CLI tests, agent API tests)
- [ ] Complete documentation (README, architecture, BOM with photos, troubleshooting)
- [ ] SECURITY.md and responsible disclosure policy
- [ ] GitHub repo made public
- [ ] Launch announcement

**Success criteria:** A technically competent person can go from zero to running Mercury Node in under 10 minutes of active work (excluding IBD sync time).

---

## Future Milestones (Post-v1.0)

### v1.1 — Hailo-8L Intelligence Expansion
- Anomaly detection model (unusual payment patterns, channel drain)
- Fee prediction model (optimize routing revenue)
- `mercury forecast` — next 24h routing fee prediction

### v1.2 — Mercury Mobile Companion
- iOS/Android app for `mercury status` and payment alerts
- QR code invoice generation
- Push notifications via self-hosted ntfy or Telegram

### v2.0 — Mercury Network
- Full Lightning-native AI mesh (thousands of nodes)
- Agent knowledge sharing (routing intelligence propagates through network)
- Mercury DAO (node operators earn governance via routing volume)

---

## Design Principles (non-negotiable across all versions)

1. **Sovereignty first.** The Bitcoin stack works identically with or without the agent.
2. **Closest to metal.** Native binaries only. No Docker. No Snap.
3. **Agent is a guest.** `mercury-agent` crashes alone. Never affects funds.
4. **Honest UX.** IBD takes 72 hours. We say so clearly.
5. **Open source is the only option.** Audit everything. MIT license.
