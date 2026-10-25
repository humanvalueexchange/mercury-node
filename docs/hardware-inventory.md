# Hardware Inventory

- **Inventory label:** Raspberry Pi #1 - Mercury
- **Hostname:** `mercury2` (SSH alias `mercury`)
- **Verified:** 2026-10-24 by read-only host inspection

“Raspberry Pi #1” is the inventory label; the installed board is a Raspberry Pi 5,
not the original Raspberry Pi Model 1.

## Observed configuration

| Component | Observed configuration |
|---|---|
| Board | Raspberry Pi 5 Model B Rev 1.1 |
| SoC / CPU | BCM2712 platform; 4-core ARM Cortex-A76, 4 threads |
| Memory | 16 GB nominal; Linux reports 16,608,240 kB `MemTotal` |
| Operating system | Debian GNU/Linux 13.2 (trixie), `aarch64`; kernel `6.12.47+rpt-rpi-2712` |
| Internal storage | SD/MMC device `mmcblk0`, 1.9 TB, device name `SM02T`; ext4 root partition |
| Boot storage | 512 MB VFAT partition on `mmcblk0`, mounted at `/boot/firmware` |
| External data storage | SanDisk Extreme 55DD USB device, 1.8 TB, ext4 at `/dev/sda1`, mounted at `/mnt/blockchain` |
| AI accelerator | Hailo-10H PCIe, device `1e60:45c4` at `0001:01:00.0`; `/dev/hailo0` |
| Hailo software | Firmware 5.1.1; HailoRT CLI 5.1.1 |
| Active swap | 2 GiB zram at `/dev/zram0` |
| Network interfaces | Wired Ethernet (`eth0`), Wi-Fi (`wlan0`), and Tailscale (`tailscale0`) |

The SD/MMC device does not expose a retail manufacturer/model in the inspected
output beyond its device name. The power supply and installed cooling hardware
could not be identified through software inspection. No serial numbers, MAC
addresses, or private network addresses are recorded here.

## Capacity and health snapshot

| Resource | Observed at inspection |
|---|---|
| Root filesystem | 33 GB used, 1.8 TB available |
| External data filesystem | 935 GB used, 806 GB available |
| Boot filesystem | 78 MB used, 433 MB available |
| CPU temperature | 48.3 °C |
| Raspberry Pi throttling status | `0x0` |
| Hailo device | Identified and responding to HailoRT |

These capacity and temperature values are a dated snapshot, not guaranteed
capacity or thermal limits.

## Operational status

On 2026-10-24, `bitcoind`, `btcpayserver`, `nbxplorer`, and `lnd` were stopped
and disabled on Mercury as part of the Bitcoin/Lightning cutover. Existing
blockchain, wallet, and configuration data were left on disk. Pi-hole and
home-monitoring services are planned after Mercury moves to the new office and
are not installed or configured yet.
