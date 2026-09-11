# Automated Result Analysis — Approved Design and Implementation Plan

**Status:** Implemented; production provider evaluation and rollout pending

**Date:** 2026-09-10
**Branch baseline:** `Test-Updates` at `827a8e473db8660558df85d4a9210ecccbcfdf97`

## Goal

Analyze newly uploaded or manually selected linked laboratory reports, extract reported peptide or molecule test values, and present evidence-backed suggestions for administrator approval.

- Group Tests: match findings to existing `lab_test_details` rows and fill blank `result` values; administrators may also approve creation of unmatched canonical rows.
- Public Results: propose new `item_results` rows for recognized test types.
- Both record types: propose report metadata in a managed description block.

The system reports what the laboratory document says. It does not provide clinical interpretation, calculate safety conclusions, or recommend use or dosing.

## Approved Product Decisions

- Analysis suggestions require administrator review before application.
- Existing non-empty result values are never overwritten.
- Group Test rows are created by analysis only when an administrator explicitly approves an unmatched canonical finding; created rows use zero cost and zero required vials.
- Composite Group Test rows remain intact and receive labeled combined results.
- Public Result rows use canonical test names and preserve source labels in evidence.
- Truly unrecognized findings remain review-only and are not actionable; recognized unmatched findings may be explicitly approved as new rows.
- Reported values and units are preserved verbatim.
- Additional metadata is written only after approval to a delimited, idempotently managed description block.
- Client and laboratory-personnel names are excluded from metadata.
- An explicit laboratory `Net`, `Average`, or `Batch Average` value takes precedence over individual vial readings.
- The application never calculates an average when the report does not provide one.
- Individual vial readings remain evidence only when a laboratory aggregate exists.
- New uploads trigger analysis after the owning record commits successfully.
- Links are never analyzed or polled automatically.
- Edit pages provide separate `Analyze uploaded file` and `Analyze linked result` actions.
- Uploaded/direct document eligibility uses the effective storage-provider format allowlist.
- Static public webpages are supported generically; known laboratories may use provider-specific resolvers.
- Login-required, cookie-dependent, and authenticated pages are unsupported.
- General-purpose production browser automation and anti-bot bypasses are out of scope.
- Existing records are not automatically backfilled.
- The analysis layer is provider-neutral; OpenAI, xAI Grok, and Anthropic Claude are planned providers.
- Provider selection is explicit per run. The system does not silently send a report to a different provider when one fails.
- Source reports are expected not to contain PII, but the system still minimizes retained and transmitted data.
- Analysis runs execute through a durable database-backed worker, not inside web requests.

## Supported Test Taxonomy

V1 canonical types:

- Identity
- Purity
- Mass
- Net Content
- Endotoxin
- Sterility
- Bioburden
- Residual Solvents
- Water/Moisture
- pH
- Appearance

Aliases are normalized in application code, not in provider-specific prompts. Examples include `assay`/`content` to Net Content only when report context supports that meaning, `LC-MS identity` to Identity, `HPLC purity` to Purity, and `LAL` to Endotoxin. Ambiguous aliases remain unrecognized.

## Source Examples

- SteriGenix rendered verification page: `https://sterigenixanalytical.com/verify/RPT-2026-624601`
- Janoshik verification page with linked report image: `https://verify.janoshik.com/tests/208271-Tirzepatide_30mg_9YATH433G9UY`
- Freedom Diagnostics direct PDF: `https://coas.freedomdiagnosticstesting.com/RPPe2608110275.pdf`
- ILS direct PDF: `https://files.ils-lab.com/coa-pdfs/the-shed-ELORASHEDBUY-HvbEfb.pdf`

These sources seed fixture design. Unit tests must not depend on live laboratory sites.

## Data Model

Add an immutable-run audit model and normalized findings through one additive migration.

### `ResultAnalysisRun`

