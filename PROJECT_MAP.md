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
   - Implement the managed/standalone boundary, subscription/entitlement enforcement, signed control-plane API, provisioning bootstrap, support account, role-filtered public documentation links, health contract, and lifecycle tests described below.
   - Freeze cross-repository contracts before writing either side so provisioning, retries, revisions, and failure behavior remain compatible.

## Planned SaaS Control-Plane Compatibility

**Status:** Planning complete enough to estimate and sequence; no SaaS integration code or migration has been implemented.

### Compatibility and ownership rules

- Add an explicit `GTT_DEPLOYMENT_MODE=standalone|managed` boundary. Default to `standalone` so existing self-hosted and manually managed deployments keep their current behavior.
- In `managed` mode, the control plane owns subscription state, canonical tenant identity, entitlement revisions, infrastructure lifecycle, support-account coordination, canonical public documentation destinations, and one-time initial administrator bootstrap. After bootstrap, GTM exclusively owns all of its users, group tests, results, participant payments, tenant configuration, and customer-supplied bot/AI/email/storage credentials; the control plane must not become an alternate GTM administration surface.
- Never scatter environment reads or plan-name comparisons through routes and templates. One typed entitlement service must parse, validate, expose, and test the complete contract.
- Client-side hiding is informative only. Route, service, CLI, bot-command, notification, and worker checks are authoritative.
- Keep the two products' action queues separate: GTM's Admin Action Queue contains test/result/participant and other tenant-application work; the control plane's operator queue contains billing, provisioning, infrastructure, backup, domain, and support-access coordination only. Never copy routine GTM business records into the control plane.

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
| `GTT_USER_DOCUMENTATION_URL` | Canonical public user-guide URL on `grouptest.online` | Validate HTTPS/approved origin; hide an invalid link |
| `GTT_ADMIN_DOCUMENTATION_URL` | Canonical public administrator-guide URL on `grouptest.online` | Validate HTTPS/approved origin; ordinary users never see this link |
| `GTT_PUBLIC_URL` | Canonical tenant origin for generated links | Readiness warning; never trust an arbitrary Host header |
| `GTT_CP_TO_INSTANCE_SECRET`, `GTT_CP_TO_INSTANCE_KEY_ID` | Verify control-plane commands | Readiness fails for managed mutation endpoints |
| `GTT_INSTANCE_TO_CP_SECRET`, `GTT_INSTANCE_TO_CP_KEY_ID` | Sign the few GTM-originated callbacks/status acknowledgements | Outbound synchronization queues safely; ordinary GTM use remains local |

- Provision two independent random 256-bit HMAC-SHA256 secrets per tenant, one for each direction. A compromised tenant secret therefore cannot authenticate another tenant or reverse the allowed direction. Store secrets only as DigitalOcean encrypted variables on GTM and encrypted values in the control plane.
- Canonical signatures cover key ID, tenant ID, contract version, HTTP method, canonical path, timestamp, nonce, operation ID, requested revision, and SHA-256 body digest. Maximum request lifetime is 120 seconds, accepted clock skew is 60 seconds, used nonces are retained for at least 10 minutes, and comparisons are constant-time.
- Rotation keeps only current and previous secrets. Deploy the receiver with both, switch the sender to the new key ID, verify traffic, and remove the previous secret within 24 hours. Reject unknown key IDs, wrong tenant/direction/version, stale timestamps, replay, body/path mismatch, and stale revisions.
- Keep the communication surface deliberately small. Control plane to GTM is limited to initial administrator/support bootstrap, support enable/rotate/disable, and detailed status requests. GTM to control plane is limited to support-request/emergency-disable reconciliation and bounded status acknowledgements. Entitlements arrive through environment deployments; ordinary page requests, GTM user management, tests, results, settings, and notifications never call the control plane.
- Add a contract-version setting and publish accepted versions in signed detailed status so incompatible control-plane/GTM deployments fail before mutation.
- Keep every secret out of templates, diagnostics, health responses, audit payloads, URLs, and process command arguments.

### Subscription and entitlement behavior

