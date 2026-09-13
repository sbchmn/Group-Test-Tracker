# Project Map

This document is the maintained current-state map for Group Test Tracker. Keep it concise and update it whenever implementation changes architecture, behavior, risks, priorities, or validation status. Historical implementation notes belong in [`docs/project-history.md`](docs/project-history.md).

## Snapshot

- **Application:** Flask web application backed by SQLAlchemy and Alembic.
- **Current code baseline:** `main` at `aec7599c2a4302a9c978505cd087f512d5454a29` (the connector-visible pre-SaaS application baseline; re-read and pin the exact SHA when the SaaS branches are actually created).
- **Planned release lanes:** existing manually managed clients remain on `main`; SaaS development and its DigitalOcean test app use `SaaS-Test`; customer SaaS applications deploy only from `SaaS-Main`.
- **SaaS compatibility:** Control-plane integration and branch isolation are mapped below but not implemented; no branch has been created by this planning change.
- **Application version:** `3.2` from `app/version.py`.
- **Primary interfaces:** authenticated web UI, admin UI, Telegram webhook/bot, Discord gateway bot, email, and Root webhook delivery.
- **Validation framework:** Python `unittest`; seven top-level test modules cover schema, security, notifications, storage, participation, cost behavior, and automated result analysis.
- **Deployment entry points:** `run.py` and `Procfile`, including a dedicated result-analysis worker process.

## Architecture and Ownership

| Area | Primary files | Responsibility |
| --- | --- | --- |
| Application setup | `app/__init__.py`, `run.py` | Flask factory, extensions, CLI commands, and process startup |
| Domain and persistence | `app/models.py`, `migrations/versions/` | Users, tests, participation, payments, results, bot configuration, event records, and additive schema evolution |
| Web and admin workflows | `app/routes.py`, `app/templates/` | Authentication, user/admin forms, group-test lifecycle, results, payments, settings, and Telegram webhook routing |
| Notifications | `app/notifications.py` | Email, Telegram, Discord, and Root message rendering and transport |
| Bot integrations | `app/discord_bot.py`, `app/public_results_bot.py`, `app/bot_dispatch.py` | Discord gateway behavior, shared Public Results queries, and outbound webhook dispatch |
| Object storage | `app/storage.py` | S3-compatible uploads, validation, deletion, and signed URL generation |
| Export | `app/export.py` | Spreadsheet export |
| Operations and documentation | `README.md`, `ADMIN_QUICK_START.md`, `Procfile` | Setup, administration, troubleshooting, and deployment guidance |
| Tests | `tests/test_*.py` | Regression coverage for business, security, integration, storage, and migration behavior |

## Implemented Capabilities

### Group tests and participation

- Manage recruiting, ready-for-payment, testing, and closed group tests.
- Request, approve, deny, reopen, and manually add participants while retaining denial state and reason.
- Recalculate participant costs and track order, payment, amount owed, and amount paid state.
- Provide dashboard grouping, sorting, searching, hiding, and participation-state actions.
- Export test data to spreadsheets.

### Results and storage

- Manage group-test and Public Results records with tags and itemized values.
- Upload image or PDF result files to S3-compatible storage.
- Issue short-lived signed URLs through authenticated application routes.
- Restrict group-test results to administrators or approved, paid participants.
- Combine eligible group-test and Public Results content on My Results.
- Queue bounded upload or public-link report sources for durable, administrator-reviewed extraction.
- Use an explicit OpenAI, xAI Grok, or Anthropic Claude provider per run without cross-provider fallback.
- Fill only blank existing Group Test rows, create canonical non-duplicate Public Result rows, and preserve evidence and audit history.
- Prefer explicit laboratory Net/Average values without calculating an aggregate, and append approved metadata in an idempotent managed description block.
- Accept Telegram `/submitcoa` submissions from linked users with a PDF/image attachment or public report link.
- Route submitted COAs through durable analysis and administrator review, including finding selection, value correction, evidence display, result naming, metadata inclusion, approval, and rejection.
- Support configurable Telegram review chat/thread destinations and preserve review state across worker restarts.
- Display callback feedback for review actions and accept name/value replies in configured private chats, groups, and forum threads.
- Normalize unset or malformed Telegram thread and message IDs so stale configuration or persisted state cannot raise integer-conversion errors.
- Provide a dedicated Public Result page with a Back to My Results button and inline PDF/image report rendering below the result details.
- Show the submitted COA source in Telegram review, provide a direct link for link-based submissions, and preserve uploaded image/PDF submissions on the Public Result.
- Let administrators select and deselect existing tags during Telegram COA review; selected tags are applied when the result is approved.
- Provide paginated Telegram tag selection with ten tags per page and explicit Save/Cancel navigation.
- Stage source edits during review so a COA can contain both a public link and an uploaded image/PDF regardless of which source started the submission.

### Payments

- Configure reusable payment options and assign them to individual tests.
- Render provider-specific destinations, links, QR payloads, and copy fallbacks.
- Preserve participant payment-option snapshots without treating selection as payment proof.

### Notifications and scheduling

- Deliver email, Telegram, Discord, and Root notifications with provider-specific formatting.
- Queue user digest events and send hourly or daily digests through a scheduler-friendly Flask command.
- Persist Telegram status digest events and suppress duplicate webhook updates.
- Use bounded Discord delivery, content chunking, rate-limit retries, and disabled broad mentions.

### Telegram

- Link accounts using single-use tokens and stable Telegram user/chat IDs.
- Validate webhook secrets, optional source CIDRs, and replay identifiers.
- Support built-in test discovery, participation, status, onboarding, and Public Results commands.
- Support configurable commands with categories, argument policies, rate limits, and chat/thread allowlists.
- Support one configurable command image and administrator reply-based replacement.
- Preserve Telegram forum-topic routing for command replies and administrator confirmations.
- Accept still images, GIFs, and Telegram MP4 animation loops for command media.

