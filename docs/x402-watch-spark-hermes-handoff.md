# x402 Watch: DGX Spark + Hermes Handoff

- **Status:** Use-case and UAT handoff. The active target is DGX Spark with
  Hermes in `humanvalueexchange/hve-librarian`. No Spark proof-of-fit or
  HVE-Librarian implementation is recorded here.
- **Date:** 2026-10-27
- **Purpose:** Preserve the research use case and the useful findings from the
  earlier Pi prototype before the implementation moves to its intended host.

## Platform and ownership decision

Mercury and the Raspberry Pi 5/Hailo-10H design are not the target for this
workload. Run the research workflow on the DGX Spark and integrate it with
Hermes through HVE-Librarian. Keep the Hermes runtime pure; put HVE-specific
behavior behind HVE-Librarian's adapter boundary. This handoff is kept in
`mercury-node` because that is where the prototype and its UAT record live.
Future Hermes integration code belongs in `humanvalueexchange/hve-librarian`.

The earlier design and UAT remain historical evidence, not Spark installation
instructions. Their Pi-specific CPU/Hailo choices, 32K context, paths, and
systemd templates must not be copied as the Spark deployment. This document
does not authorize host changes, credential migration, scheduling, repository
creation, or publication.

## Use case

Once per day, collect and compare public information about:

- x402 and adjacent agent-commerce protocol adoption;
- GENIUS Act implementation;
- stablecoin volume compared with card-network volume; and
- Stripe/OpenRouter follow-through.

The output is a private, dated research brief for human review, not a public
HVE post, investment advice, or an autonomous payment agent. Each factual claim
should link to source evidence and distinguish a source's publication date
from the workflow's retrieval date. The workflow must not access Bitcoin or
Lightning data, submit payments, or treat protocol monitoring as an HVE
commitment.

The intended pipeline is: search public sources, fetch and retain bounded
evidence, compare it with the last complete run, draft cited claims locally
through Hermes, validate the draft, and save a private brief. A first complete
run is a baseline. A failed search or fetch means coverage is incomplete; it
must never be reported as "no material change." Publication is a separate,
explicitly approved step.

The earlier proposal to publish into a private `HansHWestphal/x402-watch`
repository was not carried out. The final brief location and publication
mechanism remain open decisions.

## What the Pi prototype taught us

| Finding | Evidence from the earlier UAT | Implication for Spark/Hermes |
|---|---|---|
| Offline checks are not end-to-end acceptance. | The offline suite and Ruff checks passed at a prototype checkpoint, but tests used local fixtures and did not verify live source quality or publication. | Keep contract tests, then separately measure live-source coverage, usefulness, and citation quality in a non-publishing pilot. |
| The Pi CPU path was slow for a full run. | A short Qwen3-4B/32K smoke test measured about 16.2 prompt and 5.0 generated tokens/s. A later real run averaged about 1.75 generated tokens/s and took 11m22s for synthesis. | These are Pi-only measurements, not Spark estimates. Use the Spark's existing local inference path through Hermes and benchmark the actual model, context, and workload there. |
| Hailo was not a dependable requirement. | Synthetic Hailo inference initially passed, but later UAT reported Hailo failures and an unsupported relevance tag. Tags were advisory and could not discard sources. | Do not port the Hailo worker or make classification hardware a prerequisite. Start with the Spark/Hermes path and keep any triage optional. |
| Passing citation checks did not mean the brief was good. | In the latest recorded run, all four searches succeeded but only 9 of 18 results were fetched. The resulting 7 claims passed citation/policy validation, yet the source set was secondary and the claims were judged not editorially acceptable. | Source relevance and claim-to-source entailment need explicit human evaluation; source-ID validation alone is insufficient. |
| Fetching public sources was a major failure point. | UAT recorded HTTP 403s, unsafe-request rejections, and oversized responses. Playwright's Chromium resolves DNS itself, so URL prechecks were not proof of connection-level IP pinning. Robots checks and per-domain pacing were also not implemented. | Test source access and egress controls at the actual browser/network boundary. Respect publisher terms, robots rules, and pacing; keep failed coverage visible instead of relaxing limits silently. |
| Qwen3 needed an inference-specific setting for JSON output. | On the tested llama.cpp setup, default thinking mode used the output budget without returning message content; `chat_template_kwargs.enable_thinking=false` produced valid JSON. | If Qwen3 is selected on Spark, verify its Hermes/provider template behavior. Do not assume the old llama.cpp setting applies unchanged. |
| The old build was not fully offline/reproducible. | The llama.cpp build fetched a UI asset from Hugging Face after the checksum URL failed, even though the tested server ran with its UI disabled. | Do not reuse the Pi build as a production artifact; record and verify all model/runtime dependencies for the Spark path. |