- `standalone`: preserve all existing capabilities and configuration paths.
- `active` and `trialing`: enable only the supplied entitlements. Trial add-ons work only when explicitly included.
- `grace`: retain the current paid feature set, show a persistent billing warning to administrators, and link to the control-plane billing page.
- `suspended` and post-term `canceled`: block ordinary users. Tenant administrators enter a server-side allowlisted recovery shell: they may view existing group-test lists/details/results without mutation, download a new sanitized test/results export, open Support/billing, manage their own session, and log out. They cannot create, edit, delete, transition, approve, pay, or otherwise mutate tests/participants/results; export the user directory or participant identity/payment/notes data; send email, Telegram, Discord, Root, digest, webhook, or bot notifications; run bot commands/synchronization; or start provider/analysis work.
- Implement suspension as an allowlist, not a denylist, so future routes default blocked. GET routes admitted to recovery must be side-effect free, and every notification/provider service must independently enforce suspension as a final backstop.
- The existing `generate_test_export` workbook includes participant names, Telegram usernames, verification/payment state, and notes and therefore must not be exposed in recovery. Add a distinct bounded recovery export containing test metadata, test configuration/costs, result rows, source references, and relevant test audit timestamps, but no user directory, participant rows, contact identifiers, bot identifiers, credentials, or account exports.
- Environment state remains authoritative. Every entitlement revision causes a full App Platform restart, and all processes must report the same loaded revision. Downgrades preserve settings/history but use a first deployment that removes the entitlement while retaining the restarted, now-idle worker; only after readiness confirms the revision does a second deployment remove the worker. Upgrades add entitlement and worker in one App spec and become operational only after readiness.
- `discord_bot` gates the entire Discord surface: gateway worker startup/handlers, linking tokens and claims, command registration/synchronization/execution, Discord settings/test actions, outbound Discord webhooks/notifications, and Discord as a selectable user notification channel. Without entitlement, saved configuration remains but cannot be edited or used; existing Discord channel preferences remain stored but delivery is suppressed and is never silently rerouted.
- Without `result_analysis`, no `ResultAnalysisRun` may be inserted by upload hooks, manual Analyze, Retry, provider tests, public-result paths, or Telegram `/submitcoa`. During downgrade deployment 1, an idempotent pre-deploy reconciliation marks queued/retry-scheduled work terminal as `canceled_entitlement`, clears leases, and records revision/reason. The retained worker restarts without entitlement and remains idle; deployment 2 removes it. Already in-flight work has a bounded DigitalOcean drain-window race, so persistence rechecks the process entitlement and normal downgrades occur at billing boundaries.
- Re-upgrade never resumes `canceled_entitlement` runs. After entitlement returns, an administrator must explicitly create a new analysis; historical runs/findings remain readable.

### GTM implementation work packages

| Work package | Primary files/modules | Required change |
| --- | --- | --- |
| Entitlement kernel | new `app/entitlements.py`, `app/__init__.py`, `app/routes.py` | Typed environment contract parsing, deployment mode, immutable loaded revision, component readiness/status, feature/status checks, decorators/service guards, Jinja context, upgrade URLs, and safe diagnostics |
| Subscription UX | `app/templates/base.html`, new subscription/recovery templates, admin Settings templates, `app/export.py` or a focused recovery-export module | Plan/status banner, locked cards with upgrade actions, grace messaging, server-side suspended-admin route allowlist, and a sanitized test/results-only recovery export |
| Discord enforcement | `app/discord_bot.py`, `app/routes.py`, `app/notifications.py`, `app/templates/profile.html`, `app/templates/admin/bot_integrations.html` | Guard startup, synchronization, handlers, linking, saves/tests, and any in-scope outbound delivery while preserving stored configuration |
| Analysis enforcement | `app/result_analysis/jobs.py`, `app/result_analysis/service.py`, analysis routes, `_result_analysis_card.html`, `result_analysis_config.html` | Prevent automatic/manual queueing, claims, retries, provider tests, and paid mutations while retaining readable history and data |
| Support and documentation | new focused support blueprint/service/templates plus `base.html` | Logged-in Support tab, role-filtered links to public user/admin guides, owner-configured external helpdesk link, and support-access request/status |
| Managed system account | `app/models.py`, a focused user-management service, auth/user routes, CLI commands, user/profile templates | Immutable reserved support identity; tenant-consented control-plane enable/rotation; tenant-local emergency disable/expiry; and immediate session invalidation |
| Control-plane API | new isolated internal blueprint/service | Signed versioned commands, bootstrap, support lifecycle, status, replay defense, idempotency, bounded audit, and JSON-only error contracts |
| Provisioning readiness | `app/__init__.py`, `app/version.py`, new health/status service | Public minimal liveness/readiness plus signed detailed status reporting application, schema, contract, tenant, entitlement, and support revisions |
| Schema | `app/models.py`, new additive Alembic revisions | System-account/auth fields and durable command receipts/audit records, compatible with shared DigitalOcean MySQL and SQLite tests |
| Deployment contract | `app/__init__.py`, `Procfile`, `.env.example`, `README.md`, `ADMIN_QUICK_START.md` | Managed variables, component identity and bounded SQLAlchemy pool settings, pre-deploy migration/entitlement reconciliation, conditional workers, bootstrap, recovery, and troubleshooting |
| Validation | new focused test modules plus existing security/result-analysis/notification/schema suites | Cross-product state matrix, tamper/replay tests, stale-worker tests, migration tests, UI locks, standalone compatibility, and control-plane contract tests |

