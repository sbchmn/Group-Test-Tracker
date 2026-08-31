# Project Map

## Target Files and Modules
- app/models.py
- app/routes.py
- app/storage.py
- app/notifications.py
- app/templates/dashboard.html
- app/templates/group_test_detail.html
- app/templates/admin/edit_test.html
- app/templates/admin/create_test.html
- app/templates/admin/storage_config.html
- app/templates/base.html
- likely new templates for my results and public result admin pages
- migrations/versions/<new_revision>.py
- tests/test_notifications.py
- tests/test_schema_migration.py
- tests/test_security.py
- likely new tests for tags, results, dashboard visibility, and public results

## Intended Behavior Changes
- Move result image delivery to private-bucket-compatible access using authenticated app endpoints and short-lived signed URLs.
- Require login plus authorization checks before issuing image access; for group tests require admin or approved+paid participant.
- Generate signed image URLs on demand (60s TTL) so stale page sessions can still open images later.
- Add production-ready result image uploads backed by S3-compatible object storage (AWS S3 and DigitalOcean Spaces).
- Add admin storage settings page to enable/disable uploads and configure provider credentials/bucket/endpoint behavior.
- Add optional image attachment for both group test results and public results.
- Render a thumbnail next to result links and open full-size image in a modal on click.
- Add reusable tags for group tests and public results.
- Add per-user hidden dashboard state for group tests.
- Add a My Results page that combines member group-test results and admin-created public results.
- Add admin UI to create public results entries.
- Add admin ability to delete group tests from the edit page.
- Add dashboard sorting/grouping controls defaulting to grouping by status.
- Fix notification emails so each recipient receives the correct rendered variables.
- Add an admin action queue to approve pending participants across multiple tests from one page.
- Split dashboard actions so users can request join directly from dashboard cards.
- Add dashboard grouping by personal participation state: Pending, Approved, Not Joined.
- Ensure test-detail and dashboard join CTAs reflect existing pending/denied requests.
- Persist denied request state with admin-provided reason and show that reason to end users.
- Add a reapply workflow for denied users.
- Ensure admins can still manually add/approve users after a denial.
- Make denial state/reason visible on Manage Participants and align available admin actions across Action Queue and Manage Participants.

