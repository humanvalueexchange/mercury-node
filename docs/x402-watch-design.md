# Mercury x402 Watch: Local Research and Publishing Design

- **Status:** Proposed; not implemented
- **Date:** 2026-10-24
- **Implementation repository:** `humanvalueexchange/mercury-node`
- **Brief repository:** `HansHWestphal/x402-watch` (target, private, not yet
  created)

## 1. Purpose and boundaries

Design a Pi-orchestrated daily pipeline that searches public sources, gathers
evidence, drafts a cited private research brief, and publishes one dated
Markdown file for Hans. The brief is an internal research product, not a
public HVE social post.

Implementation code belongs in `mercury-node`; dated briefs belong in the
separate `x402-watch` repository. This design does not make either repository
an authority to access Bitcoin or Lightning data.

The design uses the supplied hardware profile: Raspberry Pi 5 Model B Rev 1.1,
ARM64, four Cortex-A76 cores, 16 GB RAM, Hailo-10H PCIe accelerator, and
internal storage. The Hailo board's exact memory, the installed OS/runtime
versions, power supply, and cooling are not assumed. No live host software
inventory is part of this design.

### Goals

- Keep orchestration, source processing, inference, state, scheduling, drafting,
  and publishing under Pi control.
- Use Brave Search for discovery and GitHub for publishing; use public source
  pages as read-only evidence.
- Run all LLM inference on the Pi. Do not use hosted LLMs, remote GPUs, hosted
  embeddings, or a remote database.
- Keep the worker unprivileged and unable to access Bitcoin/Lightning data or
  the external Bitcoin data volume.
- Preserve source provenance and require citations for factual claims.
- Publish a dated private brief even when the verified result is “no material
  change.”

### Out of scope

- Public social posting or automatically publishing HVE voice content. Hans
  must review public HVE content before publication.
- Financial participation, the 2028 agent-mandate proposal, the 2029 local-first
  series, or the 2030 position decision.
- Operating on Bitcoin, Lightning, wallet, payment, or blockchain data.
- Installing, replacing, or inspecting Mercury's current software before
  specific approval.

## 2. Model and hardware decision

Use two independent inference paths: CPU for synthesis and Hailo for bounded
short-text classification. They do not share weights or a KV cache, and this
design does not split one model across the CPU and Hailo.

| Role | Candidate | Capability and constraint |
|---|---|---|
| Main writer | Qwen3-4B Q4_K_M GGUF on ARM64 CPU via `llama.cpp` | Official Q4_K_M artifact is about 2.50 GB (2.33 GiB) and Apache-2.0 licensed. Qwen documents 32,768 tokens natively and YaRN extension to 131,072. Start at the native 32K context; enable YaRN only if measured evidence volume warrants it. |
| Short-text triage | Hailo-compiled Qwen3-1.7B-Instruct HEF via Hailo GenAI API | Hailo's model table reports a 2,048-token context and 4.78 generated tokens/s. Use it only for structured topic/relevance tags from titles and short snippets, not summaries, compression, legal/financial analysis, or factual claims. A generic GGUF is not a Hailo HEF. |

Qwen3-4B's context setting is a capacity limit, not a target prompt length.
The explicit 64K minimum applies if a Hermes Agent model or an auxiliary
compression model is selected. This design uses neither, so 64K is not a
system-wide requirement. The Hailo classifier is not a compression model; if
the requirement is later interpreted to cover every auxiliary LLM, the Hailo
LLM must not be used.

### Memory and throughput estimates

Qwen3-4B's configuration lists 36 layers, 8 KV heads, and a 128-wide head.
For one sequence, the approximate KV-cache calculation is:

```text
2 (K and V) x 36 layers x 8 KV heads x 128 dimensions
  x context tokens x bytes per value
```

At 65,536 tokens this is about 9 GiB with FP16 cache, or about 4.78 GiB with
Q8_0 cache (including block-scale overhead). At 32,768 tokens, each figure is
approximately half. Adding the 2.33 GiB Q4_K_M weights gives roughly 11.33 GiB
with FP16 cache or 7.11 GiB with Q8_0, before the OS and runtime buffers.
Q8_0 cache compatibility and answer quality must be tested; these are
estimates, not a deployment guarantee.

