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
| Model context | 32,768 tokens |
| LLM threads | 4 |
| Mercury model inventory | Phi-3.5-mini, Qwen2.5-3B, Qwen3.8-2B, Qwen3.8-4B |
| Extra service | `hve-lifeos.service` |

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

The current host is not produced by the repository's installer as currently committed.

1. The live deployment uses `/opt/mercury`, while the installer references `/var/lib/mercury`
   and untracked `/usr/local/lib/mercury` staging paths.
2. The live node uses Hailo-10H and Qwen models; repository documentation and installer still
   describe Hailo-8L and Phi-3.5-mini as the primary stack.
3. The live Bitcoin data directory is `/mnt/blockchain`; the installer assumes `/var/lib/bitcoind`.
4. The live software versions are newer than the pinned installer versions.
5. The live `mercury-agent` is version 0.5.5; the repository source identifies itself as 0.3.0.
6. The repository's installer still contains skeleton steps for NBXplorer, BTCPay, systemd
   units, and deployment staging.

This snapshot is descriptive only. It does not contain wallet balances, seed material,
macaroons, passwords, private keys, or host network addresses.