## Implemented Changes
- Extended paid-gating from images-only to full group-test result visibility (result link, itemized values, and thumbnails) for non-admin users.
- Added explicit admin bypass for group-test results visibility on My Results regardless of participation/payment state.
- Added security regression tests for unpaid-member result hiding and admin My Results bypass visibility.
- Fixed My Results group-test thumbnail rendering so admin users see all eligible result images consistently by reusing shared access helper logic.
- Hardened notification log handling to sanitize leading junk data and prune from complete timestamped entries.
- Added support for configurable `NOTIFICATION_LOG_PATH` to isolate logs per environment/test context.
- Updated notification tests to use isolated log paths and added regression coverage for junk-prefixed log cleanup.
- Switched result image display from direct object URLs to authenticated app endpoints that issue short-lived presigned URLs on demand.
- Added secure image delivery routes for group tests and public results, with login checks on all image requests.
- Enforced group-test image authorization as admin or approved+paid participant for the specific closed test.
- Added configurable signed URL TTL setting (default 60 seconds) in storage configuration.
- Changed storage ACL default toward private uploads (`public-read` disabled by default).
- Added regression tests for secure image authorization and redirect issuance in `tests/test_security.py`.
- Added production-oriented object storage module (`app/storage.py`) for S3-compatible uploads with image validation, size limits, and provider-aware URL generation.
- Added storage-backed result image fields (`results_image_key`) to both group tests and public results models, plus additive migration `c3d9e1f4a7b2_add_result_image_keys.py`.
- Added admin storage configuration page and route (`/admin/storage-config`) with provider selection (AWS/DO), bucket credentials, endpoint controls, and upload constraints.
- Added image upload handling to create/edit flows for group tests and public results, including replace/remove behavior and best-effort remote cleanup.
- Added thumbnail rendering and Bootstrap modal full-size viewing in group test detail, My Results, and Public Results admin listing.
- Added navigation entry for Storage Config in admin menu.
- Added shared Tag, PublicResult, and dashboard-hide models plus a `results_posted_at` field on group tests.
- Wired group-test and public-result tag entry through comma-separated inputs with datalist suggestions.
- Added dashboard grouping/sorting controls, hide/unhide toggles, and tag badges.
- Added `/my-results` and admin public-results management pages.
- Added edit support for admin-created public results with prefilled form values and tag updates.
- Added admin group-test delete support from the edit page.
- Fixed participant notification rendering to use each participant's own amount owed.
- Expanded dashboard grouping to include compound and made filter panels collapsible on dashboard and My Results pages.
- Filter panels on dashboard and My Results now default collapsed to avoid reopening automatically for users.
- Added optional free-text results to each lab test item in `lab_test_details` and display them on group test detail and My Results views.
- Added itemized public result rows with a new JSON column and admin create/edit UI, rendered on My Results alongside public result entries.
- Added an admin action queue page for pending participation requests with single-approve and bulk-approve actions.
- Added queue filters (status + keyword) so admins can quickly find pending requests by test/participant.
- Added queue pagination (25 per page) for large pending-request backlogs.
- Added deny actions (single + selected) to remove pending requests directly from queue.
- Added an "Approve All Filtered" action with explicit confirmation text requirement.
- Refactored action queue HTML form structure to avoid nested forms so row-level Approve/Deny buttons submit only their own row action.
- Split dashboard card action into separate "View Details" and request-status controls.
- Added dashboard quick-request POST route and card states: "Request Join", "Join Request Pending", and "Joined".
- Added dashboard filter support for grouping/sorting by personal join state.
- Updated test detail participation lookup to include pending/denied requests so CTA/status always reflects existing requests.
- Added participation denial fields (`denied`, `denied_at`, `denied_reason`) with a new additive migration.
- Updated queue deny actions to mark requests denied (instead of deleting) and require denial reasons.
- Displayed denied status and reason on dashboard cards and test detail page.
- Hid dashboard Request Join button once any participation record exists (pending/approved/denied).
- Added `POST /test/<id>/reapply` to reset denied requests back to pending review and notify admins.
- Added Reapply action on group-test detail when a denied request is shown.
- Updated admin add-participant flow to allow denied users to be selected and reactivated/approved instead of blocked by uniqueness.
- Added shared participation transition helpers (approve, deny with reason, reopen) used by both action-queue and manage-participants admin flows.
- Updated Manage Participants table to explicitly show Pending/Approved/Denied state and denial reason.
- Added Manage Participants deny/reopen endpoints so admins can perform queue-equivalent request-state actions within the test page.
- Updated test-detail participant table to show explicit request state (Approved/Pending/Denied) so denied users are never rendered as pending.
- Filtered denied participants out of group-test detail participant list entirely.

## Risks and Assumptions
- Object storage credentials and bucket policy are admin-managed; upload feature should fail closed when disabled/misconfigured.
- Uploaded files must be strictly validated as images and bounded by max size.
- Stored object references should remain provider-agnostic and safe to render without exposing secrets.
- Tags should be normalized to a shared tag table so they work across group tests and public results.
- Hidden dashboard state should be per-user and should not alter test visibility rules.
- Existing Alembic revisions must remain untouched; all schema additions go in one new revision.
- Public results should be additive and not disturb existing closed-test `results_link` behavior.
- Dashboard grouping is best handled client-side using data attributes to avoid changing core query logic.
- Bulk approval must recalculate `amount_owed` for all approved participants in affected tests to avoid stale balances.
- Deny actions remove pending participation records; this intentionally allows users to submit a fresh request later.
- Denied requests are now retained for auditability and user feedback; re-request policy remains blocked unless admin clears/changes status.

