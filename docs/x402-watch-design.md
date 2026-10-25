# Mercury x402 Watch: Local Research and Publishing Design

- **Status:** Implementation candidate; local Pi proof-of-fit and UAT remain
  pending. No recurring timer or GitHub publication is enabled.
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
| Short-text triage | Hailo-compiled Qwen2.5-1.5B-Instruct HEF via the installed Hailo GenAI API | The Hailo v5.1.1 model table lists this HEF with a 2,048-token context, 8.45-second load, 0.37-second time to first token, and 6.95 generated tokens/s. Use it only for advisory topic/relevance tags from titles and short snippets, not summaries, compression, legal/financial analysis, or factual claims. A generic GGUF is not a Hailo HEF. |

Qwen3-4B's context setting is a capacity limit, not a target prompt length.
The 64K minimum applies to Hermes Agent models and auxiliary compression
models. This design uses neither: the CPU writer uses Qwen3-4B at its native
32K context, while the Hailo model is a bounded classifier, not a compression
model. Qwen2.5-1.5B's native model card lists 32K, but its Hailo-compiled HEF
is limited to 2,048 tokens.

### Memory and throughput estimates

Qwen3-4B's configuration lists 36 layers, 8 KV heads, and a 128-wide head.
For one sequence, the approximate KV-cache calculation is:

```text
2 (K and V) x 36 layers x 8 KV heads x 128 dimensions
  x context tokens x bytes per value
```

At 65,536 tokens this is about 9 GiB with FP16 cache, or about 4.78 GiB with
Q8_0 cache (including block-scale overhead). At the selected 32,768-token
context, each figure is approximately half. Adding the 2.33 GiB Q4_K_M weights
gives roughly 6.83 GiB with FP16 cache or 4.72 GiB with Q8_0, before the OS,
server buffers, and other workloads. Q8_0 cache compatibility and answer
quality must be tested; these are estimates, not a deployment guarantee.
The 64K FP16 configuration would approach 11.33 GiB for weights plus KV cache
alone, leaving little headroom on a 16 GB Pi once the OS and other processes
are included; it is not selected.

A Pi proof-of-fit built the downloaded `llama.cpp` v0.7.0 source for ARM64 with
native CPU optimization, OpenMP, and three build jobs. In a short synthetic
test, `llama-server` loaded Qwen3-4B with a 32,768-token context, one sequence,
three CPU threads, zero GPU layers, and its UI disabled. The warm-cache
server-to-health time was 11 seconds; a 23-token prompt was processed at
16.23 tokens/s and six JSON output tokens at 5.03 tokens/s. `MemAvailable`
fell from about 15.21 GiB to 8.23 GiB while the model was loaded, and
temperature rose from 56.8 C to 64.5 C during the short request. These are
smoke-test measurements, not a full-context prompt, sustained daily-run, or
cold-start benchmark. Hailo memory and inference remain unverified. Do not
overclock; power and cooling are unverified.

