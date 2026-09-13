# Project Map

This document is the maintained current-state map for Group Test Tracker. Keep it concise and update it whenever implementation changes architecture, behavior, risks, priorities, or validation status. Historical implementation notes belong in [`docs/project-history.md`](docs/project-history.md).

## Snapshot

- **Application:** Flask web application backed by SQLAlchemy and Alembic.
- **Current branch baseline:** remote `Test-Updates` at `0e59040` plus the current Discord Public Results callback working tree.
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
- Support scoped Public Results browsing with acknowledged component callbacks, validated COA links, and safe file-only-result fallbacks, plus configured dynamic commands.
- Copy global command definitions into configured guild trees and support durable administrator-requested command refreshes without a worker restart.
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
   - Expand dedicated tests beyond guild/global synchronization into link conflicts, interaction deferral, rate limiting, media responses, and administrator reply updates.
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

### Discord Public Results Callback Reliability

- **Date:** 2026-09-13
- **Scope:** Prevent Discord tag-button interactions from timing out when `/publicresults` opens a tag, including tags containing uploaded-file-only results.
- **Target files/modules:** Public Results Discord rendering/callbacks in `app/discord_bot.py`, focused notification tests, and operator history.
- **Intended behavior:** Acknowledge component interactions before database work; use validated HTTP(S) report links or a configured application-detail fallback; render an unavailable disabled control instead of raising when neither URL is usable; and show a generic recoverable message if callback rendering fails.
- **Assumptions:** `service_base_url` is the canonical application origin for browser links generated by the standalone worker. Public Result detail pages retain their existing login requirement.
- **Security risks/checks:** Accept only HTTP(S) button targets with a hostname, do not disclose exception details to Discord users, preserve existing command/destination authorization, and avoid weakening result-page authentication.
- **Reliability risks/checks:** Defer within Discord's response window, handle missing/placeholder links, tolerate deleted/empty tag state, and keep callback errors logged with bounded non-sensitive context.
- **Optimization checks:** Reuse the already-loaded result rows and one cached configuration lookup per rendered result page; add no polling or external requests.
- **Validation plan:** Add focused button fallback, early acknowledgement, and callback-failure tests; run the Discord-focused notification tests and `git diff --check`.
- **Applied edits:** Public Results component callbacks now defer before authorization and database queries, then edit the acknowledged response. Result buttons accept only absolute HTTP(S) URLs with a hostname, replace blank/placeholder links with the configured application detail URL, and render a disabled unavailable button instead of raising when no safe target exists. Empty/deleted tag states remain navigable, and unexpected callback failures produce a retry message plus a sanitized worker-log event.
- **Security/reliability/optimization review:** Existing destination authorization remains in force after acknowledgement. Link validation rejects non-web schemes and hostless values, generated fallbacks retain the authenticated Public Result route, and Discord users do not receive exception details. The callback performs no new network work and reads `service_base_url` once per result page.
- **Validation:** Three focused URL-fallback, early-defer/missing-link, and callback-failure tests passed in 1.257s. The final full notification suite passed 49 tests in 44.194s. `git diff --check` passed.
- **Remaining risks:** `service_base_url` must be configured to make uploaded-file-only results clickable from Discord; otherwise they are shown as unavailable rather than breaking the interaction. Real Discord component timing and browser authentication still require deployment validation.

### Discord Command Synchronization

- **Date:** 2026-09-12
- **Scope:** Correct guild-scoped Discord command registration and let administrators request command synchronization without restarting the worker.
- **Target files/modules:** Discord command lifecycle in `app/discord_bot.py`, the administrator request endpoint in `app/routes.py`, the Discord card in `app/templates/admin/bot_integrations.html`, focused notification/security tests, and operator documentation.
- **Intended behavior:** Guild-specific synchronization copies the current global command tree into the configured guild; an administrator-only, CSRF-protected button records a durable synchronization request; the separately deployed Discord worker polls for new requests, reloads active custom commands, synchronizes Discord, and records a bounded status message.
- **Assumptions:** The web and Discord worker components share the same database, and one Discord worker is normally deployed. Global and guild commands remain mutually exclusive based on whether `discord_guild_id` is configured.
- **Security risks/checks:** Preserve admin-only POST and CSRF boundaries, never expose or log the bot token, and render synchronization status through Jinja auto-escaping.
- **Reliability risks/checks:** Make request IDs idempotent, avoid continuous retries after a failed request, remove stale dynamic commands before rebuilding the tree, acknowledge requests only after an attempted sync, and keep worker polling resilient to database or Discord errors.
- **Optimization checks:** Poll one indexed configuration key at a bounded interval and perform command reload/Discord API work only when the request ID changes.
- **Validation plan:** Add focused guild/global tree, dynamic refresh, route authorization/request, and UI status tests; run `tests.test_notifications`, focused security tests, compilation, and `git diff --check`.
- **Applied edits:** Guild synchronization now clears the local guild tree, copies all current global definitions into it, and synchronizes that guild. The Bot Integrations Discord card now has a Synchronize Commands button and pending/latest-status display. Its admin-only POST writes a unique database request, and the Discord worker polls every five seconds, reloads active dynamic commands, synchronizes once per request, and records success or sanitized failure. README and admin quick-start deployment guidance now explain the worker and refresh behavior.
- **Security/reliability/optimization review:** The new action is authenticated, administrator-only, POST-only, and protected by the existing global CSRF middleware. Tokens and exception details are excluded from UI status and logs. Requests and acknowledgements use unique bounded configuration values, failures are not retried indefinitely, stale dynamic commands are removed before reload, and shutdown cancels the polling task. Idle overhead is one indexed configuration lookup every five seconds; Discord API calls occur only at startup or on a new request.
- **Validation:** Four focused guild/global sync, worker request, authorization, persistence, and UI tests passed in 1.616s; the added stale dynamic-command refresh test passed in 1.257s. The final full notification suite passed 46 tests in 44.701s. The security suite ran 70 tests in 76.061s with 68 passing and the same two pre-existing Telegram callback mock-signature failures recorded below; the Discord synchronization/admin test passed. Python compilation and `git diff --check` passed.
- **Remaining risks:** Web and worker components must share `DATABASE_URL`; the page requires a refresh to display the worker's updated status; changing from a previously configured guild to global scope does not proactively delete commands from the former guild; real Discord API synchronization still requires deployment validation with the configured bot token and guild permissions.