## Validation Plan
- Add focused tests for storage config enforcement and upload validation failure paths.
- Run core unit tests including schema/security slices after upload + config changes.
- Run targeted unit tests for notification rendering and new schema behavior.
- Add or update tests for tag persistence, my-results aggregation, and dashboard hide toggles.
- Run a narrow test command before broader verification.
- Check migrations or schema-related tests to confirm the new revision is additive only.
- Add/extend admin route tests to verify action queue approvals and recalculated costs.
- Extend queue tests for deny/remove workflow, pagination behavior, and approve-all-filtered confirmation safety.
- Add focused tests for dashboard quick-request flow and join-state grouping labels.
- Update queue denial tests to assert stored denied state/reason, and add detail-page denied reason rendering test.
- Add focused tests for denied-user reapply and admin add-participant reactivation after denial.
- Add focused tests to confirm queue denial appears in Manage Participants and manage-page deny/reopen actions persist correctly.

## Validation Results
- Focused paid-gating visibility validation passed: `python -m unittest tests.test_security tests.test_participant_removal`.
- Focused My Results image-visibility regression passed: `python -m unittest tests.test_security tests.test_participant_removal`.
- Focused log-fix validation passed: `python -m unittest tests.test_notifications tests.test_security`.
- Focused secure-image validation passed: `python -m unittest tests.test_security tests.test_schema_migration tests.test_participant_removal`.
- Focused post-change validation passed: `python -m unittest tests.test_schema_migration tests.test_security`.
- Focused test slice passed: `tests.test_notifications`, `tests.test_lab_costs`, and `tests.test_schema_migration`.
- New focused queue validation passed: `python -m unittest tests.test_participant_removal`.
- Re-ran queue suite after form-structure fix; all queue tests still passed.
- Dashboard + queue participant suite passed: `python -m unittest tests.test_participant_removal` (7 tests, OK).
- Reapply/admin-reactivation workflow validated in updated participant suite (`python -m unittest tests.test_participant_removal`, 10 tests, OK).
- Cross-page action parity + denial visibility validated in updated participant suite (`python -m unittest tests.test_participant_removal`, 12 tests, OK).
- Reconfirmed denied-vs-pending detail-page rendering via updated participant suite assertions (`python -m unittest tests.test_participant_removal`, 12 tests, OK).
- Reconfirmed denied participants are excluded from detail participant table while denied requester messaging still renders (`python -m unittest tests.test_participant_removal`, 12 tests, OK).

## Documentation Updates
- README updated to cover tags, public results, dashboard controls, and the current unittest-based validation command.
- README expanded into a comprehensive feature-by-feature how-to guide covering end-user flows, admin workflows, action queue usage, notification setup, object storage setup for AWS/DO Spaces, result image behavior, testing commands, and troubleshooting.
- Added a dedicated admin one-pager quick start guide in `ADMIN_QUICK_START.md` for onboarding and day-to-day operations.
- README now includes a full Table of Contents and a prominent top-level link to `ADMIN_QUICK_START.md` for faster admin navigation.
- README and ADMIN_QUICK_START now document private-bucket signed URL access, 60-second TTL guidance, and paid-participant requirements for group-test image viewing.

## Telegram Bot Workstream

### Target Files and Modules
- app/models.py
- app/routes.py
- app/__init__.py
- app/notifications.py
- app/templates/profile.html
- app/templates/password_reset.html
- app/templates/admin/notification_config.html
- likely new Telegram onboarding templates or route fragments
- migrations/versions/<new_revision>.py
- tests/test_notifications.py
- tests/test_security.py
- likely new tests for Telegram linking, delivery gating, and password-reset fallback