### Internal control-plane interface

- Isolate endpoints under a versioned internal blueprint such as `/internal/control-plane/v1`; do not add these mutations to the already-large general route module.
- Verify the directional HMAC-SHA256 contract above over the exact HTTP method, canonical path, timestamp, nonce, operation ID, tenant ID, revision, contract version, and SHA-256 body digest. Reject unknown/retired key IDs, more than 60 seconds of clock skew, requests older than 120 seconds, replay, wrong tenant/direction, browser session credentials, and non-JSON mutation bodies.
- Exempt only this internal blueprint from CSRF because it does not use browser cookies; all ordinary GTM forms retain CSRF protection.
- Persist a unique operation ID, payload hash, requested revision, outcome, and bounded response summary. Replaying the same operation and payload returns the prior result; reusing an ID with a different payload is rejected.
- Initial-administrator bootstrap creates exactly the requested username and email once from the control-plane-produced, versioned Werkzeug scrypt hash. Validate the encoded scheme/length, reject username/email collisions, never pass the hash on a process command line, and never expose it in a response or log. Return an idempotent success receipt so the control plane can erase its staged encrypted hash; after bootstrap, all administrator management and password changes belong only to GTM.
- Support lifecycle accepts only the reserved support identity and monotonically increasing revisions. It may create the account disabled, rotate its validated hash, enable it only after fresh tenant-admin consent, disable it, increment its authentication epoch, and report actual state; it cannot edit arbitrary users. Enablement expires automatically after 24 hours. A GTM administrator may emergency-disable it locally and revoke its sessions even if the control plane is unavailable, then queue reconciliation.
- A signed status endpoint returns only bounded operational metadata: application version, Alembic revision, supported contract versions, tenant ID, loaded entitlement revision/status, component readiness, support-account actual revision/state/expiry, aggregate tenant schema bytes, and aggregate database-pool health. It never returns GTM users, tests, results, action items, settings, credentials, or row-level data.
- Add minimal unauthenticated liveness/readiness endpoints suitable for DigitalOcean health checks without tenant data, exception text, configuration values, or secrets.

### Immutable support-account design

- Add nullable unique `system_account_key`, `auth_epoch`, and control-plane credential/state revision fields to `User`; reserve `control_plane_support` independently of username or email.
- The managed account is displayed as username `gtmsupport` with internal email `support@grouptest.online`. Reserve both identities case-insensitively after the same normalization used by authentication, but authorize exclusively through `system_account_key`.
- Managed provisioning creates the support identity disabled with administrator role and notifications/bot identities off. Standalone deployments do not create it automatically. If a pre-existing ordinary account conflicts with the reserved username or email, never adopt or overwrite it: leave managed support disabled, return a bounded conflict, and route an Admin Action for operator resolution.
- Centralize user mutations so registration, ordinary admin creation/edit/toggle/reset, public reset, self-profile/password changes, bot-link creation/claim, imports, `create-admin`, `demote-admin`, and future deletion reject system-managed accounts.
- Hide ordinary Edit, Reset, Activate/Deactivate, and future Delete controls, but treat server-side rejection as the security boundary.
- Prevent ORM/service deletion of the system account. Direct database-owner repair remains possible and must be audited operationally.
- Bind authenticated sessions to `auth_epoch`; disabling or rotating the support account invalidates all of its existing sessions on the next request. Maintain backward compatibility for ordinary pre-migration sessions or deliberately invalidate them once during rollout.

### Support and public-documentation flow

