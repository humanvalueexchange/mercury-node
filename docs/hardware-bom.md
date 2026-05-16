# Mercury Node — Hardware Bill of Materials

**Version:** 1.0  
**Last updated:** 2026-05-16  
**Estimated total cost:** ~$250–320 USD

---

## Required Components

| # | Component | Spec | Est. Price | Where to Buy |
|---|---|---|---|---|
| 1 | **Raspberry Pi 5** | **16GB RAM** ⚠️ (8GB not supported) | $80 | raspberrypi.com, Adafruit, Pimoroni |
| 2 | **Hailo-8L AI Hat** | M.2 2242 form factor | $70 | hailo.ai, Seeed Studio |
| 3 | **NVMe SSD** | 2TB M.2 2242 NVMe (1TB minimum) | $80–120 | Samsung, WD, Kingston |
| 4 | **Pi 5 M.2 NVMe Hat+** | Official Raspberry Pi M.2 Hat+ | $12 | raspberrypi.com |
| 5 | **Power Supply** | 27W USB-C (official Pi 5 PSU) | $12 | raspberrypi.com |
| 6 | **microSD Card** | 32GB+ Class 10 / A2 (OS only) | $8 | Samsung, SanDisk |

---

## Recommended Accessories

| Component | Purpose | Est. Price |
|---|---|---|
| Pi 5 case with active cooling | Thermal management (24/7 operation) | $15–25 |
| Ethernet cable | Wired LAN preferred over WiFi | $5 |
| UPS (small) | Power outage protection | $30–50 |

---

## Important Notes

### ⚠️ Must use Pi 5 16GB
The 8GB variant does not have sufficient RAM for the full Mercury Node stack under load. Bitcoin Core + LND + BTCPay + NBXplorer + Mercury Agent requires approximately 6-8GB at peak. Only the **16GB model** is supported.

### NVMe form factor
The official Pi 5 M.2 Hat+ supports **M.2 2242 and 2280** drives. Verify your NVMe SSD is one of these form factors. Most laptop SSDs are 2280 — both are compatible.

### Hailo-8L Hat stacking
The Hailo-8L M.2 Hat and NVMe M.2 Hat+ can be stacked using the official Pi 5 stacking headers. Both connect via the Pi 5's PCIe FFC connector — only one can use it at a time. Use the **Hailo AI Kit** which includes an M.2 HAT+ board that accepts both the Hailo module and an NVMe drive.

**Recommended purchase:** Raspberry Pi AI Kit (includes Hailo-8L + M.2 Hat+) — simplifies stacking.

### Power requirements
The 27W official Pi 5 PSU is required for stable operation with NVMe + Hailo active. Standard 5V/3A supplies will undervolt and cause instability.

---

## Full Build Cost Breakdown

| Scenario | Components | Cost |
|---|---|---|
| **Minimum** | Pi 5 16GB + basic NVMe (1TB) + Hailo + Hat+ + PSU + microSD | ~$250 |
| **Recommended** | Above + 2TB NVMe + active cooling case + Ethernet | ~$300 |
| **Full kit + UPS** | Above + UPS | ~$340 |

---

## Software (all free, open-source)

| Software | License |
|---|---|
| Mercury Node | MIT |
| Bitcoin Core | MIT |
| LND | MIT |
| BTCPay Server | MIT |
| NBXplorer | MIT |
| Phi-3.5-mini | MIT |
| Raspberry Pi OS | Various open-source |

---

## Assembly Guide

See [docs/hardware-assembly.md](hardware-assembly.md) for step-by-step photos and assembly instructions.

---

## Where to Buy (Recommended Sources)

| Source | Ships to | Notes |
|---|---|---|
| raspberrypi.com | Worldwide | Official Pi 5, M.2 Hat+, AI Kit, PSU |
| hailo.ai | Worldwide | Official Hailo-8L products |
| seeedstudio.com | Worldwide | Hailo modules + Pi accessories |
| adafruit.com | US + intl | Pi 5, accessories, good tutorials |
| pimoroni.com | UK + intl | Pi 5, great for EU buyers |
| amazon.com | Worldwide | NVMe SSDs, microSD, cases |