### Intended Behavior Changes
- Keep the design space open for multiple Telegram integrations rather than locking in notifications-only.
- Use Option A: implement Telegram bot integration inside the existing Flask app as the system-of-record backend.
- Make notifications and password resets the primary Telegram product surface, treated as the same core delivery workflow.
- Add a dedicated Telegram webhook endpoint in the app for inbound bot updates.
- Validate inbound webhook calls using a configured Telegram webhook secret and strict method/content checks.
- Add admin-managed Telegram integration settings for bot token, webhook secret, channel/group chat id, digest mode toggle, and digest window.
- Add a bot-linking flow that associates a Telegram `/start` interaction or one-time link token with the logged-in app user.
- Replace username-based Telegram delivery with stored per-user `telegram_chat_id` values captured from bot onboarding.
- Keep `tg_username` as an optional display field only; do not rely on it for delivery.
- Send Telegram notifications only when the user has an active linked chat and the bot token is configured.
- Make Telegram password reset delivery available only for linked users, with email retained as the fallback path.
- Add explicit Telegram password-reset UI guidance instructing users to open the bot and press Start before choosing Telegram as the reset channel.
- Surface linking status in the profile/admin UI so users and admins can see whether Telegram is actually usable.
- Add a Telegram channel value-add layer that surfaces group test status updates, eligibility updates, and participation updates in the channel.
- Route Telegram group-test status notifications to a configured Telegram group chat or channel and support digest mode.
- In digest mode, collapse duplicate status events into a single message and include all applicable recipients as tagged mentions in that message.
- Allow users to list their eligible tests and submit join requests from Telegram when the channel flow is enabled.
- If a dedicated Telegram channel is used, publish test status updates there and link back to the relevant test in the web app.
- Add Telegram-facing test discovery so users can list their eligible tests and start a join flow directly from the bot.
- Add a full suite of direct join and status-request actions from Telegram, including request-join, request-status, pending-state checks, and test-specific action prompts.
- Mirror the existing approval, denial, and paid-participant rules in every Telegram action so the bot cannot bypass web authorization.
- If the Telegram integration includes a dedicated channel, support channel broadcasts and moderation controls that point back to the relevant tests.

### Risks and Assumptions
- Telegram channel membership is a separate product decision from one-to-one bot delivery, so the implementation should stay modular until the preferred model is confirmed.
- Notifications/reset are the core path, so the group/channel features should not block initial delivery if they are delayed.
- Webhook and token settings are sensitive and must be masked at rest in UI and never written to debug logs.
- Inbound webhook validation failures must fail closed and return safe responses without leaking configuration details.
- Telegram bots cannot initiate private chats, so delivery must fail closed unless the user has already started the bot.
- A username is not a stable or sufficient delivery identifier; chat IDs must be stored and used for messaging.
- Link tokens must be single-use or time-limited to avoid account takeover through stale onboarding URLs.
- If the bot token or chat ID is missing, notifications should cleanly fall back to email instead of silently pretending Telegram succeeded.
- Password resets sent over Telegram should prefer reset links or one-time codes rather than exposing a long-lived password in chat.
- Telegram mentions in digest messages depend on available mention identifiers or usernames, so mention formatting/fallback behavior must be explicit.
- Direct join and status-request actions must reuse the existing approval, denial, and paid-participant rules rather than creating a second authorization path.
- If Telegram is used for test discovery, the bot must only expose tests the user is actually allowed to see.

### Validation Plan
- Define the Telegram scope decision first: notifications-only, group join flow, or hybrid.
- Add security tests for webhook secret validation, invalid payload handling, and disallowed method/content-type requests.
- Add configuration tests to verify Telegram secrets/tokens are masked in admin views and omitted from logs.
- Add focused tests for Telegram test listing, join-request submission, and status-request actions.
- Add focused tests for Telegram chat linking, message routing, and fallback behavior when chat IDs are absent.
- Add focused tests for digest grouping logic so duplicate events produce one Telegram channel/group message with correct mention rendering.
- Add regression coverage for password-reset delivery so Telegram is used only for linked accounts and email remains the fallback.
- Add UI-path tests for Telegram password reset to verify users are instructed to start the bot when not yet linked.
- Run the narrow notification/security test slices first, then expand only if the Telegram-specific checks pass.
- Add a migration test or schema assertion for the new Telegram linkage field before broader integration checks.

### Current Recommendation
- Implement notifications/password reset as the first deliverable and treat them as the core Telegram workflow.
- Implement webhook + key management in the first phase so all later Telegram actions use a hardened inbound/outbound boundary.
- Add the channel status layer and direct Telegram action suite after the base delivery path works, using the same chat-linking foundation and the existing approval workflow.
- Keep the bot modular so the channel features and direct actions can be layered on without reworking the Telegram account-linking foundation.