### Discord and Root

- Link Discord identities using single-use user tokens.
- Run native Discord interactions with early deferral and worker-thread database access.
- Support scoped Public Results browsing and configured dynamic commands.
- Deliver Discord and Root outbound webhook notifications.

### Administration

- Provide a consolidated Settings hub for notifications, bot integrations, commands, templates, payments, and storage.
- Preserve masked provider secrets when forms submit unchanged placeholders.
- Keep provider identity linking user-owned; administrator edits do not silently reassign Telegram or Discord identities.
- Display sanitized, bounded provider diagnostics only on the administrator-only Result Analysis Settings page.

## Active Priorities

1. **Automated result analysis — implemented; deployment evaluation pending**
   - The durable worker, provider adapters, bounded source acquisition, administrator review/apply UI, automatic new-upload queueing, migration, tests, and operating documentation are implemented.
   - Before production enablement, migrate the database, configure one provider, run the shared real-report fixture evaluation, and operate the dedicated worker.
   - Follow [`docs/plans/2026-09-10-automated-result-analysis.md`](docs/plans/2026-09-10-automated-result-analysis.md) for acceptance criteria and staged rollout.

2. **Public Results notifications and enrichment**
   - Normalize and bound itemized result data.
   - Escape provider markup and disable Discord mentions.
   - Validate external COA URLs.
   - Dispatch notifications only after commit and make delivery idempotent.
   - Add Telegram, Discord, route, malformed-input, and truncation tests.

3. **Discord command parity and hardening**
   - Replace Telegram-named command fields and models with provider-neutral or Discord-native ownership.
   - Add dedicated tests for link conflicts, interaction deferral, authorization, synchronization, rate limiting, media responses, and administrator reply updates.
   - Validate configured guild/channel IDs and document invite/permission setup.

4. **Provider destination management**
   - Present friendly provider-qualified destination names while retaining raw IDs internally.
   - Add explicit refresh, validation, permission status, and send-test actions.
   - Preserve manual ID entry as a fallback, especially for Telegram.

5. **Delivery durability and service boundaries**
   - Extract provider-neutral bot operations from route and adapter code.
   - Introduce authenticated, versioned internal APIs only when independently deployed bot processes require them.
   - Add idempotency, timeouts, bounded retries, and contract tests before process separation.
   - Move outbound delivery to durable jobs when traffic or retry requirements justify the operational complexity.

6. **Repository and verification hygiene**
   - Add automated CI for the full unittest suite.
   - Stop tracking runtime databases, logs, `__pycache__`, and `.pyc` files.
   - Remove one-off debug artifacts after confirming they are not operational dependencies.

7. **SaaS control-plane compatibility — mapped; implementation not started**
   - Implement the managed/standalone boundary, subscription/entitlement enforcement, signed control-plane API, provisioning bootstrap, support account, documentation launch, health contract, and lifecycle tests described below.
   - Freeze cross-repository contracts before writing either side so provisioning, retries, revisions, and failure behavior remain compatible.

## Planned SaaS Control-Plane Compatibility

**Status:** Planning complete enough to estimate and sequence; no SaaS integration code or migration has been implemented.

### Compatibility and ownership rules

- Add an explicit `GTT_DEPLOYMENT_MODE=standalone|managed` boundary. Default to `standalone` so existing self-hosted and manually managed deployments keep their current behavior.
- In `managed` mode, the control plane owns subscription state, canonical tenant identity, entitlement revisions, support-account lifecycle, documentation launch authorization, and initial administrator bootstrap. GTM continues to own users, group tests, results, participant payments, tenant configuration, and customer-supplied bot/AI/email/storage credentials.
- Never scatter environment reads or plan-name comparisons through routes and templates. One typed entitlement service must parse, validate, expose, and test the complete contract.
- Client-side hiding is informative only. Route, service, CLI, bot-command, notification, and worker checks are authoritative.

### Environment and trust contract

| Setting | GTM responsibility | Failure behavior in managed mode |
| --- | --- | --- |
| `GTT_TENANT_ID` | Immutable tenant/audience identifier | Readiness fails; paid features fail closed |
| `GTT_PLAN_CODE` | Display/diagnostic label only | Show unknown plan; never grant access from it |
| `GTT_ENTITLEMENTS` | Versioned canonical feature set, initially `core`, `discord_bot`, `result_analysis` | Preserve Core diagnostics; deny paid features |
| `GTT_ENTITLEMENT_REVISION` | Monotonic desired-state revision | Reject stale control-plane mutations and report drift |
| `GTT_SUBSCRIPTION_STATUS` | `active`, `trialing`, `grace`, `suspended`, or `canceled` | Invalid state fails closed and remains diagnosable |
| `GTT_CONTROL_PLANE_URL` | Canonical billing/upgrade/tenant-console origin | No generated upgrade redirect; show configuration error |
| `GTT_SUPPORT_URL` | External support destination | Support page remains available with a safe unavailable state |
| `GTT_USER_DOCUMENTATION_URL` | User-documentation launch destination | Do not emit a broken or unsigned link |
| `GTT_ADMIN_DOCUMENTATION_URL` | Administrator-documentation launch destination | Administrators retain user docs only |
| `GTT_PUBLIC_URL` | Canonical tenant origin for generated links | Readiness warning; never trust an arbitrary Host header |