- Add a Support navigation item for every authenticated GTM user. It is the only in-application place that presents documentation/helpdesk links.
- Documentation pages are public on the control plane. Ordinary authenticated GTM users see only the public user-guide link; GTM administrators see both public user and administrator guide links.
- Role-based link display is a local GTM navigation rule, not cross-system authorization. Do not create signed documentation assertions, transmit GTM identities/roles to the control plane, or append tenant/user data to guide URLs.
- Validate documentation and helpdesk destinations against HTTPS and configured/approved origins. Before configuration, show a safe unavailable state; never redirect to an arbitrary database/user-supplied URL.
- The external hosted helpdesk maintains separate portal accounts and receives no GTM password, support credential, signed token, or automatic user/test data.
- The GTM support control requests access from the control plane only after fresh administrator consent, shows the 24-hour expiry and pending/actual state, and uses retry-safe operations. Emergency disable acts locally first, revokes support sessions immediately, and queues a signed reconciliation callback; local enable remains prohibited.

### Migration, deployment, and release behavior

- Add forward-only Alembic revisions; never modify historical migrations. Test from both an empty database and the current production head on MySQL-compatible behavior.
- The migration adds schema only. The signed managed-provisioning operation creates the reserved support account, avoiding an unowned credential in standalone databases.
- Keep the existing manual `create-admin` command for standalone use, but route it through the same system-account protections. Managed bootstrap uses the signed internal operation.
- DigitalOcean performs `flask --app app db upgrade head` as a pre-deploy job before web/worker activation. GTM readiness must report the expected schema before the control plane marks a deployment healthy.
- Web, Discord, and analysis processes all load the same immutable entitlement revision at startup. Runtime changes arrive only through a full App Platform configuration deployment/restart; readiness reports each component's revision and blocks lifecycle progression on mismatch. No process persists a competing entitlement set.
- Source repository is settled as `sbchmn/Group-Test-Tracker`. Existing manually managed customers remain on `main`, and SaaS-only code/migrations must never be merged there merely to deploy the SaaS product.
- When implementation is authorized, create case-sensitive branches `SaaS-Test` and `SaaS-Main` from the same re-read, recorded `main` commit and tag that commit with a dated SaaS baseline. This planning change does not create either branch.
- All SaaS development lands in `SaaS-Test` and deploys to the existing development test application. Promotion is a reviewed, tested PR from `SaaS-Test` to protected `SaaS-Main`; customer DigitalOcean applications track `SaaS-Main` only.
- Apply future fixes from `main` one way into `SaaS-Test`, resolve Alembic revision collisions there, validate, then promote to `SaaS-Main`. Never back-merge SaaS-only commits or migrations into `main` accidentally.
- Protect `SaaS-Main` from direct pushes and require the full suite, contract tests, migration checks, and a healthy real DigitalOcean `SaaS-Test` deployment before promotion. The control plane does not monitor the development test app in the MVP.

### Security, reliability, and optimization review

- **Security:** Preserve existing admin/participant authorization beneath feature gates; use independent per-tenant directional HMAC-SHA256 secrets, validate canonical request fields/version/key lifecycle, retain bounded replay records, compare signatures in constant time, enforce the suspended recovery allowlist and sanitized export, preserve immutable system identity/session epochs/canonical URLs, and redact bounded logging.
- **Reliability:** Make bootstrap/support commands and pre-deploy cancellation idempotent, distinguish desired from component-reported revisions, require full restarts, keep the unentitled worker idle before removal, fail closed without breaking Core diagnostics, commit before acknowledging, expire support access locally, and surface tenant work only in GTM's queue while infrastructure/billing failures remain in the control-plane queue.
- **Optimization:** Parse immutable environment state once per process, use constant-time feature sets, bound SQLAlchemy pools by component role, index operation IDs/system keys/revisions, avoid per-request control-plane calls, render public documentation links locally, and synchronize only bootstrap, support, revision/readiness, and bounded aggregate status events.

### Validation plan