### Implementation Status (In Progress)
- Added Telegram webhook endpoint scaffolding in the Flask app with secret-token validation and JSON request checks.
- Added Telegram bot command handling for `/start`, `/help`, `/tests`, `/status <id>`, and `/join <id>`.
- Added chat-link token generation from profile and stored `telegram_chat_id` linkage.
- Updated password reset flow to require linked Telegram chat for Telegram channel resets and to avoid committing password changes if delivery fails.
- Added admin Notification Config fields for Telegram bot username, webhook secret, status chat/channel target, digest toggle, and digest window.
- Added lightweight digest suppression for duplicate status-change messages inside the configured digest window.

## Payment Options Workstream

### Target Files and Modules
- app/models.py
- app/routes.py
- app/templates/group_test_detail.html
- app/templates/participant_update_status.html
- app/templates/admin/create_test.html
- app/templates/admin/edit_test.html
- app/templates/admin/manage_participants.html
- likely new admin payment-option templates
- migrations/versions/<new_revision>.py
- tests/test_security.py
- tests/test_participant_removal.py
- likely new tests for payment-option admin CRUD and participant selection

### Intended Behavior Changes
- Add admin-configurable payment options (for example Venmo, Cash App, crypto wallets, and other methods) as reusable records.
- Support multiple payee identities per method so admins can configure one or more recipients per payment provider.
- Allow each group test to define which configured payment options are available for that specific test.
- Show the available payment options on the group test detail page as informational guidance.
- When a test is in `testing` status, show approved participants a selector in their participant-status panel to choose a preferred payment option.
- After selection, display the selected method details (handle, wallet, network, notes, recipient name) in the participant status area.
- Generate and display a QR code payload for supported payment methods when sufficient data is available.
- Preserve existing `paid_lab`, `amount_paid`, and `amount_owed` behavior; payment-option selection is guidance and routing metadata, not proof of payment.

### Risks and Assumptions
- Payment handles and wallet addresses are sensitive operational data and should be editable only by admins.
- Participant-selected payment preference must not alter owed-amount calculations or admin paid verification logic.
- QR payload generation must validate and normalize input to avoid malformed links and unsafe rendering.
- Crypto options require explicit network/chain labeling to reduce transfer mistakes.
- Historical payment selections should remain understandable even if a global payment option is later edited or disabled.

### Validation Plan
- Add model and route tests for admin CRUD of payment options and per-test option assignment.
- Add UI/route tests to ensure participant selection is available only to approved participants when status is `testing`.
- Add tests to verify selected payment method details and QR data render only for authorized viewers.
- Add regression tests proving existing cost, paid status, and amount-tracking logic remain unchanged.
- Run focused suites first (`tests.test_security`, `tests.test_participant_removal`) and then broader schema tests after migration changes.

### Current Recommendation
- Implement this in two phases: first admin CRUD + per-test assignment + informational display; second participant selection + QR rendering.
- Store participant preferred payment option as a reference plus optional snapshot text so historical records remain readable.
- Use a whitelist-based QR payload formatter per payment type (cashapp, venmo, wallet URI) to keep rendering predictable and safe.

### Implementation Status (In Progress)
- Added reusable payment option model and per-test assignment mapping.
- Added admin Payment Options page for create/list/toggle workflows.
- Added per-test payment option selection in create/edit test flows.
- Added participant preferred payment method selection during testing phase, including stored snapshot metadata.
- Added payment option informational display on group test detail and selected-option details with QR rendering on participant status page.

### Validation Results
- Focused implementation validation passed: `python -m unittest tests.test_schema_migration tests.test_notifications tests.test_security` (29 tests, OK).

## Telegram + Payment Hardening Pass

### Intended Behavior Changes
- Add durable Telegram account identity linkage using per-user `telegram_user_id` in addition to `telegram_chat_id`.
- Add webhook replay defense by persisting Telegram `update_id` values and ignoring duplicates safely.
- Add optional webhook source IP CIDR allowlist checks configurable by admins.
- Replace best-effort digest suppression with persisted digest-event records so status updates are deduplicated by event key and tracked as sent.
- Add payment-option edit and guarded delete behavior so options in active use are deactivated instead of removed.
- Preserve currently assigned inactive payment options in edit-test assignment forms to prevent accidental unlinking.

