# Mercury Node Architecture Boundary

Mercury is a standalone Bitcoin, Lightning, and local-AI appliance. The
Mercury CLI is its canonical control plane; Bitcoin Core and LND remain the
authoritative money layer. Mercury must remain operational if the local AI
processes, HVE-CFO, Hermes, or the DGX Spark are unavailable.

The approved local reasoning path uses `hailo-ollama` on
`127.0.0.1:8000` for a short plan and native `llama-server` on
`127.0.0.1:8089` for CPU drafting and merging. Both engines are advisory.
They do not execute `/api/tools/{name}/execute`, pay invoices, move funds,
open or close channels, set fees, or buy Magma. Existing human confirmation
gates remain authoritative.

HVE-LIFE-OS is retired, stopped, disabled, and retained only as code/files; it
must not be re-enabled. HVE-CFO runs on the DGX Spark and may integrate with
Mercury only through a future narrow authenticated adapter. No remote fallback
or public inference listener is enabled by default.
