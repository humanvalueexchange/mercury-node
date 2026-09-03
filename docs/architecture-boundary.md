# Mercury Node Architecture Boundary

**Status:** Approved permanent boundary  
**Effective:** 2026-09-02

## Standalone Mercury contract

Mercury Node is a standalone Bitcoin, Lightning, and local-AI appliance. It
does not run the Hermes framework and does not run HVE-LIFE-OS.

The Mercury CLI is the canonical control plane for:

- Bitcoin Core operations;
- LND and Lightning operations;
- node health and synchronization;
- backups and diagnostics;
- local AI queries;
- preparation and confirmation of value-affecting operations.

The Mercury Agent and native llama.cpp service support the CLI locally. Bitcoin
Core and LND remain the money layer and must continue operating if Mercury AI,
HVE-CFO, Hermes, or the DGX Spark is unavailable.

## Retired HVE-LIFE-OS service

`hve-lifeos.service` was retired from the Mercury host on 2026-09-02. The
service was stopped and disabled; its files and code were retained and not
deleted. It is not part of the supported Mercury service inventory and must
not be re-enabled.

The historical reconciliation found the service active before retirement. That
observation is preserved in the dated reconciliation report and does not make
HVE-LIFE-OS a current Mercury capability.

## Hermes and HVE-CFO boundary

Hermes profiles belong on their approved hosts, not on the Mercury Pi.
HVE-CFO runs on the DGX Spark and may integrate with Mercury only through a
narrow authenticated adapter that exposes approved read and prepare operations.

HVE-CFO must not:

- install or run Hermes on Mercury;
- install or run HVE-LIFE-OS on Mercury;
- receive unrestricted shell access;
- receive wallet seeds, LND macaroons, or private keys;
- bypass Mercury's explicit execution confirmation boundary;
- make Mercury or the DGX Spark a prerequisite for Bitcoin or Lightning
  continuity.

Any future CFO-to-Mercury integration requires its own approved interface,
permission, evidence, promotion, and rollback records.
