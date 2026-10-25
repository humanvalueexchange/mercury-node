# x402 Watch UAT and Deployment Gate

This is the implementation runbook for the local candidate in
`humanvalueexchange/mercury-node`. It does not authorize a host installation,
service creation, repository creation, GitHub write, or timer enablement.

## Current state

- Application code, offline tests, and disabled systemd templates are in this
  repository.
- PR #7 was merged into `main` on 2026-10-25. A user-space UAT copy was staged
  at `/home/hermes/x402-watch-uat`; it is not a system installation or service.
- PR #8, which hardens the Hailo worker, is merged into `main`.
  All 73 offline tests and Ruff checks passed; tests use local fixtures and
  make no external API requests.
- In the isolated UAT copy, `check-models` passed on 2026-10-25 for CPU Qwen3
  at 32,768-token context and Hailo Qwen2.5-1.5B. The synthetic CPU check took
  12.7 seconds and the Hailo check took 10.1 seconds. These are smoke-test
  timings, not sustained throughput or thermal measurements.
- The Hailo check exposed runtime integration requirements: HailoRT needs a
  writable app-scoped `HOME`, rejects zero temperature even with greedy
  decoding, and emits a terminal token plus punctuation around its label. The
  follow-up worker now uses app-scoped state and strictly parses one of the
  allowed relevance labels. Hailo tags remain advisory and cannot discard
  sources.
- The user downloaded the Qwen3-4B Q4_K_M GGUF, `llama.cpp` v0.7.0 source,
  Python wheels, and HailoRT 5.1.1-compatible Qwen2.5-1.5B HEF into
  `/home/hermes/downloads`.
- A CPU-only `llama.cpp` build completed under
  `/home/hermes/downloads/x402-watch-llama-v0.7.0`; it was not installed
  globally. The build used native ARM optimization, OpenMP, and three jobs.
  CMake also fetched the static `llama-ui` asset from Hugging Face after its
  `b0` checksum URL failed and its `latest` fallback passed archive
  verification. This was a build-time UI asset, not a model or inference
  service; the tested server runs with `--no-ui`. The build is therefore not
  fully offline or reproducible from the source archive alone.
- A short synthetic CPU test initialized the 32,768-token context with one
  sequence, three threads, and zero GPU layers. With warm file cache, the
  server became healthy in 11 seconds; a 23-token prompt ran at 16.23 tokens/s
  and six JSON output tokens at 5.03 tokens/s. `MemAvailable` changed from
  15.21 GiB before loading to 8.23 GiB while loaded; temperature changed from
  56.8 C to 64.5 C. These are short smoke-test results, not sustained or
  full-context measurements.
- Qwen3's default thinking mode returned empty message content after 128
  generated tokens, with output in the reasoning channel. Setting
  `chat_template_kwargs.enable_thinking=false` returned valid JSON; the
  application now sets this option for draft requests.
- A protected local copy of the Brave key is provisioned; the private
  `HansHWestphal/x402-watch` repository and its scoped GitHub App are not
  provisioned.
- The first approved live dry run exceeded the original 240-second model
  timeout. After PR #9 was merged, a run completed synthesis in about 21
  minutes but failed editorial validation because a claim cited evidence held
  for human review; PR #10 exposed the fixed policy reason, and PR #11 now
  excludes routed sources from claim synthesis while retaining them for review.
- The approved 2026-10-25 UAT run after PR #11 completed local Qwen3 synthesis
  in about 11 minutes, but coverage was incomplete: all lane searches
  succeeded, while four source fetches failed across stablecoin/card-volume
  and Stripe/OpenRouter. Hailo triage also failed; CPU synthesis continued.
  A private baseline draft was written locally but not published. The run
  record contained only lane and exception type, so the fetch cause could not
  be determined. This follow-up records fixed fetch-failure categories and
  HTTP status codes without embedding URLs, response text, or credentials in
  diagnostics.
- The 2026-10-25 retry after PR #12 (run
  `b4240405a6f84706a435ccd70bea2099`) again completed all Brave searches but
  had three fetch failures: one stablecoin/card-volume HTTP 403, plus one
  Stripe/OpenRouter HTTP 403 and one response over the 2,000,000-byte cap.
  Hailo triage failed, while CPU synthesis continued for about 19 minutes.
  Editorial validation rejected a claim with an unknown source ID; the retry
  created no new brief and did not publish. This follow-up constrains generated
  citation IDs to supplied claimable evidence and includes sanitized run
  diagnostics in rejection errors. It does not relax fetch limits or bypass
  HTTP 403 responses.
- No recurring job or GitHub publication is enabled. Publication remains
  blocked until the private target repository and scoped credentials are
  provisioned and separately approved.
- The timer's `06:00` local-time schedule is a placeholder and must be approved
  or changed before enabling.
- The staged service hides common external-mount roots (`/mnt`, `/media`,
  `/run/media`, and `/srv`), but the actual Bitcoin/Lightning mount path is
  unverified. This is not proof of isolation; do not install the service until
  Hans confirms the mount path and the sandbox blocks it without reading its
  contents.
- The Hailo worker runs as a child of the service and shares its UID. The
  minimal child environment is not a hard credential/filesystem boundary;
  separate identity and network isolation remain deployment hardening gates.

## UAT sequence

1. **Review staged code on `main` and any follow-up branch.** Run the repository
   tests and lint before any Pi installation. Tests use local fakes and do not
   contact Brave, GitHub, or source websites.
2. **Use an isolated application prefix.** Before creating `/opt/x402-watch`,
   check only whether that exact destination already exists. If it exists,
   stop and ask; do not inspect or overwrite it. Do not use `/opt/mercury`,
   existing Mercury service directories, or the external Bitcoin/Lightning
   volume.