- Use per-tenant, per-direction Ed25519 key pairs and compact JWS with the algorithm pinned to `EdDSA`. The control plane keeps the CP-to-GTM private key and provisions its public verification set to GTM; GTM keeps its GTM-to-control-plane private key in a DigitalOcean encrypted secret and registers only its public key with the control plane. Never share one HMAC/bearer secret across directions.
- Every signed request includes `kid`, `iss`, `aud`, `iat`, `nbf`, `exp`, `jti`, tenant ID, contract version, HTTP method, canonical path, SHA-256 body digest, operation ID, and requested revision. Maximum request/assertion lifetime is 120 seconds, accepted clock skew is 60 seconds, and used `jti` values are retained for at least 10 minutes. Documentation launch assertions expire within 60 seconds and are one-time use.
- Publish public keys as a versioned JWKS-style `OKP`/`Ed25519` set with `staged`, `active`, and `retired` lifecycle metadata. Install the next public key before sender cutover, switch by `kid`, retain the old public key as verify-only for 48 hours or until all in-flight work and deployment verification complete (whichever is later), then remove it. Private keys never appear in databases shared with tenants, logs, responses, or URLs.
- Add a contract-version setting and publish the accepted versions in the status endpoint so incompatible control-plane/GTM deployments fail before mutation.
- Keep every secret out of templates, diagnostics, health responses, audit payloads, URLs, and process command arguments.

### Subscription and entitlement behavior

- `standalone`: preserve all existing capabilities and configuration paths.
- `active` and `trialing`: enable only the supplied entitlements. Trial add-ons work only when explicitly included.
- `grace`: retain the current paid feature set, show a persistent billing warning to administrators, and link to the control-plane billing page.
- `suspended` and post-term `canceled`: block ordinary users. Tenant administrators enter a server-side allowlisted recovery shell: they may view existing group-test lists/details/results without mutation, download a new sanitized test/results export, open Support/billing, manage their own session, and log out. They cannot create, edit, delete, transition, approve, pay, or otherwise mutate tests/participants/results; export the user directory or participant identity/payment/notes data; send email, Telegram, Discord, Root, digest, webhook, or bot notifications; run bot commands/synchronization; or start provider/analysis work.
- Implement suspension as an allowlist, not a denylist, so future routes default blocked. GET routes admitted to recovery must be side-effect free, and every notification/provider service must independently enforce suspension as a final backstop.
- The existing `generate_test_export` workbook includes participant names, Telegram usernames, verification/payment state, and notes and therefore must not be exposed in recovery. Add a distinct bounded recovery export containing test metadata, test configuration/costs, result rows, source references, and relevant test audit timestamps, but no user directory, participant rows, contact identifiers, bot identifiers, credentials, or account exports.
- Downgrades preserve Discord/AI settings, analysis history, findings, and tenant data. They block new execution before DigitalOcean removes the worker. Upgrades become usable only after the new entitlement revision is loaded; stale workers refuse work.
- `discord_bot` gates the entire Discord surface: gateway worker startup/handlers, linking tokens and claims, command registration/synchronization/execution, Discord settings/test actions, outbound Discord webhooks/notifications, and Discord as a selectable user notification channel. Without entitlement, saved configuration remains but cannot be edited or used; existing Discord channel preferences remain stored but delivery is suppressed and is never silently rerouted.
- Without `result_analysis`, no `ResultAnalysisRun` may be inserted by upload hooks, manual Analyze, Retry, provider tests, public-result paths, or Telegram `/submitcoa`. On entitlement removal, an idempotent pre-deploy reconciliation marks queued/retry-scheduled work terminal as `canceled_entitlement`, clears leases, records the entitlement revision/reason, and then permits worker removal. In-flight/stale workers recheck entitlement immediately before provider I/O and before persistence.
- Re-upgrade never resumes `canceled_entitlement` runs. After entitlement returns, an administrator must explicitly create a new analysis; historical runs/findings remain readable.

### GTM implementation work packages

| Work package | Primary files/modules | Required change |
| --- | --- | --- |
| Entitlement kernel | new `app/entitlements.py`, `app/__init__.py`, `app/routes.py` | Typed contract parsing, deployment mode, feature/status checks, decorators/service guards, Jinja context, upgrade URLs, and safe diagnostics |
| Subscription UX | `app/templates/base.html`, new subscription/recovery templates, admin Settings templates, `app/export.py` or a focused recovery-export module | Plan/status banner, locked cards with upgrade actions, grace messaging, server-side suspended-admin route allowlist, and a sanitized test/results-only recovery export |
| Discord enforcement | `app/discord_bot.py`, `app/routes.py`, `app/notifications.py`, `app/templates/profile.html`, `app/templates/admin/bot_integrations.html` | Guard startup, synchronization, handlers, linking, saves/tests, and any in-scope outbound delivery while preserving stored configuration |
| Analysis enforcement | `app/result_analysis/jobs.py`, `app/result_analysis/service.py`, analysis routes, `_result_analysis_card.html`, `result_analysis_config.html` | Prevent automatic/manual queueing, claims, retries, provider tests, and paid mutations while retaining readable history and data |
| Support and documentation | new focused support blueprint/service/templates plus `base.html` | Logged-in Support tab, user/admin documentation authorization, external helpdesk link, support-access request/status, and no public documentation URLs |
| Managed system account | `app/models.py`, a focused user-management service, auth/user routes, CLI commands, user/profile templates | Immutable reserved support identity, enable/disable/rotation only through the control plane, and immediate session invalidation |
| Control-plane API | new isolated internal blueprint/service | Signed versioned commands, bootstrap, support lifecycle, status, replay defense, idempotency, bounded audit, and JSON-only error contracts |
| Provisioning readiness | `app/__init__.py`, `app/version.py`, new health/status service | Public minimal liveness/readiness plus signed detailed status reporting application, schema, contract, tenant, entitlement, and support revisions |
| Schema | `app/models.py`, new additive Alembic revisions | System-account/auth fields and durable command receipts/audit records, compatible with shared DigitalOcean MySQL and SQLite tests |
| Deployment contract | `Procfile`, `.env.example`, `README.md`, `ADMIN_QUICK_START.md` | Managed variables, pre-deploy `flask --app app db upgrade head`, conditional worker expectations, bootstrap flow, recovery behavior, and troubleshooting |
| Validation | new focused test modules plus existing security/result-analysis/notification/schema suites | Cross-product state matrix, tamper/replay tests, stale-worker tests, migration tests, UI locks, standalone compatibility, and control-plane contract tests |