- Add `tests/test_entitlements.py` for standalone compatibility and the full status × feature matrix, including recovery-route allowlisting and default denial of newly added routes.
- Add `tests/test_control_plane_api.py` with shared deterministic HMAC fixtures for wrong direction/tenant/key ID, current/previous rotation overlap and retirement, 60-second skew, 120-second lifetime, replay, payload mismatch, idempotency, bootstrap collisions, stale revisions, safe errors, bounded aggregate status, and absence of GTM business data.
- Add `tests/test_support_access.py` for every admin/self-service/reset/link/CLI/delete mutation path, role immutability, fresh-consent enablement, 24-hour automatic expiry, local emergency disable while the control plane is unavailable, reconciliation, credential rotation, session invalidation, public guide visibility by GTM role, safe unavailable states, and URL allowlisting.
- Extend `tests/test_result_analysis.py`, `tests/test_notifications.py`, `tests/test_security.py`, `tests/test_export.py`, and `tests/test_schema_migration.py` for zero queue inserts without entitlement, deployment-1 cancellation/idle behavior, deployment-2 removal contract, revision mismatch, bounded in-flight drain races, no re-upgrade resume, Discord gates, suspended denial, sanitized exports, MySQL 8.4-safe migrations, and standalone behavior.
- Add component-aware database tests and a load budget for the two-process Gunicorn web service plus Discord/analysis workers. Explicitly set pool size/overflow/recycle/pre-ping from validated environment rather than relying on SQLAlchemy defaults.
- Add cross-repository contract fixtures so the control plane and GTM test the same environment schema, signature canonicalization, command/status JSON, entitlement identifiers, and supported contract versions.
- Before production, test Core, Discord, AI, Complete, trial, grace, upgrade, downgrade, suspension, recovery/export, stale worker, failed bootstrap, and support rotation in a real DigitalOcean test application.

### Recommended implementation sequence

1. When implementation is authorized, re-read `main`, record/tag the exact baseline, create `SaaS-Test` and `SaaS-Main` from it, and configure protections/deployment targets without changing existing `main` clients.
2. Freeze the shared directional HMAC, environment, bootstrap-hash/receipt, bounded status, recovery-export, and operation fixtures in both repositories.
3. Add additive schema, the entitlement kernel, recovery allowlist, and standalone-compatibility tests on `SaaS-Test`.
4. Add signed internal status/bootstrap operations and DigitalOcean readiness checks.
5. Add immutable support identity, session epochs, Support page, and locally role-filtered public documentation/helpdesk links.
6. Gate all Discord and result-analysis queue/provider/notification surfaces and add downgrade reconciliation.
7. Validate MySQL 8.4 migrations, component connection budgets, full-restart revisions, two-deployment downgrades, and the lifecycle in the real `SaaS-Test` app, then promote by PR to protected `SaaS-Main`.

### Settled SaaS implementation decisions

1. DigitalOcean deploys `sbchmn/Group-Test-Tracker`: customer SaaS apps track `SaaS-Main`, development testing uses `SaaS-Test`, and current non-SaaS clients remain on `main`.
2. `discord_bot` covers the gateway worker, commands/linking/settings, Discord webhooks/notifications, and the Discord user notification channel.
3. Analysis is never queued without `result_analysis`; environment changes restart the entire app, downgrade deployment 1 cancels pending work and idles the retained worker, deployment 2 removes it, and re-upgrade never automatically resumes canceled work.
4. Suspended tenant administrators have only the explicit read-only test/results, sanitized test export, billing/support, session, and logout surface described above; user/participant exports, mutations, delivery, bot, and provider operations are blocked.
5. Cross-repository authentication uses two independent per-tenant directional HMAC-SHA256 secrets with key IDs, a 60-second clock-skew allowance, 120-second maximum request lifetime, one-time nonces retained for 10 minutes, and current/previous rotation with the prior secret removed within 24 hours.
6. The immutable support identity is `gtmsupport` / `support@grouptest.online`, authorized only by `system_account_key=control_plane_support`; enablement requires fresh tenant-admin consent, expires after 24 hours, and can be emergency-disabled locally.

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
- Current SQLAlchemy configuration sets pre-ping/recycle but leaves default pool size/overflow in place; with two Gunicorn processes plus Discord/analysis processes, a Complete tenant can theoretically consume most connections on a small shared MySQL node. SaaS deployment requires explicit component pool budgets and a control-plane capacity gate.
- Environment-only entitlement enforcement intentionally accepts a bounded deployment drain-window race for work already in flight; the two-deployment downgrade sequence cannot provide instantaneous revocation.
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

### KISS Communication and Strict Product Boundary