3. **Build `llama.cpp` from the downloaded archive.** Use a dedicated
   x402-watch source/build directory and a stock-clock CPU build with native
   ARM optimizations, OpenMP, and the server target. Limit compilation to
   three jobs to leave headroom for the Pi. Do not install system-wide or
   enable GPU offload.
4. **Install Python dependencies into an isolated venv.** Use
   `requirements-x402-watch.txt` and the downloaded wheel directory with
   `pip --no-index`; do not change global Python packages. Confirm compatible
   HailoRT/Python bindings during the approved proof-of-fit; do not install or
   replace the system Hailo runtime without separate approval. Install the
   matching Chromium build with `python -m playwright install chromium` in the
   same venv; this browser download is separate from the Python wheel install.
5. **Place model artifacts under the isolated prefix.** The expected names are
   `Qwen3-4B-Q4_K_M.gguf` and
   `Qwen2.5-1.5B-Instruct-v5.1.1.hef`. Verify hashes and file sizes before
   use; do not load artifacts from a shared Mercury model directory.
6. **Run `check-models`.** This performs a short local CPU inference and an
   advisory Hailo classification using synthetic text. It makes no Brave or
   GitHub request and writes no brief. Record model load time, inference time,
   peak memory, and temperature at stock settings. A Hailo failure is a
   blocker to Hailo acceptance but must not trigger runtime replacement.
7. **Review a live dry run only after the Brave credential is provisioned.**
   It searches the four approved lanes and retrieves public pages with
   Playwright Chromium, fresh non-persistent browser contexts, URL checks on
   browser requests, redirect and request-count limits, and a rendered-document
   size limit; that limit does not cap total subresource transfer. Chromium
   performs its own DNS resolution, so this is not equivalent to the previous
   socket-level IP pinning; verify network egress restrictions against private,
   reserved, and link-local ranges before any recurring run. The dry run
   creates a local private brief and does not
   publish unless `--publish` is explicitly provided and the environment gate
   is enabled. Only the current local date is accepted; backdated briefs are
   rejected. The first complete run is a baseline, not a no-change claim.
   Review source-site terms and robots rules before enabling recurring
   retrieval; the fetcher does not automate robots.txt checks or per-domain
   pacing.
8. **Keep the GitHub gate closed until separate approval.** Create the target
   repository as private, install an App on that repository only, grant
   Contents write permission only, provision its private key via systemd
   credentials, and verify repository privacy. Then review the local brief
   before approving the first `--publish` operation.
9. **Enable scheduling only after UAT acceptance.** Confirm the external
   Bitcoin/Lightning volume's mount path without accessing its contents, add
   that path to the service's inaccessible paths, and verify the service
   namespace cannot see it. Review Hailo device access, select the local run
   time, install the service files, and enable the timer only after explicit
   approval. The provided timer is not enabled.

## Local command contracts

The application CLI is available as:

```text
PYTHONPATH=src python -m x402_watch.cli check-models [--skip-hailo]
PYTHONPATH=src python -m x402_watch.cli run [--date YYYY-MM-DD] [--cpu-only] [--publish]
PYTHONPATH=src python -m x402_watch.cli retry-publish --confirm-publish
```

`run` is a local dry run by default. Live publication requires both the
explicit command flag and `X402_WATCH_PUBLISH_ENABLED=true`. A retry command
only considers previously validated outbox entries that were explicitly
staged for publication; ordinary dry-run briefs are not eligible.
The optional `--date` must match the current local date; historical and
future-dated runs are rejected.

## Acceptance gates

- All offline tests and Ruff checks pass.
- CPU inference uses the downloaded Q4_K_M model at native 32K context, one
  sequence, three CPU threads, zero GPU layers, `--no-ui`, and
  `chat_template_kwargs.enable_thinking=false`; the JSON response is parsed
  into the strict draft schema. Draft requests retain the 2,600-token output
  budget and have a bounded 2,400-second timeout for CPU-only synthesis.
- Model prompts omit full URLs, bound source fields, and reject evidence packets
  above 20,000 serialized characters; summaries are deterministic, not model
  generated.
- Hailo inference loads the HEF under HailoRT 5.1.1 and returns a valid tag
  without affecting whether a candidate is retained.
- A failed Brave query or page fetch prevents a no-material-change claim.
- Local run diagnostics expose fixed source-fetch failure categories (and HTTP
  status codes when available) without embedding URLs or response text in
  diagnostic entries.
- Local draft generation constrains claim and held-item citations to supplied
  claimable source IDs; with no claimable evidence, the model schema permits no
  generated items. Editorial validation remains fail-closed.
- Rejected-draft CLI errors include the run ID and sanitized diagnostics, never
  source URLs, response text, or credentials.
- A first complete run is marked as a baseline; no-change is allowed only on a
  later complete run.
- Factual claims with unknown citations, unapproved future-year proposals,
  unsupported BlackRock attribution, or routed GENIUS Act sources are rejected
  or held.
- Same-day retries update `briefs/YYYY-MM-DD.md` idempotently.
- Dry runs remain local; the GitHub publisher refuses non-private repositories
  and verifies an installation token scoped to this repository with
  `contents:write` (and GitHub's metadata-read permission only).
- The source fetcher pins each connection to a validated public IP, rejects
  compressed responses, and caps total response bytes and request duration.
- Publisher terms/robots restrictions are reviewed before recurring
  retrieval; automated robots checks and per-domain pacing are not yet
  implemented.
- A newer validated brief for the same date supersedes an older pending
  publication retry, preventing stale content from overwriting the current
  daily file.
- The systemd unit remains uninstalled and the timer disabled until separate
  deployment and publication approval.
