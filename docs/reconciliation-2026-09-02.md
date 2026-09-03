# Mercury Node Live Reconciliation

**Date:** 2026-09-02  
**Host:** `mercury2`  
**Repository baseline:** `main` at `29aeb5f5c1c9b5999d130a5ec9b8ba7552c9812c`  
**Method:** Read-only SSH checks and public repository comparison

## Scope and handling

This report reconciles the public Mercury repository with the live reference
host. It intentionally excludes wallet balances, transaction contents,
credentials, wallet seeds, macaroons, environment-file contents, private
databases, and private logs.

The checked-in repository and live deployment are not the same filesystem.
The deployed `/opt/mercury` tree is not a Git worktree, so application source
identity was checked by SHA-256 rather than by deployed Git commit.

## Live facts observed

| Area | Live evidence |
|---|---|
| Host | `mercury2`, Debian GNU/Linux 13, `aarch64`, remote user `hermes` |
| CPU/memory | 4 CPUs; 15 GiB RAM; 11 GiB available at capture |
| Storage | Root 2% used; blockchain volume 53% used |
| Uptime | Approximately 6 weeks, 2 days |
| Bitcoin Core | `v30.2.0`; main chain; height 965239; headers equal blocks; IBD false |
| LND | `0.20.1-beta`; chain and graph synchronized; height 965239 |
| Lightning channels | 0 active; 0 pending |
| Mercury Agent | Active; health `ok`; version `0.5.5`; localhost `127.0.0.1:8088` |
| Mercury LLM | Active; health `ok`; localhost `127.0.0.1:8089` |
| Local model | Qwen3.8-2B-Distill-Q4_K_M via native llama.cpp |
| Hailo | Hailo-10H PCIe device present |
| Supporting services | `nbxplorer`, `btcpayserver`, and `nginx` active |

## Listener reconciliation

The live host listens on:

- `127.0.0.1:8088` — Mercury Agent;
- `127.0.0.1:8089` — Mercury LLM;
- `127.0.0.1:8332` — Bitcoin RPC;
- public-facing `8333` — Bitcoin P2P;
- `*:9735` — Lightning peer transport;
- `*:80` and `*:443` — nginx.

The repository correctly documents localhost binding for the agent, LLM, and
Bitcoin RPC, but did not clearly present the full listener split. The
architecture, current-state, and security documents now state the distinction.

## Service reconciliation

All of the following were active during the check:

```text
bitcoind
lnd
nbxplorer
btcpayserver
nginx
mercury-agent
mercury-llm
hve-lifeos
```

The live `mercury-agent.service` unit matches the checked-in unit by SHA-256.
The deployed `main.py` also matches the checked-in `src/agent/main.py` by
SHA-256.

The live `mercury-llm.service` unit differs from the checked-in unit in its
description and the placement of its start-limit controls: the live
description says `Qwen3.8-4B`, while the executable model path is the
documented Qwen3.8-2B model. The checked-in unit already uses the correct 2B
description and places the start-limit controls at the unit level. The live
LLM unit also runs as `root`, which is a hardening risk requiring a separate
change and validation effort.

## Capability reconciliation

The live `/api/tools` catalog exposes six confirmation-gated operation names:

- `payment.pay`;
- `channel.open`;
- `channel.close`;
- `channel.rebalance`;
- `routing.fees.set`;
- `magma.buy`.

The repository correctly documents the prepare/execute boundary and the
explicit Mercury CLI confirmation requirement. The registry refactor remains
partial: not all CLI operations are registry-backed, and no checked-in MCP
server or public registry exists.

## Documentation findings and updates

### Correct and retained

- Debian 13 ARM64 Raspberry Pi-class host;
- Hailo-10H reference hardware;
- Bitcoin Core 30.2.0;
- LND 0.20.1-beta;
- Mercury Agent 0.5.5;
- native llama.cpp with Qwen3.8-2B;
- `/opt/mercury` application layout;
- localhost-only Agent and LLM endpoints;
- active supporting services;
- no checked-in MCP or public registry;
- explicit human confirmation for value-affecting operations.

### Updated

- current-state runtime facts, chain height, synchronization, capacity,
  memory, storage, and uptime;
- full listener split and public node/web exposure;
- architecture API route list for tool discovery, preparation, and execution;
- security guidance for public listeners and the live LLM privilege gap;
- roadmap reconciliation status and the LLM hardening follow-up;
- README pointer to the latest live reconciliation.

### Not asserted

- Wallet balances or funds;
- channel or payment contents;
- credential or environment-file state;
- temperature, firmware, bootloader, or throttling status beyond the older
  2026-08-23 hardware snapshot;
- firewall rule correctness;
- TLS certificate validity;
- remote reverse-proxy authentication;
- backup freshness or restore success;
- deployed Git commit identity for the `/opt/mercury` tree.

## Required follow-up

1. Evaluate a dedicated unprivileged account for `mercury-llm.service`.
2. Reconcile the live LLM unit description and start-limit placement during a
   controlled maintenance window.
3. Verify firewall policy for Bitcoin P2P, Lightning peer transport, and nginx.
4. Complete registry coverage and explicit permissions for all
   value-affecting CLI operations before any agent integration.
5. Keep the CFO integration localhost-only and read/prepare-only until its
   separate promotion gate passes.

## Post-reconciliation retirement action

The initial 21:24 EDT snapshot found `hve-lifeos.service` active, but outside
the supported Mercury architecture. After the snapshot, the service was
stopped and disabled over SSH. No HVE-LIFE-OS files or code were deleted.

The current Mercury contract now excludes HVE-LIFE-OS and the Hermes framework.
The Mercury CLI, Mercury Agent, and native llama.cpp service remain the
canonical Bitcoin, Lightning, and local-AI control plane.

No wallet, credential, or supported Mercury service was changed during the
retirement action.