The recorded Pi measurements, model checks, and generated brief establish no
Spark performance, isolation, source-coverage, or editorial-quality result.
The prototype did not publish a brief or enable a recurring job.

## Principles to carry forward

- Keep the workflow a bounded daily research batch, not an interactive agent
  with payment or chain access.
- Preserve source IDs, canonical URLs, hashes, publisher, and both publication
  and retrieval dates. Retain short evidence excerpts rather than whole
  articles where practical.
- Require citations for factual claims and reject unknown source IDs, but treat
  validation as a structural check, not proof that a source supports a claim.
- Allow "no material change" only after a prior complete baseline and complete
  search/fetch coverage. Label partial coverage plainly.
- Keep inference local to the Spark. Do not send prompts or source evidence to a
  hosted LLM, remote GPU, or hosted embedding service.
- Keep draft generation separate from any GitHub write. Review a local/private
  draft before enabling a publishing path.

## Target implementation constraints

1. Use the existing Spark-local model service supported by Hermes; do not
   recreate the Pi's CPU-only llama.cpp and Hailo stack by default. Verify the
   actual model/provider route is local.
2. Hermes Agent models and any auxiliary compression model must meet the
   established minimum context window of 64K tokens. Verify the model and
   runtime actually support the configured context; the Pi prototype's 32K
   choice is not a suitable default for this target.
3. Keep Hermes generic. Implement the HVE-specific research workflow, tools,
   and any scheduling integration in HVE-Librarian's established adapter and
   job patterns rather than modifying Hermes core or adding a parallel service
   stack without need.
4. Reuse HVE-Librarian's existing storage and scheduling conventions where
   appropriate. The prototype's SQLite database, filesystem outbox, systemd
   units, and separate brief repository are implementation choices to review,
   not requirements.
5. Bound source requests, redirects, response sizes, and runtime. Enforce
   private/reserved-address protections at the actual fetcher or egress
   boundary, including browser subrequests; test that boundary rather than
   relying only on preflight URL validation.
6. Test the complete draft against primary sources and human editorial review.
   Record coverage, source quality, invalid-citation behavior, inference
   latency, memory use, and thermals on the Spark before considering a
   recurring schedule.

## Migration gates and decisions

1. In HVE-Librarian, map the current Hermes adapter, model-provider, tool, job,
   and storage patterns before choosing where the workflow belongs.
2. On the Spark, verify a local Hermes inference path with a supported 64K+
   context and structured output using synthetic input. Record model/runtime
   configuration and resource behavior; do not use Pi measurements as a
   substitute.
3. Run a non-publishing pilot against the approved public-source lanes. Check
   actual fetch coverage, source quality, robots/terms compliance, and whether
   each generated claim is supported. Preserve an explicit incomplete status
   on coverage failure.
4. Review the brief and diagnostics before deciding on a daily trigger.
   Schedule, output retention, reviewer routing, credentials, and any
   publication destination require separate decisions and approval.

## References

- [Earlier Pi/Hailo design](x402-watch-design.md) - historical platform design.
- [Pi prototype UAT record](x402-watch-uat.md) - detailed implementation and
  run evidence; not a Spark acceptance report.