- `id`
- exactly one of `group_test_id` or `public_result_id`
- `source_kind`: `upload` or `link`
- `source_reference`: object key or sanitized URL
- `source_sha256`
- `source_content_type`
- `source_size_bytes`
- `provider`
- `provider_model`
- `schema_version`
- `status`: `queued`, `analyzing`, `needs_review`, `applied`, `failed`, or `superseded`
- `attempt_count`
- `max_attempts`
- `lease_token` and `lease_expires_at`
- `error_code` and administrator-safe `error_message`
- `metadata_json`
- `usage_json` for token/request accounting without source content
- `requested_by_id` and `reviewed_by_id`
- queued, started, completed, reviewed, and created timestamps

Database constraints require exactly one target and valid status/source values. Index target/status, status/queued time, and lease expiry.

### `ResultAnalysisFinding`

- `id` and `analysis_run_id`
- `canonical_type`
- `source_label`
- `reported_value`
- `evidence_text`
- `page_number` when available
- `confidence`
- `is_reported_aggregate`
- `proposed_action`: `fill`, `create`, `conflict`, or `unrecognized`
- `target_row_key` or target row index snapshot
- `review_decision`: `pending`, `accepted`, or `rejected`
- `reviewed_value` for an administrator correction before application
- created and reviewed timestamps

Limit field lengths at both schema-validation and persistence boundaries. Findings are audit records and are not edited after a run is applied; review decisions are recorded separately from raw extraction fields.

## Description Metadata Contract

Preserve administrator-authored text and maintain at most one block:

```text
--- Automated COA Metadata ---
Compound: Retatrutide
Batch/Lot: RT10-260627-A
Laboratory: SteriGenix
Report date: 2026-07-20
Sample ID: ...
Methods: HPLC, LC-MS, LAL
--- End Automated COA Metadata ---
```

- Omit empty fields.
- Exclude client, analyst, reviewer, and other personnel names.
- Review metadata together with findings.
- On application, replace the prior managed block instead of appending duplicates.
- Never alter text outside the block.

## Source Acquisition

### Uploaded documents

- Read private objects through a bounded storage helper.
- Revalidate the object content rather than trusting its stored suffix.
- Use the effective configured `allowed_formats` set: JPEG, PNG, WebP, GIF, and PDF by current defaults.
- Convert the first GIF frame to a still image for analysis; ignore later frames.
- Enforce the lower of the storage upload limit and the 20 MB analysis limit.
- Reject PDFs over 25 pages before provider submission.
- Parse PDFs tolerantly and use the existing page renderer as a fallback for structurally imperfect files that standard viewers can open.

### Direct files and public webpages

- Permit only `http` and `https`, with no URL credentials.
- Allow only public destination IPs; reject loopback, private, link-local, reserved, multicast, and metadata-service ranges for IPv4 and IPv6.
- Resolve and validate every redirect and the connected peer address.
- Limit redirects to three, connection/read time to 30 seconds, HTML to 2 MB, and total document assets to 20 MB.
- Accept direct files only when their detected type is enabled by the effective storage allowlist.
- Accept bounded `text/html` separately for linked-page extraction.
- Never send cookies, application credentials, bearer tokens, or referer-derived secrets.
- Strip scripts, styles, hidden controls, and unrelated navigation from generic HTML before analysis.
- A generic page may expose one same-origin direct PDF/image asset for analysis after the same URL checks.
- Known resolvers may transform stable public verification pages into sanitized text or a public document asset.
- If a provider blocks ordinary safe server retrieval or requires browser execution without a stable public data endpoint, fail with `upload_required`.

Initial known resolver interfaces are `SteriGenixResolver` and `JanoshikResolver`. They must not bypass CAPTCHAs, anti-bot controls, authentication, or access restrictions.

## Provider Interface

Create a provider-neutral contract:

```python
class ResultAnalysisProvider(Protocol):
    capabilities: ProviderCapabilities

    def test_connection(self) -> ProviderHealth: ...
    def analyze(self, document: AnalysisDocument, context: AnalysisContext) -> AnalysisExtraction: ...
```

The orchestrator owns taxonomy, matching, limits, persistence, and application. Providers only return schema-valid extraction candidates.

`AnalysisDocument` is the provider-independent source envelope. It carries bounded extracted text, the original validated MIME type and bytes when appropriate, and ordered page/frame images with page numbers. PDF text extraction and page rendering happen once in the source layer and are reused where a provider needs normalized inputs. `ProviderCapabilities` declares accepted document/image types, direct-PDF support, structured-output support, and applicable request limits so unsupported inputs fail before a paid API call.

All adapters use the same conservative JSON Schema subset, prompt intent, output dataclasses, independent post-response validation, timeout policy, safe error taxonomy, and usage-record shape. Provider SDK exceptions are mapped to `transient`, `rate_limited`, `authentication`, `policy`, `unsupported_input`, or `invalid_response`; raw messages are not exposed to users or logs.

### Provider selection and fallback

- Store the selected provider and configured model on every run before it is leased.
- An automatic upload uses the active provider at queue time; later settings changes do not alter that run.
- A manual rerun may explicitly select a configured provider, bypass completed-source deduplication, and create a separate auditable run.
- Do not automatically fail over between providers. Cross-provider fallback could transmit a report to an unapproved processor, obscure cost/audit history, and change extraction behavior.
- A provider connection test validates credentials and model access with a minimal text-only schema request; it never transmits a report.

### OpenAI implementation

- Use the Responses API with image or file input and strict JSON-schema Structured Outputs.
- Send already-acquired bytes rather than asking the provider to retrieve private or arbitrary URLs.
- Set `store=False`.
- Do not enable web search or other tools.
- Use a configurable model; default initially to `gpt-5.4-mini`, subject to fixture evaluation before release.
- Record the actual returned model identifier, response/request identifier, and token usage.
- Set explicit request and output-token limits.
- Retry only transient transport, rate-limit, and server errors; never retry schema, policy, or unsupported-document failures automatically.
- Validate returned JSON independently before persistence.
- Treat document text as untrusted data and instruct the model to ignore instructions found inside the report.

Official API basis:

- Responses accepts text, image, and file inputs: `https://developers.openai.com/api/reference/cli/resources/responses/methods/create`
- Strict JSON-schema output is supported through Structured Outputs.

### xAI Grok implementation

- Add an `XAIResultAnalysisProvider` using xAI's Responses-compatible API surface and strict JSON-schema Structured Outputs.
- Use a configurable model; initial evaluation candidate is `grok-4.6`, not a hard-coded dependency.
- Send JPEG/PNG inputs inline as base64 data URLs. For PDFs, send bounded extracted text plus ordered page renders because xAI's documented image-understanding input supports JPEG/PNG rather than direct PDF document blocks.
- Normalize GIF, WebP, and other eligible image formats to PNG in the source layer before the Grok call.
- Do not use web/X search, tools, Collections, deferred responses, or provider-hosted source URLs.
- Do not use the xAI Files API. Inline requests work with the planned stateless flow and avoid an additional provider-side stored-file lifecycle; xAI Files is unavailable when team-level Zero Data Retention is enabled.
- Capture the `x-zero-data-retention` response header when present as non-sensitive run metadata so administrators can audit the provider account posture; do not claim ZDR unless the header reports it.
- Record the actual model, request/response identifier, usage, and rate-limit metadata exposed by the API.
- Apply the common retry classification and independently validate the JSON even when the provider reports schema conformance.

Official API basis:

- Image understanding accepts inline/public JPEG or PNG inputs and documents a 20 MiB per-image limit: `https://docs.x.ai/developers/model-capabilities/images/understanding`
- Structured Outputs uses `response_format.type=json_schema`: `https://docs.x.ai/developers/model-capabilities/text/structured-outputs`
- xAI documents default retention, team-level ZDR, the ZDR response header, and Files API restrictions: `https://docs.x.ai/developers/faq/security`