### Public Legal Pages and Bytecode Ignore

- **Date:** 2026-09-12
- **Scope:** Add public Terms of Service and Privacy Policy pages covering the web application, Telegram and Discord bots, Root webhook notifications, automated OpenAI/xAI/Anthropic result extraction, and optional Google Analytics; add Python bytecode to Git ignore rules.
- **Target files/modules:** `.gitignore`, `.env.example`, application configuration in `app/__init__.py`, public routes in `app/routes.py`, shared footer/layout in `app/templates/base.html`, registration and new legal templates in `app/templates/`, focused public-route tests in `tests/test_security.py`, and operator setup guidance in `README.md`.
- **Intended behavior:** Anyone can review the legal pages without an account; every rendered page links to both policies; the disclosures describe the application's actual data flows and clearly distinguish third-party platform processing; newly generated `.pyc` files are ignored.
- **Assumptions:** The deployed operator's legal name, privacy contact, address, and governing jurisdiction are not present in the repository, so the pages use environment-configurable values with operator-neutral fallbacks and the README identifies those items as a pre-launch legal review requirement. Google Analytics is disclosed conditionally as an operator-enabled service because no Google tag is implemented in this repository.
- **Security risks/checks:** Keep legal routes read-only and public, preserve template auto-escaping, publish no secrets or configured bot identifiers, avoid asserting that health data is protected by HIPAA, and make clear that users must not submit personal or regulated data in laboratory reports.
- **Reliability risks/checks:** Keep footer links valid for anonymous and authenticated pages, avoid database dependencies in the policy routes, and ensure the text does not promise deletion schedules the application cannot currently enforce.
- **Optimization checks:** Serve static templates without database queries or new client-side dependencies; do not add analytics scripts or consent-state code outside the requested policy/footer scope.
- **Validation plan:** Add focused anonymous-route/footer/disclosure assertions, run `tests.test_security`, run the full unittest suite if the environment supports it, and run `git diff --check`.
- **Applied changes:** Added ignored `*.pyc`/`__pycache__` patterns; added public Terms and Privacy routes and comprehensive templates; covered Telegram, Discord, Root webhooks, OpenAI, xAI, Anthropic, and optional Google Analytics; added global footer links and a registration acknowledgment; and made operator identity/contact/jurisdiction/effective-date fields configurable by environment.
- **Security/reliability/optimization review:** Legal routes are read-only and intentionally anonymous; Jinja auto-escaping protects all operator-supplied legal fields; no integration secrets or live identifiers are exposed; policies avoid claiming HIPAA coverage or AI accuracy; static templates add no database queries or external runtime requests. Google Analytics remains unimplemented, so the policy does not falsely imply that a consent banner or tag exists.
- **Validation:** Three focused legal/footer/escaping tests passed in the final run in 0.203s. The full `tests.test_security` run executed 70 tests in 75.967s with 68 passing and two pre-existing Telegram callback mock-signature failures (`answer_telegram_callback_query(id)` expected versus the current implementation's `(id, None)` call); neither failure touches the files or behavior changed here. Python compilation and `git diff --check` passed.
- **Remaining requirements:** A qualified attorney should review the policies; production must set the legal environment fields and adopt a specific retention schedule; any future Google Analytics tag must be paired with jurisdiction-appropriate consent controls and policy updates. Adding ignore rules does not remove the 58 `.pyc` files already tracked by Git.

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
