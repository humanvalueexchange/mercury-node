# Mercury Node Hardware BOM

**Status:** Observed physical hardware and procurement reference
**Snapshot:** 2026-10-24
**Inventory record:** [Raspberry Pi #1 - Mercury](hardware-inventory.md)

This document records Mercury's observed physical hardware and procurement
guidance, not a guaranteed retail kit or a claim that `install.sh` can
reproduce it. Exact prices and vendors vary; storage, cooling, power, and
backup choices for a Bitcoin deployment should be sized for 24/7 operation.

## Observed reference system

| Component | Reference specification |
|---|---|
| Host / asset | `mercury2` (`mercury` SSH alias), inventory label Raspberry Pi #1 |
| Board | Raspberry Pi 5 Model B Rev 1.1 |
| CPU | 4-core ARM Cortex-A76 |
| Memory | 16 GB nominal RAM |
| OS | Debian GNU/Linux 13.2 (trixie), kernel `6.12.47+rpt-rpi-2712`, `aarch64` |
| Root storage | 1.9 TB SD/MMC device (`mmcblk0`, device name `SM02T`), ext4 mounted at `/` |
| Blockchain storage | SanDisk Extreme 55DD USB device, 1.8 TB ext4 mounted at `/mnt/blockchain` |
| Boot storage | 512 MB VFAT boot partition |
| AI accelerator | Hailo-10H PCIe co-processor (`1e60:45c4`, `/dev/hailo0`) |
| Hailo firmware / runtime | Firmware 5.1.1; HailoRT CLI 5.1.1 |
| Swap | 2 GiB active zram |
| Cooling | Installed hardware not verified; active cooling is recommended for continuous load |
| Network | Wired Ethernet and Wi-Fi; Tailscale interface also present |

At inspection, the root filesystem had 33 GB used and 1.8 TB available; the
external data filesystem had 935 GB used and 806 GB available. CPU temperature
was 48.3 °C and `vcgencmd get_throttled` returned `0x0`.

The approved local reasoning contract pairs `qwen2.5-instruct:1.5b` through
`hailo-ollama` on localhost with `Qwen3.8-2B-Distill-Q4_K_M.gguf` through native
`llama.cpp` for drafting and merging. The old Hailo-8L and Phi-3.5-mini BOM is
obsolete. The split is not deployed by the dated snapshot.

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

## Known software and storage locations

The Bitcoin/Lightning services on Mercury were stopped and disabled on
2026-10-24; the data directories were not deleted.

| Workload | Known location |
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

The 2026-10-24 snapshot was approximately 48.3 °C with no throttling flags
reported. The power supply and installed cooling hardware were not verified.
Recheck thermals, power, cooling, and bootloader status during a maintenance
window before relying on the node for uninterrupted service.

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

See [docs/hardware-inventory.md](hardware-inventory.md) for the asset record,
[docs/current-state.md](current-state.md) for the dated software snapshot, and
[docs/architecture.md](architecture.md) for runtime relationships.