### Anthropic Claude implementation

- Add an `AnthropicResultAnalysisProvider` using the Messages API and `output_config.format` with `type: json_schema`.
- Use a configurable model; initial evaluation candidate is `claude-sonnet-5`, not a hard-coded dependency.
- Send PDFs as base64 `document` content blocks and supported images as base64 `image` blocks. Do not give Anthropic arbitrary source URLs to retrieve.
- Prefer direct request content over the Files API. The report is analyzed once, while the Files API creates provider-side stored objects and is not eligible for Anthropic ZDR.
- Do not enable tools, prompt caching, batches, or server-side model fallback for this feature.
- Bound the request below both application limits and provider limits before encoding; account for base64 expansion in the request-size check.
- Record the actual model, message identifier, input/output usage, and request identifier headers exposed by the SDK/API.
- Apply the common retry classification and independently validate the JSON even when Structured Outputs reports schema conformance.

Official API basis:

- Claude accepts PDF URL, base64 document, or Files API inputs; this design uses base64 document blocks: `https://platform.claude.com/docs/en/build-with-claude/pdf-support`
- Claude Messages accepts JSON Schema through `output_config.format`: `https://platform.claude.com/docs/en/api/messages/create`
- Claude image content supports base64 and documented JPEG, PNG, GIF, and WebP formats: `https://platform.claude.com/docs/en/build-with-claude/vision`
- Anthropic marks its Files API as ineligible for ZDR: `https://platform.claude.com/docs/en/build-with-claude/files`

### Capability matrix

| Capability | OpenAI | xAI Grok | Anthropic Claude |
|---|---|---|---|
| Adapter API | Responses | Responses-compatible | Messages |
| Strict structured JSON | Yes | Yes | Yes |
| Direct PDF input | Yes | No documented direct path; render pages + text | Yes, base64 document block |
| Image input used here | Provider-supported validated image | JPEG/PNG inline | JPEG/PNG/GIF/WebP inline |
| Provider file storage | Disabled/avoided | Files API not used | Files API not used |
| External tools/search | Disabled | Disabled | Disabled |
| Initial model candidate | `gpt-5.4-mini` | `grok-4.6` | `claude-sonnet-5` |

The release choice for each default model is made from the same fixture corpus using field accuracy, false-positive rate, latency, and estimated cost. Model identifiers remain settings so provider releases do not require an application deployment.

### Configuration

Add an administrator-only Result Analysis settings section:

- enabled flag
- active provider
- masked API key and model for OpenAI, xAI, and Anthropic
- per-provider enabled flag and connection status
- maximum document size and pages
- download timeout
- maximum attempts
- worker concurrency guidance
- connection-test action that does not transmit a report

Prefer `OPENAI_API_KEY`, `XAI_API_KEY`, and `ANTHROPIC_API_KEY` from the deployment environment; allow the existing masked settings pattern as an explicit fallback. Never log or return keys. The UI must distinguish `not configured`, `configured`, and `connection test failed` without revealing key prefixes or provider error bodies.

## Extraction Contract

The provider returns only structured data:

- one compound/molecule candidate
- batch/lot, laboratory, report date, sample ID, and methods
- zero or more findings containing source label, canonical-type candidate, verbatim reported value, evidence, page, confidence, aggregate flag, and optional vial identifier
- ambiguity and warning codes

The schema forbids additional properties and bounds all arrays and strings. Provider output cannot directly select database IDs or authorize writes.

## Matching and Net-Value Rules