### Internal control-plane interface

- Isolate endpoints under a versioned internal blueprint such as `/internal/control-plane/v1`; do not add these mutations to the already-large general route module.
- Verify the pinned Ed25519/`EdDSA` JWS contract above and authenticate the exact HTTP method, canonical path, timestamps, `jti`, operation ID, tenant ID, revision, contract version, and SHA-256 body digest. Reject algorithm substitution, unknown/retired `kid`, more than 60 seconds of clock skew, expired or over-120-second assertions, replay, wrong audience, browser session credentials, and non-JSON mutation bodies.
- Exempt only this internal blueprint from CSRF because it does not use browser cookies; all ordinary GTM forms retain CSRF protection.
- Persist a unique operation ID, payload hash, requested revision, outcome, and bounded response summary. Replaying the same operation and payload returns the prior result; reusing an ID with a different payload is rejected.
- Initial-administrator bootstrap creates exactly the requested administrator once from the control-plane-produced, versioned Werkzeug scrypt hash. Validate the encoded scheme/length, reject username/email collisions, never pass the hash on a process command line, and never expose it in a response or log.
- Support lifecycle accepts only the reserved support identity and monotonically increasing revisions. It may create the account disabled, rotate its validated hash, enable/disable it, increment its authentication epoch, and report actual state; it cannot edit arbitrary users.
- A signed status endpoint returns only bounded operational metadata: application version, Alembic revision, supported contract versions, tenant ID, loaded entitlement revision/status, and support-account actual revision/state.
- Add minimal unauthenticated liveness/readiness endpoints suitable for DigitalOcean health checks without tenant data, exception text, configuration values, or secrets.

### Immutable support-account design

- Add nullable unique `system_account_key`, `auth_epoch`, and control-plane credential/state revision fields to `User`; reserve `control_plane_support` independently of username or email.
- The managed account is displayed as username `gtmsupport` with internal email `support@grouptest.online`. Reserve both identities case-insensitively after the same normalization used by authentication, but authorize exclusively through `system_account_key`.
- Managed provisioning creates the support identity disabled with administrator role and notifications/bot identities off. Standalone deployments do not create it automatically. If a pre-existing ordinary account conflicts with the reserved username or email, never adopt or overwrite it: leave managed support disabled, return a bounded conflict, and route an Admin Action for operator resolution.
- Centralize user mutations so registration, ordinary admin creation/edit/toggle/reset, public reset, self-profile/password changes, bot-link creation/claim, imports, `create-admin`, `demote-admin`, and future deletion reject system-managed accounts.
- Hide ordinary Edit, Reset, Activate/Deactivate, and future Delete controls, but treat server-side rejection as the security boundary.
- Prevent ORM/service deletion of the system account. Direct database-owner repair remains possible and must be audited operationally.
- Bind authenticated sessions to `auth_epoch`; disabling or rotating the support account invalidates all of its existing sessions on the next request. Maintain backward compatibility for ordinary pre-migration sessions or deliberately invalidate them once during rollout.

### Support and documentation launch flow

- Add a Support navigation item for every authenticated user. Tenant administrators additionally see administrator documentation and support-access enable/disable controls.
- The GTM support toggle requests desired state from the control plane; it does not directly activate the local account. Show pending/actual state and a retry-safe error when the control plane is unavailable.
- Launch documentation with a short-lived signed POST assertion containing issuer/tenant, opaque user subject, GTM role, audience, destination, expiry, and nonce. Never put the signed assertion or identity fields into analytics URLs.
- Ordinary users receive user documentation only; administrators receive user and administrator documentation. The external helpdesk may keep separate portal accounts and receives no GTM password or support credential.

### Migration, deployment, and release behavior

- Add forward-only Alembic revisions; never modify historical migrations. Test from both an empty database and the current production head on MySQL-compatible behavior.
- The migration adds schema only. The signed managed-provisioning operation creates the reserved support account, avoiding an unowned credential in standalone databases.
- Keep the existing manual `create-admin` command for standalone use, but route it through the same system-account protections. Managed bootstrap uses the signed internal operation.
- DigitalOcean performs `flask --app app db upgrade head` as a pre-deploy job before web/worker activation. GTM readiness must report the expected schema before the control plane marks a deployment healthy.
- Web, Discord, and analysis processes all load the same immutable entitlement revision at startup. Runtime changes arrive through App Platform configuration/deployment; no process should invent or persist a different entitlement set.
- Source repository is settled as `sbchmn/Group-Test-Tracker`. Existing manually managed customers remain on `main`, and SaaS-only code/migrations must never be merged there merely to deploy the SaaS product.
- When implementation is authorized, create case-sensitive branches `SaaS-Test` and `SaaS-Main` from the same re-read, recorded `main` commit and tag that commit with a dated SaaS baseline. This planning change does not create either branch.
- All SaaS development lands in `SaaS-Test` and deploys to the existing development test application. Promotion is a reviewed, tested PR from `SaaS-Test` to protected `SaaS-Main`; customer DigitalOcean applications track `SaaS-Main` only.
- Apply future fixes from `main` one way into `SaaS-Test`, resolve Alembic revision collisions there, validate, then promote to `SaaS-Main`. Never back-merge SaaS-only commits or migrations into `main` accidentally.
- Protect `SaaS-Main` from direct pushes and require the full suite, contract tests, migration checks, and a healthy real DigitalOcean `SaaS-Test` deployment before promotion. The control plane does not monitor the development test app in the MVP.