### Implemented Changes
- Added `users.telegram_user_id` plus two new models/tables: `telegram_webhook_updates` and `telegram_status_digest_events`.
- Hardened `/telegram/webhook` with optional source-IP allowlist (`telegram_webhook_allowed_ips`) and durable duplicate update rejection.
- Updated `/start` account-link flow to bind `telegram_user_id`, detect conflicts across users, and keep token usage safe.
- Added status digest event persistence keyed by chat/window/event signature and HTML mention formatting using Telegram user IDs when available.
- Added admin payment option edit route and template, and safe delete route that auto-deactivates in-use records.
- Extended payment options admin table with Edit/Toggle/Delete actions.
- Added additive Alembic revision `e3a1c9d4b7f2_add_telegram_webhook_replay_and_digest_tables.py` on top of `d12f4a9b8c7e`.
- Extended tests for schema artifacts, webhook IP/replay checks, Telegram user-id conflict behavior, digest persistence, and payment delete safety.

### Validation Results
- Focused hardening validation passed: `python -m unittest tests.test_schema_migration tests.test_notifications tests.test_security` (37 tests, OK).

## User Digest Scheduling

### Intended Behavior Changes
- Allow each user to choose digest email frequency from profile settings (`off`, `hourly`, `daily`).
- Allow users/admins to configure digest send schedule in UTC (hourly minute or daily hour).
- Queue status-change events per user and deliver them in a scheduled digest email batch.
- Provide a reliable delivery command that can be run by a scheduler without requiring the web process to stay stateful.

### Implemented Changes
- Added user digest preference fields on `users`: `digest_frequency`, `digest_hourly_minute_utc`, `digest_daily_hour_utc`, `digest_last_sent_at`.
- Added `user_digest_events` table and model for durable queued digest content.
- Updated profile and admin user create/edit forms/routes/templates to capture digest settings.
- Status-change flow now queues `UserDigestEvent` rows for opted-in users (`hourly`/`daily`) who receive notifications.
- Added digest scheduler logic in `app/notifications.py` (`send_due_user_digests`) including due-slot evaluation and sent-event marking.
- Added CLI command `flask send-user-digests` for scheduled execution.
- Added additive migration `f0c4a6b1d9e2_add_user_digest_schedule_and_events.py` on top of `e3a1c9d4b7f2`.
- Extended tests for schema updates and digest delivery behavior.

### Validation Results
- Focused digest scheduling validation passed: `python -m unittest tests.test_schema_migration tests.test_notifications tests.test_security` (39 tests, OK).

## Result File PDF Support

### Intended Behavior Changes
- Extend result uploads to support PDFs in addition to existing image formats.
- Render PDF-aware thumbnails in result lists without breaking image previews.
- Open PDFs directly inside existing result modals and keep image behavior for image files.
- Add a universal download action in the modal for both image and PDF result files.

### Implemented Changes
- Extended storage format defaults and validation to allow PDF uploads (`application/pdf`) with header validation.
- Added result-file-type detection helper in routes and passed file-kind metadata to result templates.
- Updated group test detail, My Results, and Public Results templates to render PDF icon thumbnails and switch modal content between `<img>` and `<iframe>`.
- Added modal download button in each updated result modal.
- Updated admin create/edit upload form accept filters and copy to include PDF uploads.
- Updated storage config defaults and UI copy to include PDF in allowed formats.
- Added test coverage for PDF upload validation and PDF modal metadata rendering.

### Validation Results
- Focused PDF-support validation passed: `python -m unittest tests.test_storage tests.test_security tests.test_notifications tests.test_schema_migration` (42 tests, OK).

## Notification Config Webhook Actions

### Intended Behavior Changes
- Provide admin buttons on Notification Configuration to register and unregister Telegram webhook directly from the app.
- Add a script-style backend path that calls Telegram Bot API `setWebhook` and `deleteWebhook` with stored credentials.
- Show effective webhook endpoint used by the app and a manual PowerShell fallback script.