Sources: [Qwen3-4B model card](https://huggingface.co/Qwen/Qwen3-4B),
[Qwen3-4B configuration](https://huggingface.co/Qwen/Qwen3-4B/raw/main/config.json),
[official Q4_K_M artifact](https://huggingface.co/Qwen/Qwen3-4B-GGUF/blob/main/Qwen3-4B-Q4_K_M.gguf),
[Hailo v5.1.1 GenAI model table](https://github.com/hailo-ai/hailo_model_zoo_genai/blob/v5.1.1/docs/MODELS.rst),
[Hailo Qwen2.5 model page](https://hailo.ai/products/hailo-software/model-explorer/generative-ai/qwen2-5-1-5b/),
[Qwen2.5-1.5B model card](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct),
[Pi 5 CPU benchmark](https://drgnworks.com/log/pi5-llm-bench-notes/).

## 3. Software inventory

The following is the selected implementation candidate. The Pi's approved
hardware profile is the only host information assumed here. The OS, Python
runtime, SQLite version, systemd availability, Hailo bindings, and build
toolchain must be verified only during an approved, narrowly scoped proof of
fit. No Mercury software inventory is part of this design.

| Layer | Required software |
|---|---|
| Base | 64-bit ARM Linux. Prefer a `systemd` timer and one-shot service if the selected OS supports them. Accurate system time is required for daily scheduling and retrieval timestamps. |
| Orchestration | Python 3.13 in an isolated virtual environment; pinned `httpx`, `playwright`, `trafilatura`, `pydantic`, `PyJWT`, and `cryptography` requirements are in `requirements-x402-watch.txt`. Brave, model, and GitHub API clients use `httpx`; public source pages are retrieved with Playwright Chromium. JSON, hashing, dates, file locking, and SQLite use the standard library. |
| CPU inference | ARM64 CPU build of `llama.cpp` v0.7.0 from the user-downloaded source archive; a short-lived `llama-server` binds to `127.0.0.1:8090`. Configure one sequence, three CPU threads, native 32K context, zero GPU layers, and `--no-ui`; send `chat_template_kwargs.enable_thinking=false` so Qwen3 returns the JSON draft instead of spending a short output budget in its reasoning channel. Stop the server after synthesis. |
| Hailo inference | A compatible HailoRT/PyHailoRT 5.1.1 runtime and `hailo_platform.genai.LLM` with the Hailo v5.1.1 Qwen2.5-1.5B-Instruct HEF. Runtime compatibility, model load, and inference require the approved on-device proof-of-fit; do not install or replace system Hailo software without separate approval. The full audio/video application bundle is not needed. |
| Local state | SQLite on internal storage, a private local outbox, same-day idempotent repository path, and a non-overlap file lock. No vector store or hosted embeddings; deduplication uses canonical URLs and content hashes. |
| GitHub publishing | A GitHub App is requested for only `HansHWestphal/x402-watch`, with a per-repository installation token and Contents write permission. The publisher verifies that the target repository is private before writing. No repository or credentials have been provisioned. |
| Secrets and logs | The staged systemd unit uses systemd credentials. API keys are read at runtime and are not placed in source, prompts, or child-process environments; operational errors do not include secret values or source bodies. Service files are not installed or enabled. |
| Test-only tools | Pinned `pytest` and `ruff` development requirements; offline `unittest` contracts cover source URL safety, citations, routing, baselines, and same-day history. |

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
    |                         +-- Playwright fetch/parse+
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

- **Collector/orchestrator:** reads the Brave credential from the systemd
  credential directory and uses HTTPS for Brave and Playwright for public
  source retrieval. Browser contexts are fresh per page, downloads and service
  workers are disabled, non-GET requests and private destinations are blocked,
  and no custom user-agent or stealth settings are applied. The browser process
  receives a minimal environment without credential-directory variables.
- **Hailo worker:** runs as a separate short-lived process, receives only a
  bounded title/snippet over stdin, and is started with a minimal environment
  that omits systemd credential paths. Its `HOME` is an app-scoped writable
  directory under the data directory so HailoRT can initialize its local state.
  Its tags are advisory; it cannot discard evidence. Worker failures return a
  bounded stage, exception type, and sanitized detail through the protocol so
  the run can explain an unavailable triage path without recording evidence
  text or credentials. It currently shares the service UID, so omitting the
  credential path from its environment is not a hard filesystem or credential
  boundary.
  A separate OS identity/network sandbox remains a deployment hardening item
  and is not yet verified.
- **CPU model worker:** `llama-server` is short-lived, binds only to loopback,
  receives the curated JSON evidence packet, and is started with a minimal
  environment. It has no browser or shell integration. It shares the service
  UID, and external network isolation at the process level has not been
  verified.
- **Publisher:** only runs when explicitly requested, obtains a GitHub App
  installation token restricted to the one target repository and
  `contents:write`, and checks repository visibility before writing. No timer
  invokes it until a separate UAT approval.

The service must run unprivileged. To guarantee that the Bitcoin/Lightning
volume is inaccessible, give the worker a private filesystem namespace with
only explicit application, model, and research-state mounts. Do not rely on
file permissions or `ProtectSystem=strict` alone to hide a mounted volume;
systemd documents limitations around mount propagation and submounts. Grant
the Hailo worker only the required Hailo device access. No firewall, mount,
network, or existing service changes are authorized by this document.

## 5. Local data and brief contract

SQLite is the durable local queue and audit record. The implementation uses:

- `runs`: run ID, local brief date, start/end times, status, and coverage state.
- `queries`: watch lane, query, request time, result count, and success/error.
- `sources`: publisher, lane, stated publication time (nullable), retrieval
  time in UTC, final URL, content hash, short excerpt, Hailo tag, and whether
  the content is new, changed, or unchanged against the last complete run.
- `briefs` and `publish_outbox`: rendered Markdown, validation state, GitHub
  path, commit/retry status.

Retain source metadata, hashes, and short supporting excerpts rather than
archiving whole articles. A missing publication date is recorded as “not
stated,” never inferred by the model. The brief must distinguish publication
date from retrieval date.

Each factual claim in the generated brief carries one or more source IDs. The
validator checks that each ID resolves to an excerpt supplied to the writer,
rejects unsupported IDs, routes GENIUS Act and other flagged financial/legal/
tax sources for human review, and disallows a “no material change” result on a
baseline or incomplete run. It does not prove entailment; source quality and
the excerpt-to-claim relationship remain review concerns.

The output path is `briefs/YYYY-MM-DD.md`, with one file per local calendar day.
The private brief includes run/coverage status, material changes, why each
change matters, uncertainty, and a source table with URLs and dates. It is not
a social post.

## 6. Daily run flow

1. **Trigger and lock.** At the configured local time, the timer starts one
   run. The orchestrator records a run ID and takes a non-overlap file lock.
   Re-running a date updates the same local and GitHub path; it does not create
   a second dated file. A missed timer may trigger one current-date run on
   recovery; it must not fabricate backfilled briefs.
2. **Search.** Query the approved watch lanes: x402/ACP adoption; GENIUS Act
   implementation; stablecoin volume versus card-network volume; and
   Stripe/OpenRouter follow-through. Prefer primary sources and record every
   successful query and its result count.
3. **Deduplicate and parallelize.** Canonicalize URLs and deduplicate URLs
   before fetching; deduplicate extracted content hashes for the synthesis
   packet while retaining all source records in the private source table. CPU
   fetching/parsing runs with bounded concurrency while the Hailo child
   classifies titles/snippets. Hailo labels are advisory and cannot discard a
   source on their own.
4. **Fetch and extract.** Fetch selected pages with bounded concurrency,
   timeouts, response-size limits, and redirect revalidation. Resolve each
   hostname once per request, reject non-public answers, and pin the connection
   to the validated IP while preserving the original Host header and TLS SNI.
   Reject compressed responses to avoid decompression-bomb exposure. Do not
   execute scripts. Follow publisher terms and robots rules as a deployment
   requirement; the current fetcher does not implement a robots.txt parser or
   per-domain delay. Extract article text and source dates; retain only
   metadata and short evidence excerpts.
5. **Compare with history.** Compare source hashes with the last complete
   local run. The first complete run is marked as a baseline, not as “no
   material change.” That conclusion is allowed only after a prior complete
   run and successful search/fetch coverage of all lanes. Otherwise mark
   coverage incomplete.
6. **Build evidence packet.** Rank evidence by primary-source status,
   change history, advisory Hailo relevance, and lane priority. Keep source IDs
   attached to each excerpt. The model receives bounded title/publisher/date
   fields and at most 400 excerpt characters per source; full URLs are omitted
   from its prompt. Code-based rules flag financial/legal/tax topics for
   review; the Hailo model does not decide whether those rules apply.
7. **Draft on the CPU.** After source processing, the Hailo worker exits to
   release resources. The local Qwen3-4B model then generates structured
   claims, uncertainty, and “why it matters” text from the evidence packet.
   Keep inputs within the native 32K context. The serialized evidence packet
   has a 20,000-character ceiling; an oversized packet fails closed rather
   than being silently truncated, split, or sent to a hosted model. The
   OpenAI-compatible request disables Qwen3 thinking with
   `chat_template_kwargs.enable_thinking=false`; on Mercury, the default
   reasoning mode consumed a short output budget without returning message
   content, while non-thinking mode returned valid JSON.
8. **Apply editorial gates.** Validate source IDs, coverage/no-change
   consistency, attribution, human-routing rules, and safe Markdown rendering.
   The rendered summary is deterministic rather than model-written, so it
   cannot introduce uncited facts. Hold financial, legal, or tax interpretation
   for hve-cfo/Brian; do not let the model publish advice.
9. **Render and publish.** If the full search found no material development
   after a prior complete baseline, render an explicit “No material change”
   brief. A first run is labeled as a baseline. If coverage failed, render an
   explicit coverage-gap status, not a no-change claim. Local outbox generation
   is separate from GitHub publication; only an explicit `--publish` run or
   `retry-publish --confirm-publish` may write to the private repository. A
   retry updates the same date’s path rather than making a duplicate. A newer
   validated brief for that date supersedes any older pending outbox entry.
10. **Record outcome.** Persist success, coverage gaps, validation errors, or
    GitHub retry status locally. Application logs do not intentionally include
    credentials, full prompts, or full source bodies; review runtime logs during
    UAT before enabling persistent collection.

The daily run is a batch job, not an interactive chat service. It may create
only the current local date; backdated/future-date runs are rejected. The actual
run time, model thread count, queue limits, and CPU/Hailo overlap are set only
after an approved proof-of-fit. Maximize useful parallel work, not constant
hardware utilization.

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
| Hailo unavailable or incompatible | Continue CPU-only if the run remains valid; record the sanitized worker stage, exception type, and detail. Do not install or replace Hailo software automatically. |
| CPU model unavailable, over memory budget, or emits invalid citations | Do not publish generated claims. Record a failure or a clearly labeled incomplete status. |
| Financial/legal/tax analysis is implicated | Hold that item's interpretation for hve-cfo/Brian. |
| GitHub write fails | Keep the validated brief in the local outbox and retry idempotently; never report a successful publish without a confirmed API result. |

Before enabling a daily timer, an approved pilot must demonstrate:

- CPU synthesis at the selected context without destabilizing other workloads;
- memory, temperature, and throughput measurements at stock hardware settings;
- Hailo model-load and short-classification success with the compatible HEF;
- citation and editorial validators rejecting invalid fixtures;
- the serialized local-model evidence packet staying within its 20,000-character
  budget and summaries remaining deterministic;
- deterministic same-day retry behavior; and
- no filesystem visibility to Bitcoin/Lightning data or the external volume.

## 9. Approval gates

PR #7 is merged to `main`. On 2026-10-25, the authorized bounded model check
passed in the user-space UAT copy at `/home/hermes/x402-watch-uat`: Qwen3-4B
CPU inference at 32K context and Qwen2.5-1.5B Hailo inference both returned
success for synthetic input. The Hailo check used local follow-up code on
`luna/x402-watch-hailo-home-fix`; those changes are not yet in `main` or pushed.
No system package was installed, no systemd unit was installed or enabled, and
there has been no credential provisioning, target-repository creation, or
publication. The model check does not establish sustained thermal performance
or filesystem isolation.

Proceed in separate stages:

1. Review and separately approve pushing/opening a PR for the Hailo follow-up
   fixes; merge them before treating Hailo support as part of `main`.
2. Provision the Brave key locally in protected storage, then separately
   approve a live, non-publishing dry run. It will call Brave Search and fetch
   public source pages, writing only to the local UAT data directory.
3. Review the local brief. Separately approve creation of the initially private
   `HansHWestphal/x402-watch` repository and its repository-scoped publisher
   identity before any GitHub write.
4. Approve the first private publication only after reviewing the brief.
5. Before system installation or scheduling, confirm the external
   Bitcoin/Lightning mount path without accessing its contents, add that exact
   path to the service sandbox, verify it is invisible, review resource and
   Hailo-device isolation, and approve the service/timer and schedule. The
   staged `06:00` local-time schedule is only a placeholder.

Do not inventory unrelated host software, overclock, access the Bitcoin volume,
or change networking. If a possible conflict with existing software appears,
stop and ask rather than inspect it.

## 10. Technical references

- [Hailo v5.1.1 GenAI model table](https://github.com/hailo-ai/hailo_model_zoo_genai/blob/v5.1.1/docs/MODELS.rst)
- [Hailo GenAI applications and runtime prerequisites](https://github.com/hailo-ai/hailo-apps/tree/main/hailo_apps/python/gen_ai_apps)
- [Hailo GenAI development guide](https://github.com/hailo-ai/hailo-apps/blob/main/.hailo/instructions/gen-ai-development.md)
- [Qwen3-4B model card and context guidance](https://huggingface.co/Qwen/Qwen3-4B)
- [`llama.cpp` server options](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [systemd timer documentation](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)
- [systemd filesystem isolation documentation](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)
- [GitHub App permissions](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app)
- [GitHub repository contents API](https://docs.github.com/en/rest/repos/contents#create-or-update-file-contents)
- [Pi 5 Qwen3-4B CPU benchmark](https://drgnworks.com/log/pi5-llm-bench-notes/)