### Security, reliability, and optimization review

- **Security:** Preserve existing admin/participant authorization beneath feature gates; pin Ed25519/`EdDSA`, validate canonical claims/audience/version/key lifecycle, retain bounded replay records, isolate private keys per tenant/direction, enforce the suspended recovery allowlist and sanitized export, preserve immutable system identity/session epochs/canonical URLs, and redact bounded logging.
- **Reliability:** Make bootstrap and support commands idempotent, distinguish desired from actual revisions, fail paid features closed without breaking Core diagnostics, commit state before acknowledging commands, and surface drift/failures to the control plane Admin Action Queue.
- **Optimization:** Parse immutable environment state once per process, use constant-time set membership for feature checks, index operation IDs/system keys/revisions, avoid per-request control-plane calls, and perform network synchronization only for explicit support/documentation actions.

### Validation plan

- Add `tests/test_entitlements.py` for standalone compatibility and the full status × feature matrix, including recovery-route allowlisting and default denial of newly added routes.
- Add `tests/test_control_plane_api.py` with shared deterministic Ed25519 fixtures for algorithm substitution, `kid` rotation overlap/retirement, 60-second skew, 120-second lifetime, replay, payload mismatch, idempotency, bootstrap collisions, stale revisions, safe errors, and status output.
- Add `tests/test_support_access.py` for every admin/self-service/reset/link/CLI/delete mutation path, role immutability, support toggles, credential rotation, and session invalidation.
- Extend `tests/test_result_analysis.py`, `tests/test_notifications.py`, `tests/test_security.py`, `tests/test_export.py`, and `tests/test_schema_migration.py` for zero queue inserts without entitlement, terminal downgrade cancellation/no re-upgrade resume, Discord-wide notification gates, suspended mutation denial, sanitized recovery exports, worker races, MySQL-safe migrations, and unchanged standalone behavior.
- Add cross-repository contract fixtures so the control plane and GTM test the same environment schema, signature canonicalization, command/status JSON, entitlement identifiers, and supported contract versions.
- Before production, test Core, Discord, AI, Complete, trial, grace, upgrade, downgrade, suspension, recovery/export, stale worker, failed bootstrap, and support rotation in a real DigitalOcean test application.

### Recommended implementation sequence

1. When implementation is authorized, re-read `main`, record/tag the exact baseline, create `SaaS-Test` and `SaaS-Main` from it, and configure protections/deployment targets without changing existing `main` clients.
2. Freeze the shared Ed25519/JWS, environment, bootstrap-hash, status, recovery-export, and operation fixtures in both repositories.
3. Add additive schema, the entitlement kernel, recovery allowlist, and standalone-compatibility tests on `SaaS-Test`.
4. Add signed internal status/bootstrap operations and DigitalOcean readiness checks.
5. Add immutable support identity, session epochs, support page, and documentation assertions.
6. Gate all Discord and result-analysis queue/provider/notification surfaces and add downgrade reconciliation.
7. Validate migrations and the full lifecycle in the real `SaaS-Test` deployment, then promote by PR to protected `SaaS-Main`.

### Settled SaaS implementation decisions

1. DigitalOcean deploys `sbchmn/Group-Test-Tracker`: customer SaaS apps track `SaaS-Main`, development testing uses `SaaS-Test`, and current non-SaaS clients remain on `main`.
2. `discord_bot` covers the gateway worker, commands/linking/settings, Discord webhooks/notifications, and the Discord user notification channel.
3. Analysis is never queued without `result_analysis`; pending work is terminally canceled on downgrade and never automatically resumes after re-upgrade.
4. Suspended tenant administrators have only the explicit read-only test/results, sanitized test export, billing/support, session, and logout surface described above; user/participant exports, mutations, delivery, bot, and provider operations are blocked.
5. Cross-repository authentication uses per-tenant, per-direction Ed25519 keys and pinned `EdDSA` JWS with a 60-second clock-skew allowance, 120-second maximum request lifetime, one-time `jti`, and staged key rotation.
6. The immutable support identity is `gtmsupport` / `support@grouptest.online`, authorized only by `system_account_key=control_plane_support`.

Remaining Phase 0 work is operational configuration (DigitalOcean IDs/scopes, DNS, Mailjet, Stripe, chain providers, retention/support policy) and shared contract fixtures, not an unresolved GTM product choice.

## Deferred Work

- Separately deploy Telegram and Discord processes only after the shared service/API contract is stable.
- Add Root connection testing beyond outbound webhook delivery.
- Add administrator-triggered Public Results re-notification only after initial idempotent creation delivery is established.
- Introduce a separate queue/worker platform only when in-process or synchronous delivery no longer meets reliability requirements.

## Security Invariants

- Administrative workflows require application-level `User.is_admin`; provider moderator status is not a substitute.
- Provider account links are token-based, single-use, conflict checked, and bound to stable provider IDs.
- Telegram webhook traffic fails closed without a configured matching secret.
- Non-private bot commands are disabled unless the specific command and destination scope explicitly allow them.
- Callback and reply actions revalidate identity, command ownership, and destination scope.
- Group-test result links and files require administrator access or approved-and-paid participation.
- Uploaded content is size bounded, type validated, stored under generated keys, and never trusted based only on a client filename.
- Secrets remain masked in admin interfaces and must not appear in logs or rendered messages.
- Result-analysis diagnostics retain only bounded status/code/request-ID context, redact credential patterns, exclude report content and raw responses, and rely on template auto-escaping.
- User-controlled Telegram/Discord text must not create markup, commands, callbacks, or broad mentions.