A public Pi 5 CPU benchmark reports about 4.52 generated tokens/s for
Qwen3-4B Q4 at a short prompt, not at a full 64K context. For planning only,
a fully populated 64K context may be around 0.5-1.5 generated tokens/s; no
verified benchmark for this exact Pi/context combination is available. Actual
performance depends on runtime, thermal conditions, cache type, and concurrent
load. Do not overclock; power and cooling are unverified.

Sources: [Qwen3-4B model card](https://huggingface.co/Qwen/Qwen3-4B),
[Qwen3-4B configuration](https://huggingface.co/Qwen/Qwen3-4B/raw/main/config.json),
[official Q4_K_M artifact](https://huggingface.co/Qwen/Qwen3-4B-GGUF/blob/main/Qwen3-4B-Q4_K_M.gguf),
[Hailo GenAI model table](https://github.com/hailo-ai/hailo_model_zoo_genai/blob/main/docs/MODELS.rst),
[Pi 5 CPU benchmark](https://drgnworks.com/log/pi5-llm-bench-notes/).

## 3. Software inventory

The following is the proposed runtime bill of materials. Exact versions and
compatibility must be established only through an approved implementation
step; no current package or service state is assumed.

| Layer | Required software |
|---|---|
| Base | 64-bit ARM Linux. Prefer a `systemd` timer and one-shot service if the selected OS supports them. Accurate system time is required for daily scheduling and retrieval timestamps. |
| Orchestration | Python 3.10 or later in an isolated virtual environment; `httpx` for HTTPS; `trafilatura` for article extraction; `pydantic` for structured-output validation. Use the Python standard library for JSON, hashing, date handling, and `sqlite3`. |
| CPU inference | ARM64 CPU build of `llama.cpp`, using an on-demand `llama-server` bound to loopback, and the Qwen3-4B Q4_K_M GGUF. Use one inference slot. Stop the process at the end of the run to release memory. |
| Hailo inference | Compatible Hailo-10H device support, HailoRT/PyHailoRT, the supported Python GenAI API (`hailo_platform.genai.LLM`), and the compatible Qwen3-1.7B HEF. Keep this worker separate and load the model once per run. The full audio/video application bundle and its audio dependencies are not needed. |
| Local state | SQLite on internal storage. Start without a vector store or embedding model; use canonical URLs, content hashes, and deterministic matching for deduplication. |
| GitHub publishing | GitHub App installed only on the private `x402-watch` repository, with repository Contents write permission and no administration or Actions permission. A small publisher process can use the GitHub REST contents API. Python JWT/cryptography support is needed if the publisher creates App installation tokens itself. |
| Secrets and logs | Systemd credentials if supported, otherwise protected local credential files. Use local journald or equivalent logs with secrets and source bodies redacted. |
| Test-only tools | `pytest` for offline fixture tests and `ruff` for linting. Cover parsing, deduplication, policy gates, Markdown validation, and retry/idempotency. These tools are not part of the runtime. |

Brave Search and GitHub are the service APIs. Fetching the public publisher
pages found by search is necessary for source evidence, but those pages are
never treated as compute services. If outbound access must be limited literally
to Brave and GitHub hostnames, source retrieval cannot work without an approved
publisher-host allowlist.

The Qwen GGUF is hosted on Hugging Face and the Hailo HEF is distributed by
Hailo. These are one-time static artifact sources, not runtime inference
services; obtain separate approval before downloading either artifact.

## 4. Component architecture

```text
systemd timer
    |
    v
daily orchestrator --------------------------- local SQLite state
    |                                                   ^
    +-- Brave Search --> candidate URLs                 |
    |                         |                         |
    |                         +-- CPU fetch/parse -------+
    |                         |
    |                         +-- Hailo short-text tags -+
    |                                                   |
    +-- curated evidence --> llama.cpp CPU writer -------+
                                  |
                                  v
                         policy/citation validator
                                  |
                                  v
                         dated Markdown outbox
                                  |
                                  v
                       scoped GitHub publisher
                                  |
                                  v
                 private HansHWestphal/x402-watch
```

### Process and credential separation

- **Collector/orchestrator:** has the Brave credential and HTTPS access needed
  for search and public source retrieval. It does not have the GitHub App key.
- **Hailo worker:** receives only short candidate text, has no API credentials
  or network tools, and returns structured tags through a bounded local queue.
- **CPU model worker:** receives curated evidence and returns structured draft
  data. It has no API credentials, browser, shell, or external network access.
- **Publisher:** reads only a validated brief and has GitHub access only. Use
  the GitHub App installation restricted to this one repository.

The service must run unprivileged. To guarantee that the Bitcoin/Lightning
volume is inaccessible, give the worker a private filesystem namespace with
only explicit application, model, and research-state mounts. Do not rely on
file permissions or `ProtectSystem=strict` alone to hide a mounted volume;
systemd documents limitations around mount propagation and submounts. Grant
the Hailo worker only the required Hailo device access. No firewall, mount,
network, or existing service changes are authorized by this document.

## 5. Local data and brief contract

SQLite is the durable local queue and audit record. Suggested logical records:

- `runs`: run ID, local brief date, start/end times, status, and coverage state.
- `queries`: watch lane, query, request time, result count, and success/error.
- `candidates`: result URL, title, snippet, canonical URL, duplicate group, and
  Hailo tags.
- `sources`: publisher, source type, stated publication time (nullable),
  retrieval time in UTC, final URL, content hash, and fetch status.
- `evidence`: source ID, short excerpt, and any stable location/section marker.
- `briefs` and `publish_outbox`: rendered Markdown, validation state, GitHub
  path, commit/retry status.

Retain source metadata, hashes, and short supporting excerpts rather than
archiving whole articles. A missing publication date is recorded as “not
stated,” never inferred by the model. The brief must distinguish publication
date from retrieval date.

Each factual claim in the generated brief carries one or more source IDs. The
validator checks that each ID resolves to a source record and that source
metadata is complete. It does not claim to prove factual entailment; source
quality and the excerpt-to-claim relationship remain explicit review concerns.

The output path is `briefs/YYYY-MM-DD.md`, with one file per local calendar day.
The private brief includes run/coverage status, material changes, why each
change matters, uncertainty, and a source table with URLs and dates. It is not
a social post.

## 6. Daily run flow

1. **Trigger and lock.** At the configured local time, the timer starts one
   run. The orchestrator records a run ID, takes a non-overlap lock, and checks
   whether that date already has a completed brief. A missed timer may trigger
   one current-date run on recovery; it must not fabricate backfilled briefs.
2. **Search.** Query the approved watch lanes: x402/ACP adoption; GENIUS Act
   implementation; stablecoin volume versus card-network volume; and
   Stripe/OpenRouter follow-through. Prefer primary sources and record every
   successful query and its result count.
3. **Deduplicate and parallelize.** Canonicalize URLs and deduplicate by URL
   and content hash. As results arrive, CPU-side fetching and parsing runs in
   parallel with Hailo classification of titles/snippets. Hailo labels are
   advisory and cannot discard a source on their own.
4. **Fetch and extract.** Fetch selected pages with bounded concurrency,
   timeouts, response-size limits, redirect revalidation, and checks against
   private/loopback destinations. Respect publisher terms and rate limits. Do
   not execute scripts. Extract article text and source dates; retain only
   metadata and short evidence excerpts.
5. **Compare with history.** Compare source hashes, official announcements,
   and tracked metrics with prior local records. A “no material change”
   conclusion is allowed only if all configured lanes were searched
   successfully. Otherwise mark coverage incomplete.
6. **Build evidence packet.** Rank evidence by primary-source status,
   relevance, freshness, and materiality. Keep source IDs attached to each
   excerpt. Code-based rules flag financial/legal/tax topics for review; the
   Hailo model does not decide whether those rules apply.
7. **Draft on the CPU.** The local Qwen3-4B model generates structured
   claims, uncertainty, and “why it matters” text from the evidence packet.
   Keep inputs within the native 32K context initially. If a run exceeds that
   budget, split by watch lane and use the same CPU model for the resulting
   structured synthesis; do not add a smaller compression model.
8. **Apply editorial gates.** Validate source IDs, dates, Markdown structure,
   and topic-specific rules before rendering. Hold financial, legal, or tax
   interpretation for hve-cfo/Brian; do not let the model publish advice.
9. **Render and publish.** If the full search found no material development,
   render an explicit “No material change” brief. If coverage failed, render
   an explicit coverage-gap status, not a no-change claim. The publisher
   writes the validated file to the private GitHub repository. A retry updates
   the same date’s path rather than making a duplicate.
10. **Record outcome.** Persist success, coverage gaps, validation errors, or
    GitHub retry status locally. Logs contain operational metadata, not API
    keys, full prompts, or full source bodies.

The daily run is a batch job, not an interactive chat service. The actual run
time, model thread count, queue limits, and CPU/Hailo overlap are set only after
an approved proof-of-fit. Maximize useful parallel work, not constant hardware
utilization.

## 7. Editorial policy

The content scope follows the
[approved HVE decision](https://github.com/HansHWestphal/hve-knowledge-and-operations/blob/main/agent-communications/2026-10-22-hve-machine-native-economy-content-series-approval-v1.0.md):

- The 2027 “The Machine-Native Economy, Human-Centered” series is 4–6
  household-facing HVE-voice posts, centered on human mandates and consent over
  machine autonomy and KYA as human agency at scale. Daily briefs support
  research; they do not draft or publish those public posts.
- Describe relevant BlackRock figures as “analyst estimates, per BlackRock
  (Sept. 2026),” not as proprietary BlackRock data or established fact.
- Treat x402, ACP, AP2, TAP, MCP, and A2A as topics to monitor, not commitments.
- Education/opinion only; no investment advice.
- Route financial, legal, and tax matters to hve-cfo/Brian before related
  analysis proceeds. Until routed, mark the item as held and omit
  interpretation.
- Do not include the unapproved 2028 proposal, 2029 series, 2030 decision, or
  financial participation.

## 8. Failure behavior and acceptance criteria

| Condition | Required behavior |
|---|---|
| Brave unavailable or a lane has no successful query | Mark coverage incomplete; do not claim no material change. |
| A source is inaccessible or has no publication date | Record fetch status or “not stated”; do not invent a date. |
| Hailo unavailable or incompatible | Continue CPU-only if the run remains valid; record the missing triage step. Do not install or replace Hailo software automatically. |
| CPU model unavailable, over memory budget, or emits invalid citations | Do not publish generated claims. Record a failure or a clearly labeled incomplete status. |
| Financial/legal/tax analysis is implicated | Hold that item's interpretation for hve-cfo/Brian. |
| GitHub write fails | Keep the validated brief in the local outbox and retry idempotently; never report a successful publish without a confirmed API result. |

Before enabling a daily timer, an approved pilot must demonstrate:

- CPU synthesis at the selected context without destabilizing other workloads;
- memory, temperature, and throughput measurements at stock hardware settings;
- Hailo model-load and short-classification success with the compatible HEF;
- citation and editorial validators rejecting invalid fixtures;
- deterministic same-day retry behavior; and
- no filesystem visibility to Bitcoin/Lightning data or the external volume.

## 9. Approval gates

This document does not authorize deployment. Proceed in separate approved
stages:

1. Approve a bounded CPU/Hailo proof-of-fit and the official static model
   artifact sources. Schedule it in a safe window; no existing service or
   package inventory, overclock, Bitcoin-volume access, or network changes.
2. Review results, then separately approve any software installation, Hailo
   runtime changes, service identity, filesystem namespace, or timer creation.
   If a possible conflict with existing software appears, stop and ask rather
   than inspect it.
3. Provision the Brave key locally and approve creation/configuration of the
   initially private `HansHWestphal/x402-watch` repository and its
   repository-scoped publisher identity.
4. Validate a local dry run, then separately approve the first GitHub write and
   recurring private publication.

No Mercury host commands, model downloads, installations, service changes,
credential provisioning, repository creation, or brief publication have been
performed as part of this design.

## 10. Technical references

- [Hailo GenAI model table](https://github.com/hailo-ai/hailo_model_zoo_genai/blob/main/docs/MODELS.rst)
- [Hailo GenAI applications and runtime prerequisites](https://github.com/hailo-ai/hailo-apps/tree/main/hailo_apps/python/gen_ai_apps)
- [Hailo GenAI development guide](https://github.com/hailo-ai/hailo-apps/blob/main/.hailo/instructions/gen-ai-development.md)
- [Qwen3-4B model card and context guidance](https://huggingface.co/Qwen/Qwen3-4B)
- [`llama.cpp` server options](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [systemd timer documentation](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)
- [systemd filesystem isolation documentation](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
- [GitHub App permissions](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app)
- [GitHub repository contents API](https://docs.github.com/en/rest/repos/contents#create-or-update-file-contents)
- [Pi 5 Qwen3-4B CPU benchmark](https://drgnworks.com/log/pi5-llm-bench-notes/)
