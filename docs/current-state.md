# Mercury Node — Current Reference Deployment

**Hardware snapshot:** 2026-08-23
**Runtime reconciliation:** 2026-09-02
**Host:** `mercury2`
**Purpose:** Authoritative hardware and software snapshot of the currently operated Mercury node,
with the latest runtime facts recorded separately from older hardware observations.

This document describes the live reference deployment. It is intentionally separate from the
original target BOM and architecture documents so that historical design assumptions remain
traceable while operational documentation stays accurate.

## Hardware

| Component | Observed specification |
|---|---|
| Platform | Raspberry Pi 5-class ARM64 system |
| CPU | 4-core ARM Cortex-A76, 1 thread/core |
| Memory | 16 GiB RAM |
| Root storage | 1.9 TB ext4 device mounted at `/` |
| Blockchain storage | 1.8 TB ext4 `Extreme 55DD` device mounted at `/mnt/blockchain` |
| Boot storage | 512 MB FAT boot partition |
| AI accelerator | Hailo-10H PCIe co-processor |
| Hailo firmware | 5.1.1 |
| Temperature at snapshot | 67.75 °C |
| Swap | 2 GiB zram swap |

The system reported a non-zero historical throttling flag and an available Raspberry Pi
bootloader update at snapshot time. These should be reviewed during a planned maintenance
window before applying firmware changes.

## Operating system

| Component | Version |
|---|---|
| Distribution | Debian GNU/Linux 13 (trixie) |
| Kernel | `6.12.47+rpt-rpi-2712` |
| Architecture | `aarch64` / ARM64 |
| Python | 3.13.5 |

## Bitcoin and Lightning software

| Service | Version / deployment |
|---|---|
| Bitcoin Core | 30.2.0 |
| Bitcoin data/config | `/mnt/blockchain/bitcoin` |
| LND | 0.20.1-beta |
| LND data | `/var/lib/lnd` |
| NBXplorer | `/opt/nbxplorer/NBXplorer.dll` |
| BTCPay Server | `/opt/btcpayserver/BTCPayServer.dll` |
| .NET runtime | `/usr/local/dotnet/dotnet` |
| Reverse proxy | nginx |

Bitcoin Core runs as user `bitcoin`; LND runs as user `lnd`; NBXplorer and BTCPay run as
user `btcpay`. LND is configured with an automated wallet-unlock password file under
`/var/lib/lnd`.

## Mercury software

| Service | Current deployment |
|---|---|
| Mercury Agent | `/opt/mercury/agent/main.py`, API on port `8088` |
| Mercury Agent version | 0.5.5 |
| Mercury LLM | native llama.cpp `llama-server` |
| LLM endpoint | `127.0.0.1:8089` |
| Active model | `Qwen3.8-2B-Distill-Q4_K_M.gguf` |
| Model context | 32,768 tokens |
| LLM threads | 4 |
| Mercury model inventory | Qwen3.8-2B-Distill-Q4_K_M.gguf (active) |
| Extra service | `hve-lifeos.service` |

The agent binds to localhost by default. If the authenticated backup endpoint is enabled,
`MERCURY_BACKUP_TOKEN` must be supplied through the root-readable
`/etc/mercury/agent.env` systemd environment file; the token is never stored in this
repository.

Static channel backups are stored under `/var/lib/mercury/backups` and are intended to be
owned by `lnd` with restrictive permissions.

All observed services were active during the 2026-09-02 reconciliation:

```text
bitcoind  lnd  nbxplorer  btcpayserver  nginx
mercury-agent  mercury-llm  hve-lifeos
```

## Runtime state

The following non-sensitive runtime facts were collected over SSH on
2026-09-02 at 21:24 EDT:

- Bitcoin Core was on `main`, at block height `965239`, with `blocks == headers`
  and initial block download disabled.
- LND reported chain and graph synchronization complete at block height
  `965239`.
- LND reported zero active and zero pending channels.
- Mercury Agent health returned `status: ok`, version `0.5.5`.
- Mercury LLM health returned `status: ok`.
- Root filesystem usage was 2%; blockchain storage usage was 53%.
- The host reported 15 GiB total memory, 4.4 GiB used, 11 GiB available, and
  1.7 GiB of 2 GiB swap used.
- Host uptime was approximately 6 weeks and 2 days.

## Network exposure

The live host currently binds:

- Mercury Agent on `127.0.0.1:8088`;
- Mercury LLM on `127.0.0.1:8089`;
- Bitcoin RPC on `127.0.0.1:8332`;
- Bitcoin P2P on public-facing IPv4/IPv6 port `8333`;
- Lightning peer transport on `*:9735`;
- nginx on `*:80` and `*:443`.

The public-facing Bitcoin and Lightning listeners are distinct from the
localhost-only Mercury AI services. Firewall, reverse-proxy, and authenticated
route configuration must be reviewed before any remote CFO integration.

## Configuration drift from repository

The current host was deployed before the repository's installer was rebuilt and
may still differ in paths and optional services.

1. The live Bitcoin data directory is `/mnt/blockchain`; the installer defaults to
   `/var/lib/bitcoin` and supports `MERCURY_BITCOIN_DATADIR` for another volume.
2. The live host already includes optional NBXplorer, BTCPay, nginx, and llama.cpp
   services; the installer intentionally does not provision those components.
3. The installer uses verified Bitcoin Core 30.2 and LND 0.20.1-beta artifacts,
   while the live node may have locally customized configuration.
4. The live `mercury-llm.service` unit currently describes itself as
   `Qwen3.8-4B`, while its configured and running model is
   `Qwen3.8-2B-Distill-Q4_K_M.gguf`. The checked-in unit file already uses the
   correct 2B description, so this is live-unit drift rather than repository
   source drift.
5. The live LLM service runs as `root`. Its endpoint is localhost-only, but the
   privilege level is a hardening risk and is not required by the model server
   contract.

This snapshot is descriptive only. It does not contain wallet balances, seed material,
macaroons, passwords, private keys, or host network addresses.
