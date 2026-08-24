# Mercury Node Hardware BOM

**Status:** Live reference hardware
**Snapshot:** 2026-08-23

This document describes the currently operated node, not a guaranteed retail
kit or a claim that `install.sh` can reproduce it. Exact prices and vendors
vary; storage, cooling, power, and backup choices should be sized for 24/7
Bitcoin operation.

## Observed reference system

| Component | Reference specification |
|---|---|
| Host | Raspberry Pi 5-class ARM64 system |
| CPU | 4-core ARM Cortex-A76 |
| Memory | 16 GiB RAM |
| OS | Debian GNU/Linux 13 (trixie), `aarch64` |
| Root storage | 1.9 TB ext4 mounted at `/` |
| Blockchain storage | 1.8 TB ext4 volume mounted at `/mnt/blockchain` |
| Boot storage | 512 MB FAT boot partition |
| AI accelerator | Hailo-10H PCIe co-processor |
| Hailo firmware | 5.1.1 observed on the snapshot host |
| Swap | 2 GiB zram observed |
| Cooling | Active cooling is recommended for continuous load |
| Network | Wired Ethernet is preferred |

The active local model is `Qwen3.8-2B-Distill-Q4_K_M.gguf`, served by native
`llama.cpp`. The Hailo-10H is part of the reference hardware; the old Hailo-8L
and Phi-3.5-mini BOM is obsolete.

## Procurement guidance

For a new build, target:

| Item | Guidance |
|---|---|
| ARM64 host | Raspberry Pi 5-class board with 16 GiB RAM and supported PCIe |
| AI accelerator | Hailo-10H-compatible PCIe hardware and current firmware |
| Storage | At least 2 TB fast NVMe-class storage; separate blockchain volume is preferred |
| Power | Official or equivalent supply with adequate sustained headroom |
| Cooling | Active heatsink/fan solution rated for 24/7 operation |
| Network | Stable wired Ethernet |
| Power protection | UPS or clean shutdown capability |
| Backup media | Offline, encrypted media for static channel backups and configuration |

The Bitcoin chain grows, and model/tooling upgrades consume space. Do not size
the disk from the historical 500 GB installer minimum.

## Software and storage contract

| Workload | Live location |
|---|---|
| Bitcoin Core 30.2.0 data/config | `/mnt/blockchain/bitcoin` |
| LND 0.20.1-beta data | `/var/lib/lnd` |
| Mercury agent | `/opt/mercury/agent` |
| llama.cpp binaries/libraries | `/opt/mercury/llama.cpp` |
| Qwen model files | `/opt/mercury/models` |
| Static channel backups | `/var/lib/mercury/backups` |

NBXplorer and BTCPay Server are installed under `/opt/nbxplorer` and
`/opt/btcpayserver` on the reference host. They are supporting services, not
replacements for Bitcoin Core or LND.

## Thermal and maintenance notes

The snapshot host was approximately 67.75 °C and reported a non-zero historical
throttling flag. Check thermals, power, cooling, and bootloader status during a
maintenance window before relying on the node for uninterrupted service.

Monitor capacity and health with:

```bash
df -h
free -h
nvidia-smi                 # only where an NVIDIA device is present
htop
sudo systemctl status bitcoind lnd mercury-agent mercury-llm
```

`nvidia-smi` is not expected to report the Pi/Hailo accelerator; it is included
only for mixed or attached operator systems.

## Historical assumptions removed

The following are not requirements for the current contract:

- Hailo-8L AI Hat
- Phi-3.5-mini model
- 8 GB memory as a supported target
- a single 500 GB root-disk minimum
- the installer’s `/var/lib/bitcoind` and `/var/lib/mercury` layout

See [docs/current-state.md](current-state.md) for the complete dated snapshot
and [docs/architecture.md](architecture.md) for runtime relationships.