1. Normalize names and aliases deterministically.
2. Group findings by canonical test type.
3. When the laboratory explicitly reports `Net`, `Average`, or `Batch Average`, choose it as the proposed displayed value and retain vial-level values as evidence.
4. Never calculate an average from individual values.
5. If multiple non-aggregate candidates remain, mark the type ambiguous and require manual entry.
6. For Group Tests, match canonical findings against existing simple or composite test rows; offer unmatched canonical findings as unchecked new-row proposals.
7. A composite row receives a stable labeled string such as `Mass: 10.2 mg; Purity: 99.4%; Identity: Confirmed`.
8. If the matched Group Test row already has a non-empty result, create a conflict finding and do not modify it.
9. For Public Results, propose one canonical row per accepted type and do not create a duplicate of an existing non-empty row.
10. Recompute matching at review/apply time so concurrent administrator edits cannot be overwritten.

## Workflow

### Queueing

- A successful new upload or upload replacement queues one run after the owning database transaction commits.
- A manual POST action queues the explicitly selected upload or link.
- Source hash, target, provider, and schema version form the automatic-analysis idempotency identity.
- Concurrent queued/analyzing runs are deduplicated, while an explicit administrator rerun may reanalyze a completed source.
- A new source supersedes older unapplied runs for that target/source kind.

### Worker

- Add a Flask CLI worker command that atomically leases queued jobs.
- A crashed or expired lease becomes retryable.
- Allow two automatic retries with bounded exponential backoff and jitter.
- Default to two concurrent analyses per worker deployment.
- Commit run status before and after external calls so progress survives process failure.

### Review and application

- Edit pages show current run status and safe errors.
- `Needs review` links to an administrator-only review page.
- Show source, provider/model, extracted metadata, each finding, confidence, page/evidence, target mapping, and conflict state.
- Allow accept/reject per finding and editable accepted values.
- Apply all accepted changes in one transaction after rechecking current target values.
- If the target changed, convert affected findings to conflicts and leave them unapplied.
- Ordinary users see only applied values and approved description metadata.

## UI Changes

### Group Test edit

- Analysis status card.
- `Analyze uploaded file` when an eligible upload exists.
- `Analyze linked result` when a link exists.
- Review link, prior-run summary, and safe failure guidance.

### Public Result edit

- The same source controls and status card.
- Review preview distinguishes new canonical rows, conflicts, metadata, and unrecognized findings.

### Settings

- Add Result Analysis to the existing Settings hub.
- Mask secrets and preserve unchanged secret values.
- Explain that results require administrator approval and are not medical interpretation.

## Security Review Requirements

- Every queue, status, review, apply, retry, and settings route is administrator-only and CSRF protected.
- Linked-source retrieval passes the SSRF controls above, including every redirect.
- Content type is detected from bytes and bounded before parsing or API submission.
- PDF/image parsers run with page, pixel, decompression, and memory limits.
- Source filenames, HTML, PDF text, and model output are untrusted.
- Provider prompts cannot grant write authority; only deterministic application code may mutate results.
- Logs contain run IDs and safe error codes, not source content, signed URLs, API keys, evidence, or provider responses.
- Provider response storage is disabled where supported.
- Result access rules remain unchanged after extracted values are applied.

## Reliability Requirements

- Queue creation occurs only after the record/source commit succeeds.
- Job claiming is atomic and safe across multiple workers.
- Application is idempotent and rechecks current values under transaction.
- Network operations use explicit connect/read/request timeouts.
- Retry classification distinguishes transient from permanent failures.
- Provider/schema version and source hash make reruns reproducible and auditable.
- No live network or provider dependency exists in the unit-test suite.
- A failed analysis never removes or changes existing result data.

## Performance and Cost Requirements

- Maximum analyzed source: 20 MB and 25 PDF pages.
- Maximum generic HTML: 2 MB.
- Maximum three redirects.
- Two retries and two concurrent analyses per worker by default.
- Avoid duplicate automatic provider calls through source hashing and active-run deduplication; honor explicit administrator reruns.
- Store usage metadata for cost monitoring without storing document text.
- Render or decode only pages/frames needed by the selected provider input path.

