# Project Map

This document is the maintained current-state map for Group Test Tracker. Keep it concise and update it whenever implementation changes architecture, behavior, risks, priorities, or validation status. Historical implementation notes belong in [`docs/project-history.md`](docs/project-history.md).

## Snapshot

- **Application:** Flask web application backed by SQLAlchemy and Alembic.
- **Current branch baseline:** `Test-Updates` at `cc700412f387e8680720584016dbd4f023ebf2a4`.
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

- The current branch has no automated GitHub verification signal.
- Real provider accuracy, latency, cost, and retention behavior still require fixture evaluation with production-like credentials before automatic analysis is enabled.
- Runtime databases, notification logs, Python bytecode, and a debug script are tracked in the repository.
- Telegram animation validation recognizes GIF signatures and MP4 `ftyp` markers but does not fully parse or transcode media containers.
- Some outbound delivery remains synchronous or process-local and can be lost on process termination.
- The large `app/routes.py` and shared configuration table concentrate responsibilities and raise regression risk.
- Discord dynamic commands still inherit Telegram-oriented persistence names and incomplete provider-specific coverage.
- Historical validation was run across mixed Windows and Linux command environments.

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