## Reliability Invariants

- Schema changes are additive Alembic revisions; existing migrations are immutable.
- Database changes commit before external notifications are attempted.
- External delivery failures do not roll back committed domain changes.
- Duplicate webhook and digest events are handled idempotently.
- External calls use explicit timeouts and bounded retry behavior.
- Provider diagnostic writes are best-effort, process-safe on Linux, and cannot alter provider or worker outcomes; the log discards oldest entries when its configured size is reached.
- Payment selection does not alter accounting or prove payment.
- Replacing stored media commits the new reference before best-effort deletion of the previous object.
- Provider-specific adapters format and transport messages; business authorization stays in shared application logic.
- Optional Telegram thread IDs are normalized at configuration, persistence, matching, and transport boundaries; invalid values are treated as unset.
- Telegram review replies are processed before non-private command filtering, while administrator, chat, thread, and pending-action checks remain enforced.

## Optimization Guidance

- Keep request paths free of unbounded provider waits and broad table scans.
- Use indexed identifiers for command, invocation, participation, callback, and event lookups.
- Bound pagination, message length, upload size, retry duration, and digest windows.
- Prefer shared service helpers over duplicated Telegram/Discord business queries.
- Add infrastructure such as durable queues only when measured load or delivery requirements justify it.

## Validation Baseline

Latest local validation on 2026-09-11, from baseline `cc700412f387e8680720584016dbd4f023ebf2a4` plus the unified Action Queue diff:

```text
PYTHONPATH=/tmp/group-test-tracker-test-deps-20260910 /home/sbachman/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -B -m unittest
149 tests passed in 158.283s
```

This local result is recorded in project history but is not backed by a GitHub Actions check. The provider/network paths use mocks; production credentials and the real-report evaluation corpus were not exercised.

Required validation by change type:

| Change | Minimum validation |
| --- | --- |
| Models or migrations | `tests.test_schema_migration` plus affected feature tests |
| Authentication, authorization, routes, or templates | `tests.test_security` plus focused affected tests |
| Notifications or provider transport | `tests.test_notifications` and provider-focused security tests |
| Storage or uploaded media | `tests.test_storage` and authorization tests |
| Participation or costs | `tests.test_participant_removal`, `tests.test_lab_costs`, and affected security tests |
| Documentation only | Link/path inspection and `git diff --check` |
| Release candidate | Full `python -m unittest` and automated CI when available |

Record future results with the exact command, pass/fail count, date, environment, and commit SHA. Do not replace a failed result with a later pass without preserving the failure and its resolution in project history.

## Known Risks

- GTM does not yet parse or enforce the control-plane entitlement/subscription contract; deploying paid plans before these guards exist would rely only on removable workers and UI state.
- GTM has no signed control-plane command/status API, automated hash-based administrator bootstrap, immutable support identity, session epoch, or DigitalOcean-ready health endpoint.
- Three long-lived branches create drift and Alembic collision risk. Keep `main` fixes flowing one-way through `SaaS-Test` to `SaaS-Main`, protect the production branch, and record the exact common baseline before branch creation.
- The current per-test export contains participant identity/payment data and cannot serve suspended recovery unchanged; the dedicated sanitized export is a security requirement.

- The current branch has no automated GitHub verification signal.
- Real provider accuracy, latency, cost, and retention behavior still require fixture evaluation with production-like credentials before automatic analysis is enabled.
- Runtime databases, notification logs, Python bytecode, and a debug script are tracked in the repository.
- Telegram animation validation recognizes GIF signatures and MP4 `ftyp` markers but does not fully parse or transcode media containers.
- Some outbound delivery remains synchronous or process-local and can be lost on process termination.
- The large `app/routes.py` and shared configuration table concentrate responsibilities and raise regression risk.
- Discord dynamic commands still inherit Telegram-oriented persistence names and incomplete provider-specific coverage.
- Historical validation was run across mixed Windows and Linux command environments.
- Telegram COA review delivery is still an external API operation; a failed notification can leave an analysis run in `needs_review` until delivery is retried.
- Inline report rendering depends on the browser being able to display the secured PDF/image response; the authenticated open-report link remains available as fallback.
- Telegram tag keyboards can become large as the shared tag catalog grows; pagination may be needed for larger catalogs.
- Staged source uploads are stored before approval and require cleanup on cancellation, replacement, or rejection; failed cleanup can leave an orphaned object.

## Change Protocol

Before editing:

1. Review this map and the relevant implementation and tests.
2. Identify target files, intended behavior, assumptions, risks, and validation commands.
3. Prefer the smallest compatible change and preserve existing authorization boundaries.

After each edit phase:

1. Update implemented capabilities, priorities, risks, or validation status here when they materially change.
2. Append detailed chronological notes to `docs/project-history.md` when the change needs an audit trail.
3. Run focused validation before broad validation.
4. Record exact results and remaining risks.

## Current Change Record

### SaaS Branches and Settled Entitlement Contract

