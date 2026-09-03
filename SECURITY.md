# Security Policy

Mercury Node can operate a real Bitcoin wallet. Treat the host, wallet seed,
LND credentials, environment files, and static channel backups as sensitive.
This repository is under active development; audit the exact deployment before
using production funds.

## Supported versions

| Version | Support status |
|---|---|
| Current repository/live deployment | Best-effort development support |
| Older v0.x designs | Not supported |

The 2026-09-02 live reconciliation confirms Bitcoin Core 30.2.0,
LND 0.20.1-beta, Mercury Agent 0.5.5, and Qwen3.8-2B through native
llama.cpp. Hailo-8L,
Phi-3.5-mini, MCP mesh, and public registry claims describe obsolete or
unimplemented designs.

The Hermes framework and HVE-LIFE-OS are not Mercury dependencies. HVE-LIFE-OS
was retired from the host on 2026-09-02; its files may remain for historical
purposes, but its service must stay disabled.

## Reporting a vulnerability

Do **not** open a public GitHub issue for a vulnerability. Report privately to
**security@hvecorp.com** with:

- a description and affected component;
- reproducible steps or a minimal proof of concept;
- impact, especially whether funds, wallet recovery material, or node control
  can be affected;
- suggested mitigation, if available.

Please avoid accessing or modifying data that is not yours. We will acknowledge
reports within 24 hours and prioritize critical issues for an emergency fix.

## Threat model

The security priorities are:

1. **Key safety:** the wallet seed must never enter the repository, logs, API
   responses, chat prompts, or third-party services.
2. **Fund safety:** AI recommendations are advisory. The agent has no intended
   autonomous payment loop; fund-moving CLI actions require an operator to
   invoke and approve them.
3. **Service isolation:** a failed Mercury agent must not stop Bitcoin Core or
   LND.
4. **Local exposure:** LND RPC, the agent API, and the llama.cpp endpoint bind
   to localhost by default.
5. **Credential protection:** LND credentials, the wallet-unlock password file,
   `MERCURY_BACKUP_TOKEN`, and `MAGMA_API_KEY` must be root/operator secrets.

This is not a claim that a compromised host is safe. The agent runs as `lnd`
because it invokes `lncli` against `/var/lib/lnd`; host compromise or theft of
the LND account, wallet files, seed, or secrets remains a fund-risk scenario.

## API security

The FastAPI agent defaults to `127.0.0.1:8088`; the local LLM defaults to
`127.0.0.1:8089`; Bitcoin RPC is `127.0.0.1:8332`. Do not expose these
services directly to the Internet.

The live node intentionally exposes Bitcoin P2P on port `8333`, Lightning peer
transport on port `9735`, and nginx on ports `80` and `443`. These listeners
must be governed by host firewall, protocol, and authenticated reverse-proxy
policy. Public web exposure does not authenticate the Mercury API.

- Telemetry GET routes expose node status, balances, channel information,
  invoices, peers, routing, and payment history to any client that can reach
  the bound service.
- `POST /api/backup` is disabled unless `MERCURY_BACKUP_TOKEN` is configured
  and supplied as `X-Mercury-Backup-Token`.
- `POST /api/magma/buy` requires `MAGMA_API_KEY`. It creates a remote Amboss
  order and returns a Lightning invoice; it does not pay the invoice.
- CORS origins are opt-in through `MERCURY_CORS_ORIGINS`; an allowed origin is
  not an authentication mechanism.

If remote access is required, put the service behind an authenticated,
encrypted reverse proxy or private network and restrict the exposed routes.

Mercury’s supported control plane is the local CLI, Agent, and llama.cpp
service. Do not add Hermes or HVE-LIFE-OS as an alternate control plane.

## Filesystem and service controls

The reference system stores application code and models under `/opt/mercury`,
Bitcoin data under `/mnt/blockchain/bitcoin`, LND data under `/var/lib/lnd`,
and backups under `/var/lib/mercury/backups`.

`mercury-agent.service` runs as `lnd` with `NoNewPrivileges=yes`,
`ProtectSystem=strict`, and explicit write paths limited to
`/var/lib/mercury` and `/var/lib/lnd`. The agent unit is restartable and does
not own the Bitcoin or LND service lifecycle.

The live `mercury-llm.service` currently runs as `root`. Although it is
localhost-bound, this is a privilege-reduction gap. A future hardening change
should evaluate a dedicated unprivileged service account and verify model,
library, and socket permissions before deployment.

## Static channel backups

Static channel backups are recovery material, not ordinary logs:

- directory: `/var/lib/mercury/backups`, mode `0700`;
- files: timestamped `channels-*.bak`, mode `0600`, owned for LND access;
- HTTP export: disabled unless `MERCURY_BACKUP_TOKEN` is set;
- off-device copies: encrypt them and use controlled, offline-capable media;
- wallet seed: store separately; an SCB does not replace the seed.

Verify backup freshness with `mercury backup` and perform recovery drills before
depending on a backup during an incident.

## Installer warning

The checked-in `install.sh` is a verified partial installer for Bitcoin Core,
LND, the Mercury agent, and the CLI. It preserves existing Bitcoin/LND
configuration, verifies published artifact checksums, installs the
`/opt/mercury` layout, and refuses unsupported options or replacement of
unmanaged systemd units.

It does not install BTCPay Server, NBXplorer, nginx, llama.cpp, models, Hailo
drivers, or UTXO snapshots. Treat those components as separate deployment work
and independently review the installer before using it with production funds.