### Implemented Changes
- Added Telegram webhook API helper functions in `app/notifications.py` for `setWebhook` and `deleteWebhook` requests.
- Added Notification Config field `telegram_webhook_url` (optional override) with automatic fallback to `service_base_url` or current host + `/telegram/webhook`.
- Added admin POST routes:
	- `/admin/notification-config/telegram-webhook/register`
	- `/admin/notification-config/telegram-webhook/unregister`
- Added UI controls on Notification Configuration page with Register/Unregister buttons and a PowerShell manual script snippet.
- Added guard rails and user feedback for missing bot token and non-HTTPS URL.
- Added focused security tests for register success, missing-token failure, and unregister success.

### Validation Results
- Focused webhook-action route validation passed: `python -m unittest tests.test_security.SecurityTests.test_admin_can_register_telegram_webhook_from_config_page tests.test_security.SecurityTests.test_register_telegram_webhook_requires_bot_token tests.test_security.SecurityTests.test_admin_can_unregister_telegram_webhook_from_config_page` (3 tests, OK).

## Telegram Profile Link UX Fix

### Intended Behavior Changes
- Ensure users can visibly access the generated Telegram link after clicking Generate Telegram Link.
- Show a QR code for the generated Telegram deep link.
- Provide a fallback display (start command + token) when bot username is not configured.
- Eliminate invalid nested-form markup in profile view to avoid inconsistent browser behavior.

### Implemented Changes
- Updated profile route context to pass `telegram_link_token` and `telegram_start_command` alongside `telegram_link_url`.
- Reworked profile Telegram action area to use a single valid form with `formaction` for Generate Telegram Link.
- Added explicit generated-link display field and QR code render using existing external QR service.
- Added fallback read-only start command/token display when deep link cannot be built.
- Added security tests for both configured and missing bot-username scenarios.

### Validation Results
- Focused regression validation passed: `python -m unittest tests.test_security tests.test_notifications tests.test_schema_migration tests.test_storage` (47 tests, OK).

## Telegram Webhook 404 Token-Safety Fix

### Intended Behavior Changes
- Prevent masked credential placeholders from being persisted as real credentials when saving Notification Configuration.
- Improve webhook registration feedback for Telegram API 404 Not Found responses.

### Implemented Changes
- Updated Notification Config save flow to preserve existing Mailjet and Telegram tokens when submitted value matches masked placeholder.
- Added explicit webhook-register failure hint for Telegram 404 Not Found to guide bot token re-entry.
- Added regression test for preserving `telegram_bot_token` when masked value is submitted.

### Validation Results
- Focused token-safety validation passed: `python -m unittest tests.test_security.SecurityTests.test_admin_can_register_telegram_webhook_from_config_page tests.test_security.SecurityTests.test_register_telegram_webhook_requires_bot_token tests.test_security.SecurityTests.test_notification_config_preserves_telegram_token_when_masked_value_submitted` (3 tests, OK).

## Public Results Template Runtime Fix

### Intended Behavior Changes
- Eliminate runtime template errors on admin pages caused by unsupported Jinja filters.

### Implemented Changes
- Replaced unsupported `|endswith('.pdf')` filter usage with slice-based extension checks in admin templates.
- Updated both public-results and edit-test PDF-preview branches to use the same compatible extension logic.
- Added a focused regression test that renders `/admin/public-results` with a PDF-backed public result to guard against template runtime failures.

### Validation Results
- Focused regression run passed: `python -m unittest tests.test_security tests.test_storage` (24 tests, OK).
- Additional focused rendering check passed: `python -m unittest tests.test_security.SecurityTests.test_group_test_pdf_result_renders_pdf_modal_trigger_and_download_button tests.test_security.SecurityTests.test_admin_public_results_page_renders_pdf_result_without_template_error` (2 tests, OK).

## Telegram Digest Duplicate Insert Race Fix

### Intended Behavior Changes
- Ensure test status updates remain idempotent and do not fail the request when concurrent digest event inserts race on the unique key.

### Implemented Changes
- Wrapped digest-event insert/flush in a nested transaction and caught `IntegrityError` to treat duplicate unique-key insert as a suppressed duplicate event.
- Added focused regression coverage that simulates duplicate-insert `IntegrityError` and verifies no exception escapes.