- **Date:** 2026-09-13
- **Project map before changes:** SaaS integration was mapped against `main`, but the application repository/branch source, Discord boundary, analysis downgrade behavior, suspended export scope, signing scheme, and support display identity remained open.
- **Planned edits:** Set isolated SaaS release lanes and convert all six user decisions into enforceable route/service/worker/deployment and validation requirements without creating branches or application code.
- **Applied edits:** Reserved `SaaS-Test` for development and `SaaS-Main` for customer deployments while leaving `main` clients unchanged; defined complete Discord gating, zero analysis queueing without entitlement, terminal downgrade cancellation, strict suspended-admin recovery, a sanitized test-only export, per-direction Ed25519/JWS authentication and rotation, and the immutable `gtmsupport` identity.
- **Security review:** The existing workbook was identified as unsuitable for recovery because it exports participant identity/payment data. The map now requires an allowlisted recovery surface, service-level notification/provider backstops, pinned asymmetric signatures, replay defense, and conflict-safe support-account provisioning.
- **Reliability review:** Branch promotion, one-way mainline fixes, entitlement revision ordering, idempotent queue cancellation, stale-worker checks, no automatic re-upgrade resume, and key-overlap rotation are explicit.
- **Optimization review:** Feature checks stay process-local; no per-request control-plane dependency is introduced; workers remain absent when unentitled; replay data is bounded; and the recovery export is streamed/bounded.
- **Validation:** Read the current connector-visible project maps and `app/export.py`; planning-only changes were published to the project map. No branch, executable code, migration, or deployment was created.
- **Remaining action:** Update the control-plane map to the same contract, then create/protect the branches only when implementation is explicitly authorized.


### SaaS Control-Plane GTM Change Map

- **Date:** 2026-09-13
- **Project map before changes:** The GTM map described the standalone application and current feature priorities but did not enumerate the code, schema, process, trust, lifecycle, support, or validation work required by the new SaaS control plane.
- **Planned edits:** Compare the control-plane contract with current GTM models, routes, templates, workers, CLI commands, deployment files, and tests; then add a sequenced implementation map without changing application code.
- **Applied edits:** Updated the connector-visible `main` baseline and added managed/standalone compatibility, environment/trust contracts, subscription semantics, file-level work packages, signed internal operations, idempotent administrator bootstrap, immutable support account, documentation/support flow, health/readiness, migrations, deployment behavior, cross-repository tests, sequencing, open decisions, and current risks.
- **Security review:** Mapped directional request signing, replay/idempotency protection, strict audience/version checks, hash validation, immutable system identity, server-side feature enforcement, session invalidation, canonical URLs, and secret/logging boundaries.
- **Reliability review:** Mapped desired/actual revisions, stale-worker refusal, retry-safe operations, schema/readiness gates, standalone compatibility, recovery access, contract fixtures, and Admin Action escalation.
- **Optimization review:** Entitlements are parsed once per process, checks are local/indexed, no per-request control-plane dependency is introduced, and network calls are limited to explicit support/documentation operations.
- **Validation:** Read both repositories and the current `main` GTM implementation through the GitHub connector, including the project maps, application factory/CLI, User model, authentication/user-management routes, Discord and analysis workers, Settings/profile/user templates, deployment files, environment example, and current tests. Documentation-only planning change; no executable code or migration was changed or run.
- **Remaining action:** Resolve the six GTM contract decisions, freeze shared fixtures in both repositories, and then implement in the recommended sequence.

- **Date:** 2026-09-11
- **Scope:** Make the Admin Action Queue the central inbox for result-analysis review and operational attention.
- **Target files/modules:** Action Queue query/rendering in `app/routes.py` and `app/templates/admin/action_queue.html`, result-analysis route coverage, administrator documentation, and this project map.
- **Intended behavior:** Show result-analysis runs in `needs_review` and unacknowledged `failed` states alongside existing pending participation requests, link directly to review/failure details, and remove resolved or acknowledged runs automatically.
- **Assumptions:** `needs_review` requires approval and `failed` requires intervention; queued/analyzing work does not require administrator action yet.
- **Security risks/checks:** Preserve the existing administrator-only route boundary, escape provider/error text, and expose no new actions without existing CSRF controls.
- **Reliability risks/checks:** Avoid hiding analysis attention behind participation filters, preserve both pagination states across participation actions, and ensure applied/resolved runs disappear.
- **Optimization checks:** Paginate analysis attention independently at 25 rows and eager-load target/finding relationships to prevent N+1 database queries.
- **Validation plan:** Focused result-analysis and action-queue tests, full unittest discovery, template rendering, and `git diff --check`.
- **Applied changes:** Added an independently paginated Result Analysis section; surfaced review-ready and unacknowledged failed runs regardless of participation filters; added direct review/inspection links; added an administrator-only, CSRF-protected failure acknowledgment action; and preserved both pagination states across participation actions.
- **Security/reliability/optimization review:** The Action Queue and acknowledgment endpoint remain administrator-only; acknowledgment is POST-only and CSRF-protected; provider/error strings remain auto-escaped; acknowledged failures retain their failed status and audit metadata; and eager loading plus 25-row pagination bounds database and rendering work.
- **Validation:** Focused result-analysis and participation suites passed 26 tests in 32.336s; full discovery passed 149 tests in 158.283s; the final pagination-context adjustment passed its two targeted tests; and `git diff --check` passed. Existing deprecation warnings remain.
- **Product invariant:** Any present or future state requiring administrator approval or attention must surface in the Admin Action Queue until resolved.

## Tonight's Change Record