- **Date:** 2026-09-13
- **Project map before changes:** The map used an asymmetric JWKS/JWS key service and left support/status synchronization broad enough to blur control-plane and GTM ownership.
- **Planned edits:** Reduce cross-application machinery while preserving tenant isolation, replay resistance, emergency support shutdown, and the environment-authoritative subscription model.
- **Applied edits:** Replaced Ed25519/JWKS planning with independent per-tenant directional HMAC-SHA256 secrets and current/previous rotation; restricted network operations to bootstrap, support, revision/readiness, and bounded aggregate status; made initial-admin bootstrap one-time with hash-erasure acknowledgement; added fresh-consent 24-hour support access and local emergency disable; explicitly separated the two Admin Action Queues and prohibited GTM business data from status.
- **Security review:** Directional tenant-scoped secrets constrain compromise, canonical body/path signatures prevent substitution, nonces/timestamps prevent replay, constant-time checks prevent timing comparison leaks, and status cannot expose row-level tenant data.
- **Reliability review:** GTM remains usable without a live control plane for ordinary work. Support expiry and emergency disable are enforced locally; signed retries are idempotent; entitlements remain deployment environment state.
- **Optimization review:** There is no per-request control-plane dependency, JWKS service, or public-key lifecycle. Synchronization is event-driven and bounded.
- **Validation:** Re-read the current GTM map and matched its environment, operation, bootstrap, support, status, and lifecycle contracts to the control-plane map. Planning-only update; no code, branch, migration, or deployment changed.
- **Remaining action:** Freeze deterministic cross-repository HMAC fixtures before implementing on `SaaS-Test`.


### Environment-Authoritative Lifecycle and Database Capacity

- **Date:** 2026-09-13
- **Project map before changes:** The map required stale workers to stop but did not define how environment-only entitlements restart all processes, and it did not account for SQLAlchemy default pools across the two-process web service plus paid workers.
- **Planned edits:** Mirror the approved control-plane lifecycle without introducing a GTM database entitlement authority, and make shared-MySQL capacity a first-class SaaS requirement.
- **Applied edits:** Defined full-restart entitlement revisions, atomic upgrade deployment, two-deployment downgrade/cancellation/idle/removal behavior, component revision readiness, bounded drain-window semantics, component-aware pool configuration, connection/load tests, and MySQL 8.4 validation.
- **Security review:** Paid work remains guarded at queue, provider, and persistence boundaries; no process or database row can grant an entitlement absent from the deployed environment.
- **Reliability review:** All retained components must restart/report the target revision before worker removal; analysis cancellation is idempotent; revision mismatch blocks progression; already in-flight work is an explicit bounded risk.
- **Optimization review:** Explicit pool/overflow budgets replace unsafe defaults and let the control plane cap tenants using real cluster connection headroom.
- **Validation:** Reviewed current GTM engine options and Procfile through the connector: only pre-ping/recycle are configured and Gunicorn runs two worker processes. Planning-only update; no code, branch, migration, or deployment changed.
- **Remaining action:** Implement and benchmark the pool/revision contract on `SaaS-Test` after branch creation is authorized.


### Public Documentation and Control-Plane Boundary Alignment

- **Date:** 2026-09-13
- **Project map before changes:** GTM planned signed, access-controlled documentation assertions even though the revised control-plane product makes both guide sets public.
- **Planned edits:** Remove unnecessary cross-system documentation authentication while preserving role-appropriate discovery inside GTM and the signed support-account control contract.
- **Applied edits:** Made user/admin guides public control-plane destinations; limited their in-GTM presentation to the authenticated Support page; ordinary users see only the user guide and GTM administrators see both; removed documentation assertions and identity transfer; retained HTTPS/origin validation and safe unavailable states.
- **Security review:** GTM sends no identity, role, tenant ID, signed token, or query data to public documentation. Role filtering is presentation, not authorization; arbitrary redirect destinations remain blocked.
- **Reliability review:** Links require no live control-plane call and fail safely when unconfigured. Support-account enable/disable remains a separate signed, revisioned operation.
- **Optimization review:** Public guide navigation is local and stateless, eliminating assertion issuance, replay storage, and documentation-session coupling.
- **Validation:** Read the current connector-visible GTM map and checked all documentation/assertion references before publishing this planning-only update. No application code, branch, migration, or deployment changed.
- **Remaining action:** Implement the Support-page link rules on `SaaS-Test` after branch creation is authorized.


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