### Validation Results
- Focused validation passed: `python -m unittest tests.test_notifications tests.test_security` (46 tests, OK).

## New Test Telegram Channel Notification

### Intended Behavior Changes
- Send a Telegram status channel/group notification when a new group test is created, if a status channel is configured.

### Implemented Changes
- Added `_send_new_test_created_to_telegram(...)` helper to send a creation message to the configured Telegram status chat.
- Hooked create-test flow to call this helper after successful commit so DB writes are never blocked by notification delivery.
- Added exception guard and logging around the post-commit send path for fail-soft behavior.
- Added regression coverage for create-test route to assert channel messaging is invoked when `telegram_status_chat_id` is configured.

### Validation Results
- Focused validation passed: `python -m unittest tests.test_lab_costs tests.test_notifications tests.test_security` (53 tests, OK).

## Ready For Payment Status + Payment Panel Placement

### Intended Behavior Changes
- Add a new group-test lifecycle status: `ready_for_payment`.
- Allow organizers to set tests to this status.
- Display payment options at the top of the right-hand column on test detail during this phase.
- Keep Telegram channel/group status notifications active for this status transition.

### Implemented Changes
- Added `ready_for_payment` to admin group-test status choices.
- Updated visibility and grouping logic so approved users can see member-only tests in `ready_for_payment` like `testing` and `closed`.
- Added status-label formatting helper for underscore-based statuses and applied it to Telegram status digest and new-test channel messages.
- Updated participant payment preference save/render logic to allow selection in both `testing` and `ready_for_payment`.
- Moved the payment methods panel to the top of the right column when test status is `ready_for_payment`.

### Validation Results
- Impacted suite run passed: `python -m unittest tests.test_lab_costs tests.test_security tests.test_notifications tests.test_participant_removal`.
- New focused checks passed:
	- `tests.test_lab_costs.LabCostTests.test_create_test_supports_ready_for_payment_status`
	- `tests.test_security.SecurityTests.test_ready_for_payment_shows_payment_methods_at_top_of_right_column`
	- `tests.test_notifications.NotificationTests.test_status_digest_formats_ready_for_payment_label`

## PDF Upload Legacy Format Compatibility Fix

### Intended Behavior Changes
- Ensure PDF uploads for group/public results keep working even when older storage format config values omit `PDF`.

### Implemented Changes
- Updated storage settings parsing to auto-include `PDF` in allowed formats for backward compatibility with legacy image-only config values.
- Added regression coverage for successful PDF upload when `storage_allowed_formats` is stored as `JPEG,PNG,WEBP,GIF`.

### Validation Results
- Focused validation passed: `python -m unittest tests.test_storage tests.test_security` (27 tests, OK).

## Telegram Status Message Format + Thread Target Support

### Intended Behavior Changes
- Status channel notifications should read as `TestName is now newstatus` instead of `OldStatus -> NewStatus`.
- Telegram status channel configuration should support thread targets encoded as `<chat_id>_<message_thread_id>` and send `message_thread_id` in the Bot API payload.

### Implemented Changes
- Updated status digest line rendering in the status-channel path to sentence format using the new status only.
- Added thread-aware channel target parsing in notifications so `-100..._2` maps to `chat_id=-100...` and `message_thread_id=2`.
- Extended Telegram send helper to include `message_thread_id` when provided.
- Added regression tests for both thread-suffix and non-thread channel target forms, plus updated status message wording assertion.

### Validation Results
- Focused validation passed: `python -m unittest tests.test_notifications tests.test_security` (50 tests, OK).

## Status Ordering Adjustment (Ready Before Testing)

### Intended Behavior Changes
- Place `ready_for_payment` above `testing` in status-based lists and sorts.

### Implemented Changes
- Updated admin status dropdown ordering to show `Ready for Payment` before `Testing`.
- Updated dashboard status sort order and status-group order maps so ready-for-payment appears above testing.
- Added dashboard regression coverage that asserts grouped status ordering places `Ready For Payment` before `Testing`.

### Validation Results
- Focused validation passed: `python -m unittest tests.test_participant_removal tests.test_notifications tests.test_security` (63 tests, OK).