- **Date:** 2026-09-11
- **Scope:** Implement, debug, and document the Telegram `/submitcoa` submission/review workflow and improve dedicated Public Result navigation and report display.
- **Target files/modules:** `app/routes.py`, `app/notifications.py`, `app/result_analysis/jobs.py`, `app/telegram_result_review.py`, `app/templates/public_result_detail.html`, and related result-analysis/storage behavior.
- **Intended behavior:** Linked Telegram users can submit a COA; administrators receive a review message, set a result name, review findings, and approve or reject; replies work in private chats and configured group/forum threads; published Public Results expose their attached report on the dedicated page.
- **Security risks/checks:** Preserve linked-user and administrator checks, configured chat/thread scope checks, authenticated result access, signed storage URLs, CSRF boundaries, and no secret disclosure in diagnostics.
- **Reliability risks/checks:** Keep analysis committed before notification; retain `needs_review` state when Telegram delivery fails; log the underlying notification exception; normalize sentinel IDs; avoid crashes from stale reply, edit, or delete message references.
- **Optimization checks:** Reuse the existing result-image access route and file-kind helper; avoid duplicating report storage or download logic; bound Telegram callback/reply text and existing review message content.
- **Applied changes:** Added `/submitcoa` attachment/link intake and queued analysis handoff; added Telegram interactive review state and approval/rejection workflow; added worker traceback logging; normalized optional thread/message IDs; moved review reply handling before non-private command filtering; displayed callback notices; added resilient prompt/review-message correlation; and added Public Result back navigation plus inline PDF/image rendering.
- **Validation:** `python -m py_compile app/routes.py app/notifications.py app/telegram_result_review.py app/result_analysis/jobs.py` passed; `git diff --check` passed for the dedicated page change. Full suite validation was not performed for this documentation update.
- **Remaining follow-up:** Add focused webhook tests for `/submitcoa`, group/forum-thread replies, callback notices, name persistence, and inline Public Result report rendering; provide an explicit retry path for review notifications that remain in `needs_review`.

## Follow-up Change Record: COA Source and Tag Review Controls

- **Date:** 2026-09-11
- **Scope:** Make the Telegram COA review source visible and allow selection of existing Public Result tags before approval.
- **Target files/modules:** `app/telegram_result_review.py`, `Tag`/`PublicResult` relationships in `app/models.py`, and the result-analysis review state.
- **Intended behavior:** Link-based reviews expose the submitted link; uploaded image/PDF reviews retain their stored source; administrators can toggle existing tags and approved results receive only the selected tag relationships.
- **Security risks/checks:** Do not create arbitrary tags from Telegram input; resolve selections only against existing `Tag` records and retain administrator-only callback authorization.
- **Reliability risks/checks:** Persist tag choices in review state before approval, preserve source fields through review, and keep source access behind the existing authenticated result/storage routes.
- **Optimization checks:** Load the existing tag catalog for the review keyboard and avoid new storage downloads or duplicate source records.
- **Applied changes:** Added source labeling, submitted-link button support, existing-tag toggle buttons, review-state tag persistence, and approval-time tag assignment.
- **Validation:** `python -m py_compile app/telegram_result_review.py app/routes.py app/notifications.py` and `git diff --check -- app/telegram_result_review.py` passed.
- **Remaining risk:** Very large tag catalogs may require paginated Telegram tag selection in a later refinement.
- **Public Results fix:** Telegram tag result buttons now fall back to the authenticated dedicated Public Result page when a published certificate has no external `results_link`, preventing Telegram from rejecting a keyboard containing a null URL.
- **Validation:** Image-only certificate tag navigation and linked-user Public Results behavior passed two focused security tests in 2.322s on 2026-09-11.
- **Diagnostics:** Telegram API failures now write bounded single-line method/error details to the notification log; Public Results edit failures also include chat, message, tag, and page context, and Telegram shows a callback alert.
- **Recovery:** If Telegram rejects editing the callback message, Public Results now sends the rendered page as a fresh message; callback pagination also preserves the originating forum-thread ID.
- **Confirmed root cause:** Bot-created results could store `results_link` as `#`; this truthy placeholder bypassed the fallback and Telegram rejected it with `URL '#' is invalid: URL host is empty`. `#` is now treated as an unset link.
- **Public Result form:** The results link is optional when an image/PDF is uploaded; create and edit flows reject a record only when it would have neither a link nor a file.

## Follow-up Change Record: Paginated Tags and Dual COA Sources

- **Date:** 2026-09-11
- **Scope:** Replace the flat Telegram tag button list with a paginated submenu and allow review-time addition of the complementary COA source.
- **Target files/modules:** `app/telegram_result_review.py`, Telegram webhook dispatch in `app/routes.py`, and result-analysis review state.
- **Intended behavior:** Show ten existing tags per page with Save/Cancel controls; preserve the initial COA link or file while allowing an administrator to add, replace, remove, or retain the other source before publishing.
- **Security risks/checks:** Tag callbacks resolve only existing database tags; source links remain administrator-controlled review state; uploaded files use existing bounded Telegram download and storage validation; review authorization and destination matching remain unchanged.
- **Reliability risks/checks:** Source changes are staged in review JSON; approval applies both fields atomically with the result publication state; cancel/reject removes newly uploaded draft objects on a best-effort basis.
- **Optimization checks:** Tag queries are paginated in the Telegram keyboard at ten records per page; source editing reuses the existing storage upload path and does not duplicate analysis until approval.
- **Applied changes:** Added tag submenu pagination, tag draft toggles, Save/Cancel callbacks, source submenu controls, link reply prompts, attachment reply prompts, staged source fields, and approval-time dual-source persistence.
- **Validation:** `python -m py_compile app/routes.py app/telegram_result_review.py app/notifications.py` and `git diff --check -- app/routes.py app/telegram_result_review.py` passed.
- **Remaining risk:** Staged object cleanup is best effort; focused Telegram webhook tests and an explicit cleanup/retry mechanism remain recommended.
- **Test coverage added:** Result-analysis tests now cover name-required approval, name persistence, paginated tag Save state, dual-source link/file approval, and dedicated Public Result PDF rendering.
- **Validation limitation:** Test collection is currently blocked in the active environment because `Pillow` is missing; the repository declares `Pillow>=10.4.0` in `requirements.txt`. Compilation and diff checks pass.
