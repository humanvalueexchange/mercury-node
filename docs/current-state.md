# Mercury Node — Current Reference Deployment

**Snapshot date:** 2026-08-23  
**Host:** `mercury2`  
**Purpose:** Authoritative hardware and software snapshot of the currently operated Mercury node.

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
| Model context | 32,768 tokens (live snapshot; repository target is 8,192) |
| LLM threads | 4 (live snapshot; repository target is 2 pinned to cores 2-3) |
| Mercury model inventory | Qwen3.8-2B-Distill-Q4_K_M.gguf (active) |
| Mercury Hailo planner | `hailo-ollama` on `127.0.0.1:8000` (not installed at snapshot) |
| Extra service | `hve-lifeos.service` (retired; retained only as historical host state) |

The Hailo + CPU split is approved for repository implementation but is not
deployed by this snapshot. The checked-in Hailo unit is localhost-only and
requires separate package, model, and live-service approval.

The agent binds to localhost by default. If the authenticated backup endpoint is enabled,
`MERCURY_BACKUP_TOKEN` must be supplied through the root-readable
`/etc/mercury/agent.env` systemd environment file; the token is never stored in this
repository.

Static channel backups are stored under `/var/lib/mercury/backups` and are intended to be
owned by `lnd` with restrictive permissions.

All observed services were active at snapshot time:

```text
bitcoind  lnd  nbxplorer  btcpayserver  nginx
mercury-agent  mercury-llm  hve-lifeos
```

## Runtime state

- Bitcoin and Lightning services were synchronized to chain.
- Mercury Agent health endpoint returned `status: ok`.
- The node had no active or pending Lightning channels at snapshot time.
- Root filesystem usage was approximately 2%; blockchain storage usage was approximately 53%.
- Memory availability was approximately 9.1 GiB, with approximately 6.7 GiB reported in use.
- The node had been continuously up for approximately 34 days.

## Configuration drift from repository

The current host was deployed before the repository's installer was rebuilt and
may still differ in paths and optional services.

1. The live Bitcoin data directory is `/mnt/blockchain`; the installer defaults to
   `/var/lib/bitcoin` and supports `MERCURY_BITCOIN_DATADIR` for another volume.
2. The live host already includes optional NBXplorer, BTCPay, nginx, and llama.cpp
   services; the installer intentionally does not provision those components.
3. The installer uses verified Bitcoin Core 30.2 and LND 0.20.1-beta artifacts,
   while the live node may have locally customized configuration.

This snapshot is descriptive only. It does not contain wallet balances, seed material,
macaroons, passwords, private keys, or host network addresses.
