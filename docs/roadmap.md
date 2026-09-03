# Mercury Node Roadmap

**Status:** Current plan, aligned to the live reference deployment
**Updated:** 2026-08-23

The live reference node is ahead of the original v0.1 design, but the
repository's installer and documentation still contain historical assumptions.
Roadmap items below distinguish shipped repository capabilities from planned
work; unchecked items are not promises of the current installer.

## Current baseline

- [x] Debian 13 (trixie), ARM64 Raspberry Pi 5-class reference host
- [x] Hailo-10H reference hardware
- [x] Bitcoin Core 30.2.0 and LND 0.20.1-beta in the live deployment
- [x] Mercury Agent 0.5.5 with FastAPI telemetry and Magma routes
- [x] Native llama.cpp `llama-server` with Qwen3.8-2B-Distill
- [x] `/opt/mercury` live application layout
- [x] Operational CLI for status, health, sync, channels, invoices, payments,
  routing, backups, logs, AI queries, channel operations, and diagnostics
- [x] Backup endpoint token check and restrictive backup file permissions
- [x] Implement approved Hailo + CPU split reasoning path on the controlled
  repository branch, including bounded snapshots, deterministic status
  fast-paths, deadline-aware fallbacks, Hailo readiness/prewarm units, and
  schema validation
- [ ] Validate and promote the split path on the live host; service enablement,
  model/runtime changes, and promotion gates require separate approval

Hailo-8L, Phi-3.5-mini, and the old Hailo-specific inference path are retired
claims. They are not current milestones.

## Near-term repository work

### Installer reconciliation

- [x] Pin verified Bitcoin Core 30.2 and LND 0.20.1-beta artifacts.
- [x] Deploy the Mercury application into `/opt/mercury` with the CLI package.
- [x] Add protected configuration handling, preflight checks, and real
  checksum verification.
- [x] Remove unsupported snapshot and optional-component claims.
- [ ] Add separately reviewed BTCPay Server, NBXplorer, nginx, llama.cpp, and
  model provisioning.
- [ ] Add upgrade/rollback support and a production wallet migration guide.

### Registry refactor

- [x] Introduce typed `ToolSpec`, `Permission`, and `ToolRegistry`.
- [x] Register `node.status` as a read-only tool.
- [x] Test duplicate registration, lookup, and confirmation enforcement.
- [ ] Register the remaining CLI operations.
- [ ] Assign explicit permission policies to all fund-moving and administrative
  commands.
- [ ] Add input schemas and a stable listing/introspection interface.
- [ ] Decide whether agent API handlers should share registry metadata.

The registry is currently a partial refactor, not a complete authorization
boundary.

### Local AI split status

The repository implementation is complete through the offline validation and
documentation phase on the controlled `luna/mercury-hailo-cpu-split` branch.
The CPU draft and merge path retains the approved native llama-server contract;
merge is optional only when the 12-second global deadline cannot accommodate
it. Three closed snapshot-only status cases may bypass inference when their
required fresh fields are present. Live Hailo residency, warm latency, soak,
thermal, zram, and money-layer regression gates remain open.

### Operational hardening

- [ ] Add deployment documentation for the observed systemd units and
  `/etc/mercury/agent.env`.
- [ ] Document and test authenticated reverse-proxy exposure, if remote API
  access is needed.
- [ ] Add backup restore drills and monitoring for stale static channel backups.
- [ ] Add compatibility checks for Bitcoin Core, LND, llama.cpp, and model
  upgrades on ARM64.

## Future capabilities

These remain proposals and are not present in the current source:

- [ ] MCP server and agent-card endpoint
- [ ] Authenticated, payment-gated agent-to-agent API
- [ ] Peer discovery over Lightning gossip or mDNS
- [ ] Opt-in public Mercury Registry
- [ ] Automatic agent-to-agent Lightning payments
- [ ] Mobile companion and push notification product
- [ ] Anomaly detection, fee forecasting, and routing optimization models

Any future mesh or registry work must preserve the current security boundary:
the AI layer must not gain autonomous authority to move funds, and a node must
remain usable without a public directory or cloud service.

## Design principles

1. **Sovereignty first:** keys and wallet control stay with the operator.
2. **Money layer isolation:** Bitcoin Core and LND must continue to work if
   Mercury fails.
3. **Local by default:** telemetry and inference bind to localhost unless an
   explicitly secured deployment requires otherwise.
4. **Human approval for value transfer:** recommendations may be automated;
   payments, channel changes, and purchases require operator approval.
5. **Honest documentation:** live behavior, installer behavior, and future
   designs are labeled separately.