## Implementation Phases

### Phase 1 — Contracts, fixtures, and persistence

Target files:

- `app/models.py`
- `migrations/versions/<new_revision>.py`
- `app/result_analysis/types.py`
- `app/result_analysis/taxonomy.py`
- `tests/fixtures/result_analysis/`
- `tests/test_result_analysis.py`

Work:

- Create synthetic/minimized fixtures representing the four supplied report layouts.
- Define extraction schema, taxonomy, aliases, managed metadata block, run/finding models, constraints, and indexes.
- Add migration and schema tests.

### Phase 2 — Safe source acquisition

Target files:

- `app/storage.py`
- `app/result_analysis/sources.py`
- `app/result_analysis/resolvers.py`
- `tests/test_result_analysis_sources.py`

Work:

- Add bounded private-object reads.
- Implement file sniffing, GIF first-frame handling, PDF page limits, SSRF-safe fetches, redirects, static HTML extraction, and known provider resolvers.
- Add malicious URL, redirect, MIME mismatch, oversize, timeout, and resolver fixture tests.

### Phase 3 — Provider abstraction and OpenAI adapter

Target files:

- `app/result_analysis/providers/base.py`
- `app/result_analysis/providers/openai.py`
- `app/result_analysis/service.py`
- `requirements.txt`
- analysis settings routes/templates
- provider tests

Work:

- Add provider interface, OpenAI Responses adapter, strict schema validation, masked configuration, connection test, safe retry classification, and usage capture.
- Mock every provider call in automated tests.

### Phase 3b — Grok and Claude adapters

Target files:

- `app/result_analysis/providers/xai.py`
- `app/result_analysis/providers/anthropic.py`
- `app/result_analysis/providers/registry.py`
- `app/result_analysis/documents.py`
- `app/result_analysis/service.py`
- `requirements.txt`
- analysis settings routes/templates
- provider contract and fixture-evaluation tests

Work:

- Add capability-aware document normalization, including bounded PDF text/page extraction and PNG conversion for Grok.
- Implement Grok Responses-compatible structured extraction without Files, search, or tools.
- Implement Claude Messages structured extraction with inline base64 PDF/image blocks and without Files, caching, batches, fallback, or tools.
- Add explicit provider selection, per-provider health checks, normalized errors/usage, and audit metadata.
- Run every adapter against the same mocked contract suite and synthetic report corpus before enabling it.

### Phase 4 — Queue and orchestration

Target files:

- `app/result_analysis/jobs.py`
- `app/__init__.py`
- `app/routes.py`
- deployment documentation/`Procfile` as required
- job tests

Work:

- Implement idempotent queueing, atomic leasing, retry/backoff, source supersession, worker CLI, and post-commit upload triggers.

### Phase 5 — Review and apply UI

Target files:

- `app/routes.py`
- `app/templates/admin/edit_test.html`
- `app/templates/admin/public_results.html`
- new analysis review/settings templates
- security and route tests

Work:

- Add manual source-specific actions, status cards, review workflow, conflict handling, transactional application, composite formatting, Public Result row creation, and managed description updates.

### Phase 6 — Full validation and documentation

Target files:

- `PROJECT_MAP.md`
- `docs/project-history.md`
- `README.md`
- `ADMIN_QUICK_START.md`
- all affected tests

Work:

- Run focused suites after each phase, then the full suite.
- Verify migrations from a pre-feature schema and a clean schema.
- Document worker deployment, configuration, review workflow, supported sources, limitations, and recovery.

## Acceptance Criteria

1. A new eligible Group Test or Public Result upload queues exactly one analysis run after commit.
2. Saving or changing a link does not automatically queue analysis.
3. Administrators can manually analyze the upload or link independently from the edit page.
4. Non-administrators cannot queue, inspect, review, retry, or apply analyses.
5. Direct PDFs/images and bounded static public HTML are supported without credentials or cookies.
6. Known laboratory resolvers never bypass authentication, CAPTCHAs, or anti-bot restrictions and return `upload_required` when safe retrieval is unavailable.
7. Private, loopback, link-local, reserved, metadata-service, or redirect-to-private URLs are rejected before content is processed.
8. Eligible upload types come from the effective storage format allowlist; GIF analysis uses only the first frame.
9. Sources over 20 MB, PDFs over 25 pages, and HTML over 2 MB fail safely without a provider call; structurally imperfect but readable PDFs are parsed tolerantly.
10. OpenAI receives acquired file/image content through the Responses API with strict JSON-schema output and `store=False`.
11. Provider credentials and raw provider responses never appear in logs or UI errors.
12. Every proposed result includes a source label, verbatim value, confidence, and evidence; page number is included when available.
13. Explicit Net/Average/Batch Average values are preferred over vial readings, and the application never calculates an absent aggregate.
14. Group Test analysis creates rows only for explicitly approved unmatched canonical findings, using zero cost and zero required vials, and never overwrites a non-empty result.
15. Composite Group Test rows receive deterministic labeled result strings.
16. Result analysis proposes canonical rows, avoids duplicates, and leaves truly unrecognized findings non-actionable.
17. Description metadata is administrator-reviewed, excludes personnel/client names, preserves manual text, and maintains one idempotent managed block.
18. Applying accepted findings is atomic and rechecks concurrent record changes.
19. Failed, retried, superseded, rejected, and applied runs remain auditable without retaining duplicate source documents.
20. Ordinary users see only administrator-approved results and metadata.
21. Unit tests use local fixtures and mocked provider/network calls; the full suite requires no external service.
22. Migration, security, source, provider, queue, review, and full regression suites pass before release.
23. OpenAI, xAI, and Anthropic adapters implement the same provider contract and return the same independently validated extraction schema.
24. Grok receives only inline JPEG/PNG page images and bounded extracted text; PDFs and other eligible image formats are normalized locally before submission.
25. Claude receives PDFs/images in inline base64 content blocks and does not create Files API objects, prompt caches, batches, tool calls, or server-side fallbacks.
26. Provider selection is fixed on each run; a failure never silently transmits the report to another provider.
27. Each provider has an administrator-only text connection test that sends no report and reveals no credential or raw error content.
28. Provider credentials, configured secret placeholders, request content, and raw responses remain absent from logs and user-visible errors across all three adapters.
29. Each adapter passes a shared mocked contract suite and the same fixture evaluation; provider enablement records field accuracy, false-positive rate, latency, and estimated cost.
30. xAI retention status is recorded only from the response header when available; the application never represents ZDR as enabled based solely on configuration.

## Validation Commands

Planned minimum:

```bash
python -m unittest tests.test_schema_migration
python -m unittest tests.test_result_analysis tests.test_result_analysis_sources
python -m unittest tests.test_security tests.test_storage
python -m unittest tests.test_notifications tests.test_lab_costs tests.test_participant_removal
python -m unittest
git diff --check
```

Add the new test modules to discovery-compatible paths so `python -m unittest` includes them automatically.

## Rollout

1. Deploy migration, settings, and worker with analysis disabled.
2. Configure the OpenAI project key and selected model.
3. Run the shared fixture/evaluation corpus and record per-field accuracy, false-positive rate, latency, and estimated cost for OpenAI.
4. Enable OpenAI manual analysis for administrators only.
5. Add Grok and Claude credentials in disabled state, run their connection and fixture evaluations, then enable each provider independently only if it meets the release threshold.
6. Confirm provider selection, audit, retry, cost, retention metadata, and review behavior in production.
7. Enable automatic analysis for new uploads with one explicitly selected active provider.
8. Do not backfill historical records automatically.

## Remaining Questions

None. Deployment requires the additive migration, provider credentials, a running worker, and successful real-report fixture evaluation before automatic analysis is enabled.
