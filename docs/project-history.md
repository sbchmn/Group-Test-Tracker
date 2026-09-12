# Project History

> Archived from the original `PROJECT_MAP.md` on 2026-09-10. This file preserves the chronological engineering record. For the maintained current-state map, see [`../PROJECT_MAP.md`](../PROJECT_MAP.md).

## 2026-09-11 - Telegram COA Review and Public Result Detail Improvements

### Scope

Implemented and debugged the Telegram `/submitcoa` workflow and improved the dedicated Public Result page. The work spans commits `13ca082`, `3bdc7d3`, `05aa163`, `e556370`, and `6994778`, plus the current dedicated-page edits.

### Implemented Changes

- Added linked-user Telegram COA intake for PDF/image attachments and public HTTP/HTTPS report links.
- Created queued `PublicResult` submissions and durable result-analysis runs for Telegram COAs.
- Added Telegram review presentation with finding selection, corrected values, evidence viewing, result naming, optional metadata, approval, and rejection.
- Preserved administrator-only review authorization and configured review chat/thread routing.
- Added worker exception logging with the underlying error and traceback when review notification delivery fails.
- Fixed optional Telegram thread handling when settings or persisted records contain `None`, `"None"`, `"null"`, blank, or malformed values.
- Hardened Telegram reply-to, edit, and delete message ID handling against invalid persisted values.
- Moved review reply processing before the non-private command filter so configured group/forum-thread administrators can complete reviews.
- Added callback feedback so Telegram users can see messages such as the required-name error instead of receiving a silent callback.
- Made name and finding-value replies correlate against both the generated prompt and the main review message to tolerate Telegram reply-shape differences.
- Added a dedicated Public Result Back to My Results button.
- Added inline rendering of attached image reports and embedded PDF reports below the Public Result details, with an authenticated open-report fallback link.

### Security, Reliability, and Performance Review

- Existing linked-user, active-user, administrator, destination-chat, and destination-thread checks remain in the review path.
- Report previews continue to use the authenticated result-image route and short-lived signed storage URLs rather than exposing object-storage keys.
- Analysis state remains committed before Telegram notification delivery; notification failure does not discard extracted findings.
- Invalid Telegram IDs are ignored or treated as unset instead of causing worker/webhook exceptions.
- Review text and callback notices remain bounded by existing Telegram message limits.
- The dedicated page reuses the existing secured storage route and file-kind helper without adding a second download path.

### Validation

- Passed: `python -m py_compile app/routes.py app/notifications.py app/telegram_result_review.py app/result_analysis/jobs.py` on 2026-09-11.
- Passed: `git diff --check` for the dedicated Public Result page change.
- Full automated test validation was not performed for this change set. Focused webhook and review-flow regression tests remain recommended.

### Remaining Risks

- A Telegram API delivery failure can still leave a run in `needs_review` until an explicit notification retry path is used.
- The current review reply path would benefit from direct tests using private, group, and forum-thread Telegram update payloads.
- Browser PDF support varies; the dedicated page retains an open-report link for clients that cannot embed PDFs.

## 2026-09-11 - Paginated Tags and Dual COA Sources

### Implemented Changes

- Replaced the flat Telegram tag list with a paginated submenu showing ten existing tags per page.
- Added explicit Save Tags and Cancel controls that return to the main review message.
- Added a Sources submenu with staged link and image/PDF fields, regardless of which source was submitted initially.
- Added link reply prompts for adding or changing the public COA URL.
- Added attachment reply prompts for adding or changing the stored PDF/image, using existing Telegram download and object-storage validation.
- Added remove-link and remove-file controls plus source Save/Cancel behavior.
- Applied staged link, file, and tag selections only when the administrator approves and publishes the result.
- Routed attachment-only review replies through the Telegram review handler.

### Validation and Risks

- Passed `python -m py_compile app/routes.py app/telegram_result_review.py app/notifications.py` on 2026-09-11.
- Passed `git diff --check -- app/routes.py app/telegram_result_review.py`.
- Newly uploaded draft files are cleaned up on cancel or rejection on a best-effort basis; orphan cleanup and focused webhook tests remain follow-up work.

## 2026-09-11 - Image-Only Public Results Tag Navigation Fix

- Fixed Telegram `/publicresults` result keyboards to use the authenticated `/public-results/<id>` page when a published certificate has no external result link.
- This prevents Telegram from rejecting the entire tag-result message edit because an inline button contained `url: None`.
- Added a security regression test covering an image-only bot-created certificate selected from a tag.
- Focused validation passed: `tests.test_security.SecurityTests.test_telegram_public_results_tag_click_handles_image_only_certificate` and the existing linked-private-user Public Results test, 2 tests in 2.322s.

## 2026-09-11 - Public Results Callback Diagnostics

- Added bounded, single-line Telegram API failure logging for `sendMessage`, `editMessageText`, and related API calls.
- Public Results callback updates now propagate `editMessageText` failure instead of returning success unconditionally.
- Logged chat ID, message ID, tag ID, and page number for failed Public Results updates without logging bot tokens or report contents.
- Added a Telegram callback alert directing the administrator to the bot log when a tag-result page cannot be loaded.
- Focused image-only and linked-user Public Results tests passed; the broader notification test invocation produced an incomplete terminal result and should be rerun in a fully provisioned environment.

### Regression Tests Added

- Added coverage that approval is rejected until a Public Result name is set.
- Added coverage that a valid Telegram name reply persists and can be published.
- Added coverage for ten-per-page tag navigation and Save state.
- Added coverage for adding a link and image/PDF to the same COA before approval.
- Added coverage for the dedicated Public Result page back link and embedded PDF.

### Test Environment Note

The focused test module could not be collected in the active environment because `Pillow` is not installed (`ModuleNotFoundError: No module named 'PIL'`). The dependency is already declared in `requirements.txt` as `Pillow>=10.4.0`. The updated application and test modules compile successfully, and `git diff --check` passes.

## 2026-09-11 - COA Source and Tag Review Controls

### Implemented Changes

- Added source context to Telegram COA review messages.
- Added a direct `Open Submitted COA Link` button for link-based submissions.
- Preserved uploaded image/PDF sources on the Public Result for review and later display through existing secured storage access.
- Added toggle buttons for the existing shared `Tag` catalog.
- Persisted selected tag IDs in the review state and applied only existing selected tags when an administrator approves the result.
- Kept tag changes behind the existing administrator-only review callback path; Telegram input cannot create arbitrary tags.

### Validation and Risks

- Passed `python -m py_compile app/telegram_result_review.py app/routes.py app/notifications.py` on 2026-09-11.
- Passed `git diff --check -- app/telegram_result_review.py`.
- The review keyboard currently displays the complete existing tag catalog; pagination may be needed if the catalog becomes large.

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
- README and ADMIN_QUICK_START refreshed for the latest release features: ready_for_payment lifecycle, payment option matrix workflows, Telegram webhook register/unregister actions, editable Telegram status templates with variables, status-channel digest behavior, Telegram account-linking reset guidance, and PDF result modal/download behavior.
- Admin docs/UI now present Telegram status template configuration as a sub-item under Notification Templates via an "Open Telegram Status Template Config" button that deep-links to the anchored section on Notification Config.

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

## Multi-Bot Workstream

### Target Files and Modules
- app/models.py
- app/routes.py
- app/notifications.py
- app/templates/admin/notification_config.html
- app/templates/admin/telegram_config.html
- likely new Discord and Root config templates
- likely new background dispatcher module or task runner
- migrations/versions/<new_revision>.py if provider-specific config is persisted
- tests/test_notifications.py
- tests/test_security.py

### Intended Behavior Changes
- Add Discord and Root as separate bot integrations rather than coupling them to Telegram.
- Keep bot delivery modular so each provider can be enabled, disabled, and configured independently.
- Avoid adding synchronous bot network work to the main web request path where possible.
- Prefer a shared delivery interface that can route to provider-specific adapters without duplicating business rules.
- Reuse existing notification/event selection logic so the web app continues to decide what should be sent, while bot adapters only handle transport.

### Implemented This Pass
- Added a shared queued webhook dispatcher in `app/bot_dispatch.py` using a small thread pool so bot webhook delivery can happen off the request thread.
- Added Discord and Root delivery helpers in `app/notifications.py` that queue outbound webhook payloads instead of performing the transport inline.
- Extended `send_notification_message()` so `discord` and `root` are valid delivery channels.
- Added Discord and Root webhook URL/display-name fields to the existing Notification Configuration admin form and persistence path.
- Added regression tests covering queued Discord and Root routing in `tests/test_notifications.py`.

### Risks and Assumptions
- The current notification path is synchronous, so adding bot sends directly in request handlers would increase request latency.
- A separate queue/worker path is the safer route if bot traffic is expected to grow.
- Discord and Root may have different message/thread models, so transport adapters should not assume Telegram semantics.
- If a background worker is not introduced, bot work should be kept out of hot paths and guarded by tight timeouts.

### Validation Plan
- Inspect the current notification dispatch points and identify which are on web request hot paths.
- Add focused tests for provider selection and fallback behavior before changing transport details.
- If a queue or background dispatcher is added, validate it with a narrow notification test slice before broadening scope.

### Validation Results
- Focused notification slice passed after the bot transport change: `python -m unittest tests.test_notifications`.
- Static diagnostics on touched Python files reported no errors.
- Isolated test log output in `tests/test_security.py` so webhook/config tests no longer pollute the shared `instance/notification.log`.
- Focused webhook security slice still passed after test-log isolation: `python -m unittest tests.test_security.SecurityTests.test_admin_can_register_telegram_webhook_from_config_page tests.test_security.SecurityTests.test_admin_can_unregister_telegram_webhook_from_config_page tests.test_security.SecurityTests.test_register_telegram_webhook_requires_bot_token`.

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
	- `/admin/telegram-config/webhook/register`
	- `/admin/telegram-config/webhook/unregister`
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

## Payment Method Matrix + Branded Link/QR UX

### Intended Behavior Changes
- Generate method-specific payment metadata (destination, hyperlinkable payment link, QR payload) for app-based methods and crypto.
- Improve payment presentation with provider branding/icons and clickable payment links.
- Provide admin-facing matrix documentation and generated previews for payment options.

### Implemented Changes
- Added centralized payment profile generation in `PaymentOption` for Venmo, Cash App, PayPal, Crypto Wallet, and Other.
- Added network-aware crypto scheme handling (for example `ethereum:`, `bitcoin:`, `solana:`) with fallback `crypto:` links.
- Updated route payment context builder to include provider branding, destination label/value, generated payment link, and QR payload.
- Added admin payment option input validation by method type unless QR payload override is provided.
- Enhanced payment display on test detail and participant status pages with provider badges, destination value, hyperlinkable payment links, and QR previews.
- Enhanced admin payment options and edit pages with a payment matrix table and generated preview panels.

### Validation Results
- Focused validation passed: `python -m unittest tests.test_security tests.test_lab_costs tests.test_notifications`.
- Additional targeted checks passed:
	- `tests.test_security.SecurityTests.test_payment_profile_generates_venmo_link_destination_and_qr`
	- `tests.test_security.SecurityTests.test_payment_profile_generates_crypto_link_destination_and_qr`

## Telegram Status Template Customization

### Intended Behavior Changes
- Make Telegram status-related message text editable from Notification Configuration instead of hardcoded strings.
- Support variable-based templates for status digests, new-test channel posts, and user `/status` responses.
- Keep safe defaults so blank/missing template values continue to produce reliable messages.

### Implemented Changes
- Added Notification Config form fields and persistence keys for Telegram status template variants.
- Added a shared Telegram status template renderer in routes and used it for:
	- digest header, digest line items, and participants line,
	- new-test created channel message,
	- user `/status` response variants (no request, denied, approved, pending).
- Extended Notification Configuration UI with editable textareas for each template and a variable reference list.
- Added regression tests for custom template rendering in status digest, new-test channel message, and approved `/status` response.

### Security / Reliability / Optimization Notes
- Security: Template rendering uses existing placeholder substitution and static context values; no dynamic code execution introduced.
- Reliability: Each render path supplies explicit default templates, preserving behavior when configs are empty/malformed.
- Optimization: Reuses lightweight substitution helper and current config map lookup without adding new query-heavy paths.
- Reliability: Telegram digest mentions are now resolved from current participation state at send time so denied users are excluded even if older queued events included them.
- Reliability: Telegram digest mentions now prefer a single @tg_username mention per participant and only use linked-ID mention fallback when no Telegram username exists, preventing duplicate mentions for the same person.

### Validation Results
- Focused post-change validation passed: `python -m unittest tests.test_notifications tests.test_lab_costs tests.test_security -q` (65 tests, OK).
- Follow-up mention-filter fix validation passed: `py -3 -m unittest tests.test_notifications tests.test_security` (58 tests, OK).
- Mention dedupe preference validation passed: `py -3 -m unittest tests.test_notifications` (30 tests, OK).
	- `tests.test_security.SecurityTests.test_ready_for_payment_renders_venmo_link_and_qr`
	- `tests.test_security.SecurityTests.test_payment_option_form_requires_handle_for_venmo_without_override`

## Telegram My Tests Command + Ordered Lists

### Intended Behavior Changes
- Add a `/mytests` bot command that lists only group tests the linked user is actively interacting with (pending, approved, or denied).
- Ensure Telegram test list responses are ordered by group test number ascending.
- Keep `/status <test_id>` usable for a user's own participation record even when that test is no longer broadly visible to them.

### Implemented Changes
- Added `/mytests` to Telegram help output and webhook command handling.
- Added shared Telegram test-list formatting and ascending-by-test-id ordering helpers.
- Updated `/tests` to use the shared ordered formatter.
- Added participation-scoped `/mytests` output with Pending/Approved/Denied labels.
- Added per-test clickable command hints under iterated Telegram test items, using `/status_<test_id>` and including `/join_<test_id>` only when the user can still join that recruiting test.
- Relaxed Telegram `/status` visibility gating to allow a user's own participation record to resolve status output.
- Updated README and ADMIN_QUICK_START with the new Telegram bot command guidance.

### Security / Reliability / Optimization Notes
- Security: `/status` now allows access only when the requesting linked user has a participation record for that test; it does not expose unrelated tests.
- Reliability: Shared ordered formatter removes inconsistent list ordering across Telegram test list responses.
- Optimization: Sorting is done on de-duplicated in-memory test sets capped to the existing list size, avoiding wider query churn.

### Validation Results
- Narrow webhook-command validation passed: `py -3 -m unittest tests.test_security.SecurityTests.test_telegram_tests_command_lists_visible_tests_in_ascending_test_number_order tests.test_security.SecurityTests.test_telegram_mytests_command_lists_only_user_interactions_with_states tests.test_security.SecurityTests.test_telegram_status_command_allows_user_participation_even_if_test_not_visible` (3 tests, OK).
- Broader Telegram/security regression slice passed: `py -3 -m unittest tests.test_security` (32 tests, OK).
- Follow-up clickable-command list validation passed: `py -3 -m unittest tests.test_security.SecurityTests.test_telegram_tests_command_lists_visible_tests_in_ascending_test_number_order tests.test_security.SecurityTests.test_telegram_mytests_command_lists_only_user_interactions_with_states` (2 tests, OK).
- Clickable underscored-command validation passed: `py -3 -m unittest tests.test_security.SecurityTests.test_telegram_tests_command_lists_visible_tests_in_ascending_test_number_order tests.test_security.SecurityTests.test_telegram_mytests_command_lists_only_user_interactions_with_states tests.test_security.SecurityTests.test_telegram_status_command_allows_user_participation_even_if_test_not_visible tests.test_security.SecurityTests.test_telegram_join_command_accepts_underscored_clickable_form` (4 tests, OK).

## Telegram Closed-Test Results Status Reply

### Intended Behavior Changes
- When a linked user requests `/status <test_id>` for a closed test where they are approved and marked paid, return a message containing the test results URL.
- Keep this message configurable within the existing Telegram status template system.

### Implemented Changes
- Added a completed+paid `/status` branch that returns the closed test's `results_link` when available.
- Added a new notification-config key and admin field: `telegram_status_user_results_template`.
- Exposed `results_url` as a supported Telegram status template variable.
- Updated README and ADMIN_QUICK_START with the new bot behavior.

### Security / Reliability / Optimization Notes
- Security: The results URL is returned only for the linked user's own approved, paid participation on a closed test.
- Reliability: The branch falls back to the standard approved reply when the test is not closed, the user is not paid, or no results URL exists.
- Optimization: The change reuses the existing `/status` lookup path and template renderer with no new broad queries.

### Validation Results
- Narrow results-status validation passed: `py -3 -m unittest tests.test_notifications.NotificationTests.test_telegram_status_summary_returns_results_url_for_closed_paid_participant tests.test_notifications.NotificationTests.test_telegram_status_summary_uses_custom_results_template tests.test_security.SecurityTests.test_notification_config_persists_telegram_status_templates` (3 tests, OK).

## Telegram Group Outbound-Only Guard

### Intended Behavior Changes
- Do not let the bot reply to commands in Telegram groups/topics used for status updates.
- Prevent group messages from overwriting a user's linked private `telegram_chat_id`.

### Implemented Changes
- Added an early non-private chat guard in the Telegram webhook so `group`, `supergroup`, and other non-private chats are ignored for bot command handling.
- Kept status-channel/topic posting unchanged because outbound status messages use the separate status sender path.
- Updated README and ADMIN_QUICK_START to state that bot commands should be used in private DM only.

### Security / Reliability / Optimization Notes
- Security: Prevents accidental disclosure of per-user bot replies in shared group chats.
- Reliability: Prevents a linked user's private chat binding from being replaced by a group chat ID.
- Optimization: Early return reduces unnecessary user lookup and command processing for group traffic.

### Validation Results
- Narrow group-guard validation passed: `py -3 -m unittest tests.test_security.SecurityTests.test_telegram_webhook_ignores_group_messages_without_reply tests.test_security.SecurityTests.test_telegram_webhook_group_message_does_not_overwrite_private_chat_link` (2 tests, OK).

## Telegram /testing Public Reply Path

### Intended Behavior Changes
- Allow one public Telegram command path, `/testing`, in groups and channels.
- Reply with the app base URL plus sign-up and login instructions so users can onboard without private bot interaction.
- Keep all other non-private commands ignored.

### Implemented Changes
- Added `_resolve_service_base_url(...)` and `_telegram_testing_message(...)` helpers.
- Extended webhook payload parsing to accept `channel_post` and `edited_channel_post` so `/testing` can work in channels as well as groups.
- Added an early `/testing` branch before the non-private-chat guard, returning sign-up and login links built from `service_base_url` with host fallback.
- Threaded `/testing` replies to the originating Telegram topic by forwarding `message_thread_id` through the direct chat send helper when present.
- Added `/testing` to the bot help text and updated README/ADMIN_QUICK_START.

### Security / Reliability / Optimization Notes
- Security: The public reply contains only onboarding links and no user-specific state.
- Reliability: The message uses configured `service_base_url` when available and falls back to the current host, matching existing link-building patterns.
- Optimization: Early branching avoids unnecessary user-link lookups for this public onboarding path.

### Validation Results
- Narrow `/testing` validation passed: `py -3 -m unittest tests.test_security.SecurityTests.test_telegram_webhook_testing_command_replies_in_group_with_signup_and_login_urls tests.test_security.SecurityTests.test_telegram_webhook_testing_command_replies_in_channel_post tests.test_security.SecurityTests.test_telegram_webhook_ignores_group_messages_without_reply tests.test_security.SecurityTests.test_telegram_webhook_group_message_does_not_overwrite_private_chat_link` (4 tests, OK).
- Focused thread-routing validation passed: `py -3 -m unittest tests.test_security.SecurityTests.test_telegram_webhook_testing_command_replies_in_group_with_signup_and_login_urls tests.test_security.SecurityTests.test_telegram_webhook_testing_command_replies_in_originating_message_thread tests.test_security.SecurityTests.test_telegram_webhook_testing_command_replies_in_channel_post tests.test_security.SecurityTests.test_telegram_webhook_ignores_group_messages_without_reply` (4 tests, OK).

## Phase 1: Dedicated Telegram Config Page

### Target Files and Modules
- `app/routes.py`
- `app/templates/admin/notification_config.html`
- `app/templates/admin/telegram_config.html`
- `app/templates/admin/notification_templates.html`
- `app/templates/base.html`
- `tests/test_security.py`
- `README.md`
- `ADMIN_QUICK_START.md`

### Intended Behavior Changes
- Split admin configuration responsibilities so Notification Config remains focused on Mailjet/debug settings.
- Move Telegram bot credentials, webhook settings/actions, status channel target, digest controls, status templates, and service base URL into a dedicated Telegram Config page.
- Keep runtime Telegram behavior and config keys unchanged to avoid migration and compatibility risk.
- Preserve existing webhook action endpoints while introducing Telegram Config-native webhook routes.

### Implemented Changes
- Refactored forms in routes:
	- `NotificationConfigForm` now contains Mailjet + notification debug fields only.
	- Added `TelegramConfigForm` for all Telegram-related fields and templates.
- Refactored `/admin/notification-config` route to persist only Mailjet/debug keys.
- Added `/admin/telegram-config` route with full Telegram settings persistence, webhook-secret masking behavior, and effective webhook URL context.
- Added Telegram-config-native webhook action routes:
	- `/admin/telegram-config/webhook/register`
	- `/admin/telegram-config/webhook/unregister`
	while preserving legacy endpoints as aliases for backward compatibility.
- Updated webhook action redirects to return to Telegram Config.
- Simplified Notification Config template and added CTA to open Telegram Config.
- Added new `admin/telegram_config.html` containing Telegram fields, template editor, webhook action buttons, and manual PowerShell script.
- Updated Notification Templates deep-link button to target Telegram Config status-template anchor.
- Added Telegram Config entry in admin navigation.
- Updated security tests to post Telegram persistence cases to `/admin/telegram-config`.
- Updated README and admin quick-start docs to reflect the route/page split.

### Security / Reliability / Optimization Notes
- Security: Telegram token masking preservation remains enforced on Telegram Config POST, preventing masked placeholders from being stored as credentials.
- Security: Existing admin-only protection remains on all config and webhook action routes.
- Reliability: Legacy webhook action endpoints are retained, minimizing regression risk for existing scripts/bookmarks.
- Reliability: Telegram and Mailjet settings ownership is now explicit per page, reducing operator misconfiguration risk.
- Optimization: No additional DB schema changes or heavy query paths were introduced; route behavior remains lightweight map-based config persistence.

### Validation Results
- Focused regression validation passed: `python -m unittest tests.test_security` (38 tests, OK).

## Phase 2: Telegram Webhook Endpoint Cutover

### Target Files and Modules
- `app/routes.py`
- `tests/test_security.py`
- `PROJECT_MAP.md`

### Intended Behavior Changes
- Remove legacy Notification Config webhook action URLs now that Telegram has a dedicated admin page.
- Enforce a single Telegram control-plane endpoint family under `/admin/telegram-config/...`.
- Keep cutover explicit and test-covered so stale old URLs fail predictably.

### Implemented Changes
- Removed route aliases for:
	- `/admin/notification-config/telegram-webhook/register`
	- `/admin/notification-config/telegram-webhook/unregister`
- Retained canonical Telegram webhook actions at:
	- `/admin/telegram-config/webhook/register`
	- `/admin/telegram-config/webhook/unregister`
- Added regression test asserting both legacy notification-config webhook endpoints now return 404.
- Updated Notification Config save activity-log label to `configuration: notification settings updated` to match page scope.

### Security / Reliability / Optimization Notes
- Security: Removing stale endpoints reduces accidental invocation surface and keeps all Telegram webhook actions behind one explicit admin route family.
- Reliability: Canonical endpoints remain unchanged from Phase 1, and tests now guard against route regression/reintroduction.
- Optimization: No schema or runtime query overhead introduced; this is a routing-surface reduction.

## Reliability Callouts 1-3 Fixes

### Implemented Changes
- Telegram webhook requests now fail closed with `503` when no webhook secret is configured, and always require a matching `X-Telegram-Bot-Api-Secret-Token` header.
- Password reset rendering now selects `email_body` or `telegram_body` according to the selected delivery channel.
- Discord and Root webhook notifications now use bounded synchronous delivery through the shared HTTP helper, returning failure when transport fails so email fallback can run.
- Added regression coverage for missing webhook secrets, channel-specific password-reset templates, and successful webhook delivery.

### Security / Reliability / Optimization Notes
- Security: An unconfigured Telegram webhook cannot be used as an unauthenticated command endpoint.
- Reliability: Notification success now reflects the provider response instead of only in-memory queue submission.
- Optimization: Delivery retains the existing 10-second timeout and shared JSON transport helper; no durable queue was introduced in this phase.

### Validation Results
- Focused security and notification suites passed with the Python 3.12 interpreter.
- Full unittest discovery completed without reported failures.

## Public Results Pagination and Close Controls

### Implemented Changes
- Fixed tag pagination to count and slice one distinct, alphabetically ordered tag set.
- Added Telegram `Close` callback buttons that delete the current bot message.
- Added Discord `Close` buttons that delete the ephemeral Public Results response.

### Validation Results
- 13-tag pagination regression passed: page 1 contains 10 tags and page 2 contains 3.
- Telegram Close/delete regression passed.
- Existing Public Results private/group/callback tests passed.
- Full unittest discovery completed without reported failures.
- Changed modules compiled successfully.

## Telegram Public Results Dispatch Fix

### Implemented Changes
- Restricted the non-private Telegram Public Results handler to messages whose command head is exactly `/publicresults`.
- Unknown group/channel commands such as `/testme` no longer open or repeat the Public Results browser.

### Validation Results
- Unknown-command regression passed.
- Scoped group and linked private Public Results regressions passed.
- Full unittest discovery completed without reported failures.

## Future Admin-Only Bot Workflows

### Planned Behavior
- Support bot commands that require a linked Group Test Tracker administrator through `User.is_admin`.
- Keep application-admin authorization distinct from Telegram group-admin and Discord server-moderator status.
- Allow each future command to declare its required authorization policy instead of inheriting broad bot access.

### Authorization Layers
- Linked Group Test Tracker admin.
- Linked regular user.
- Telegram group administrator, when provider metadata is available and explicitly enabled.
- Discord server moderator/administrator, when interaction permissions are available and explicitly enabled.
- Explicit chat, guild, channel, or thread scope.

### Security / Reliability Notes
- Application-admin status remains the authoritative policy for administrative workflows.
- Platform-admin status must never silently substitute for application-admin status.
- Existing public and participation commands remain governed by their current linking and scope rules.
- Future admin-only commands require dedicated authorization tests for private and group/channel contexts.

## Bot Service Boundary and Versioned Internal API

### Recommendation
- Keep Telegram and Discord as separate bot processes initially, but keep them in the same repository and use a shared GTM service layer.
- Do not duplicate business authorization or database rules inside provider adapters.
- Introduce authenticated internal GTM API endpoints before splitting bot processes into separately deployed applications.
- Use the path shape `/internal/api/v1/...` for the first stable internal API version.
- Move bot outbound delivery toward durable jobs once provider traffic or retry requirements justify the added infrastructure.

### Boundary Responsibilities
- GTM web application/API: system of record, business rules, authorization, command configuration, user linking, tests, participation, and Public Results.
- Telegram process: webhook parsing, Telegram media/callback handling, message IDs, and Telegram API delivery.
- Discord process: gateway events, slash commands, Discord permissions, attachments, interactions, and Discord API delivery.
- Shared service layer: provider-neutral operations such as resolve linked user, check command policy, list Public Results, submit join request, and record bot message ownership.

### Versioned API Management Prompts
Before adding or changing an internal bot API endpoint, answer these questions in the project map or change plan:

- What is the endpoint's version, method, request schema, response schema, and owning service layer?
- Is this backward compatible with existing Telegram and Discord processes?
- Does the change require a new `/v2` endpoint, or can `/v1` safely accept an additive field?
- What authentication, authorization policy, and provider scope apply?
- What idempotency key or provider event ID prevents duplicate effects?
- What timeout, retry, rate-limit, and failure behavior applies?
- How are secrets, tokens, image keys, and provider IDs prevented from leaking into logs?
- What migration or dual-read/dual-write period is required?
- How will old bot versions behave during rollout and rollback?
- Which contract, security, migration, and provider integration tests prove compatibility?
- What deprecation date and removal plan applies to the old endpoint or field?

### API Reliability Rules
- Use authenticated service-to-service requests with separate credentials from user sessions.
- Require idempotency for join requests, command updates, message ownership records, and outbound event processing.
- Keep API responses provider-neutral; Telegram and Discord formatting stays in their adapters.
- Prefer additive changes within a version; introduce a new version for breaking schema or authorization changes.
- Maintain contract tests for each supported bot process against every active API version.
- Document rollout order: deploy GTM compatibility first, then bot clients, then remove deprecated behavior only after the client minimum version is enforced.

### Planned Migration Stages
1. Extract shared bot operations from route/adapter code into a tested GTM service layer.
2. Add authenticated `/internal/api/v1` endpoints with request validation and idempotency.
3. Update Telegram and Discord processes to call the service boundary while retaining compatibility fallbacks.
4. Add durable outbound jobs and provider delivery status when operational load requires them.
5. Split provider processes into independently deployable applications only after the versioned API contract is stable.

## Provider-Aware Bot Destination Selectors

### Planned Behavior
- Add admin configuration selectors for bot status destinations using friendly names rather than raw IDs.
- Clearly label every option by provider, for example `Telegram · Group Test Updates` or `Discord · Results Channel`.
- Do not display Telegram chat IDs, Discord guild IDs, Discord channel IDs, or raw technical identifiers in dropdown labels.
- Selecting a friendly destination writes the underlying provider ID into the correct configuration field.
- Keep manual ID entry and validation available as a fallback when discovery is unavailable.

### Provider Discovery Model
- Discord: discover accessible guilds and channels through the connected bot, then expose provider-labeled friendly names with permission status.
- Telegram: validate manually entered or previously discovered chats through Bot API metadata and remember friendly chat titles/types for future selection; Telegram cannot globally enumerate all bot chats.
- Store provider, destination type, friendly name, underlying ID, last validation time, and permission state separately from the active configuration value.

### Security / Reliability / UX Notes
- Only show Discord guilds/channels the bot can access and use for the selected operation.
- Validate Telegram destinations before saving and show clear permission/error states.
- Use explicit Refresh/Resolve and Send Test actions rather than silently replacing configured destinations.
- Preserve raw IDs in storage and logs only where operationally necessary; never use raw IDs as the primary user-facing label.

## Status Channel Test Navigation

### Implemented Changes
- Added a stable `#payment-options` anchor to the Ready for Payment section on group-test detail pages.
- Ready-for-payment status events now include one `View Payment Options` button linking to `/test/<id>#payment-options`.
- Closed status events now include one `View Test` button linking to `/test/<id>`.
- Telegram uses inline URL buttons; Discord uses native link buttons. Root remains text-only.
- Digest messages deduplicate repeated action buttons and continue sending text when no service base URL is configured.

### Security / Reliability / Optimization Notes
- Security: Buttons link to the existing authenticated test page; payment destinations are not exposed directly in group/channel messages.
- Reliability: URL construction uses the configured service base URL and does not require an active Flask request context, so scheduled/status-triggered sends remain safe.
- Optimization: One button per relevant test event; unrelated statuses remain text-only.

### Validation Results
- Ready-for-payment and closed button regressions passed.
- Existing digest persistence and Discord status delivery tests passed.
- Full unittest discovery completed without reported failures.

## Discord User Form Audit

### Reviewed Surfaces
- Self-service Profile form and Discord link-token flow.
- Admin Create User, Edit User, and Manage Users forms.
- Password Reset channel selection and linked-account gating.
- Notification channel selection and Discord DM delivery identity.
- Participation and bot-facing user lookup paths.

### Implemented Fix
- Admin user creation and editing now persist `discord_username`, and Manage Users displays Discord display/link status.

### Intentional Boundary
- Discord account linking remains user-driven through Profile-generated one-time tokens and `/start`; admins do not directly edit Discord snowflake IDs. This prevents accidental identity reassignment and preserves the ownership checks in the Discord bot.

### Validation Results
- Focused user-form and password-reset tests passed.
- Full unittest discovery completed without reported failures.
- Updated user routes and models compiled successfully.

## Admin Bot-Link Visibility and Edit Safety

### Implemented Changes
- Manage Users now shows Telegram and Discord display/link status badges.
- Edit User now shows both provider linking states and explains that links are user-managed.
- Admin create/edit forms persist Discord display names without touching provider identity IDs.

### Safety Contract
- Editing username, email, display names, notification settings, or activity status does not change `telegram_chat_id`, `telegram_user_id`, or `discord_user_id`.
- Leaving the admin password field blank preserves the existing password hash.
- Provider linking remains token-based and user-driven through Profile and bot `/start` flows.

### Validation Results
- Focused admin linking-status and password-preservation tests passed.
- Full unittest discovery completed without reported failures.

## Built-in Bot Command Controls

### Implemented Changes
- Added `/admin/settings/commands/builtins` for enabling/disabling built-in command workflows.
- Reserved `/publicresults` from generic bot command templates.
- Registered Discord `/publicresults` as a native application command rather than a dynamic template command.
- Moved `/publicresults` scope configuration to built-in settings while preserving private-link and group/channel rules.
- Added enable flags for `/tests`, `/mytests`, `/status`, `/join`, and `/publicresults`.
- Excluded legacy `/publicresults` template rows from generic Telegram/Discord help and dynamic command registration.

### Security / Reliability / Optimization Notes
- Security: Built-in commands cannot be overridden by generic reply templates, and public-result scope is centrally enforced per provider.
- Reliability: Disabling `/publicresults` applies to both Telegram handling and Discord command execution.
- Optimization: Built-in behavior no longer depends on a fake generic template record or duplicated reply configuration.

### Validation Results
- Built-in settings and public-results integration tests passed.
- Full unittest discovery completed without reported failures.
- Routes and Discord bot module compiled successfully.
- `git diff --check` passed.

## Application Version and Payment UX

### Implemented Changes
- Added the authoritative application version in `app/version.py` (`0.1.0`).
- Added a public `/version` page, authenticated user-menu entry, and footer version link.
- Extended payment profiles with web-vs-URI classification, mobile/desktop action labels, and copyable fallback values.
- Added responsive Open/Copy payment controls to group-test and participant payment views.
- Kept payment options informational: no transaction processing or payment-proof behavior was introduced.

### Security / Reliability / Optimization Notes
- Security: Payment links remain administrator-provided/generated destinations; no credentials or payment tokens are handled by the app.
- Reliability: Desktop browsers get web-page/copy behavior while mobile users get app/wallet-oriented actions; QR payloads remain available for camera-based handoff.
- Optimization: No new dependency or migration was added. There is no universal library that can reliably launch every supported payment provider across desktop and mobile, so the app uses provider standards and progressive enhancement instead.

### Validation Results
- Version-page/footer regression passed.
- Venmo and crypto payment profile regressions passed.
- Ready-for-payment rendering regression passed.
- Full unittest discovery completed without reported failures.

## Discord API Compliance Hardening

### Target Files and Modules
- app/notifications.py
- tests/test_notifications.py
- PROJECT_MAP.md

### Intended Behavior Changes
- Align Discord transport behavior with official Discord API documentation for authentication, endpoint usage, and Create Message payload constraints.
- Add bounded retry behavior for HTTP 429 responses using Retry-After/retry_after guidance.
- Prevent accidental broad mentions in Discord status and DM messages when message text contains user-provided content.

### Implemented Changes
- Verified official docs from raw source files in discord/discord-api-docs:
	- developers/reference.mdx (Authentication, Base URL, API versioning)
	- developers/resources/user.mdx (Create DM endpoint and recipient_id)
	- developers/resources/message.mdx (Create Message constraints, content limit)
	- developers/topics/rate-limits.mdx (429 behavior and Retry-After/retry_after)
	- developers/platform/interactions.mdx (Gateway vs HTTP interactions requirements)
- Updated Discord REST sender in app/notifications.py:
	- Added bounded 429 retry support honoring Retry-After/retry_after for short waits.
	- Added safe payload builder with allowed_mentions parse disabled.
	- Added message chunking to keep content within Discord's 2000-character message limit.
	- Kept API v10 endpoint usage and Bot authorization header behavior unchanged.
- Added focused tests in tests/test_notifications.py:
	- Verifies allowed_mentions parse is disabled in Discord payloads.
	- Verifies 429 retry path succeeds when a retry-after window is provided.

### Security / Reliability / Optimization Notes
- Security: Explicit allowed_mentions restrictions reduce risk of unintentional @everyone/@role mentions from templated or user-originated text.
- Reliability: Short, bounded 429 retries improve successful delivery without indefinite retry loops.
- Optimization: Retry count and maximum wait are capped by app config to avoid prolonged blocking in request paths.

### Validation Results
- Focused validation passed: py -3 -m unittest tests.test_notifications -q (38 tests, OK).

### Validation Results
- Focused validation passed: `python -m unittest tests.test_security` (39 tests, OK).

## Discord Native Interaction Hardening

### Current Implementation
- Discord uses a gateway bot with native application slash commands, ephemeral responses, and optional guild-scoped command synchronization.
- Profile-generated one-time tokens link a Discord snowflake to the application user; links now reject identity movement and consume tokens under a row lock.
- Core and dynamic commands defer first, run synchronous SQLAlchemy work through the existing worker helper, and edit the original interaction response.
- Dynamic command collisions with native command names are skipped, and application-command failures receive a safe ephemeral error response.

### Security / Reliability / Optimization Notes
- Security: Discord user IDs are the delivery/link identity; display names are informational only. Existing links cannot be silently replaced by another Discord account.
- Reliability: Interaction acknowledgements are sent before database work, avoiding Discord's initial-response timeout and gateway event-loop blockage.
- Optimization: Database work runs in worker threads while Discord interaction I/O remains asynchronous.

### Remaining Discord Work
- Dynamic commands currently reuse `TelegramCommandTemplate` and Telegram-named scope fields. A Discord-native command-template model/admin surface should be introduced before expanding custom command features.
- Add dedicated Discord tests for token ownership conflicts, interaction deferral, command authorization, command synchronization, and dynamic-command rate limits.
- Add explicit Discord configuration/invite guidance and validate guild/channel IDs before bot startup.

### Validation Results
- `app/discord_bot.py` compiles successfully.
- Editor diagnostics report no errors for the edited Discord module.

## Phase 3: Telegram Custom Command Templates

### Target Files and Modules
- `app/models.py`
- `app/routes.py`
- `app/templates/admin/telegram_config.html`
- `app/templates/admin/telegram_command_templates.html`
- `app/templates/base.html`
- `migrations/versions/a4c9d2e7f1b3_add_telegram_command_templates.py`
- `tests/test_security.py`
- `tests/test_schema_migration.py`
- `README.md`
- `ADMIN_QUICK_START.md`

### Intended Behavior Changes
- Allow admins to create and manage custom Telegram slash commands and reply text from the admin interface.
- Keep built-in Telegram commands reserved to prevent workflow/auth regressions.
- Execute active custom command replies in Telegram webhook handling for linked private users.
- Expose custom commands in `/help` output for discoverability.

### Implemented Changes
- Added `TelegramCommandTemplate` model with unique command key, reply text, active state, and timestamps.
- Added additive Alembic revision `a4c9d2e7f1b3_add_telegram_command_templates.py`.
- Added `TelegramCommandTemplateForm` and admin CRUD routes:
	- `/admin/telegram-command-templates`
	- `/admin/telegram-command-templates/<id>/edit`
	- `/admin/telegram-command-templates/<id>/delete`
- Added command normalization/validation helpers with reserved command + prefix protection.
- Added runtime custom command processing in Telegram webhook for active command templates.
- Extended `/help` output to include active custom commands and descriptions.
- Added Telegram Commands links from Telegram Config and admin navigation.
- Added focused tests for template creation, reserved-command rejection, and runtime webhook reply rendering.
- Extended schema tests for `telegram_command_templates` table/migration presence.

### Security / Reliability / Optimization Notes
- Security: Built-in command overrides are blocked (`/start`, `/help`, `/tests`, `/mytests`, `/testing`, `/status`, `/join`) and reserved prefixes (`/status_`, `/join_`) are blocked.
- Security: Custom command processing remains inside existing linked-user/private-chat webhook boundary.
- Reliability: Normalized lowercase command keys avoid case-sensitive duplicates and inconsistent matching.
- Optimization: Runtime lookup is a single indexed query by command + active flag.

### Validation Results
- Focused validation passed: `python -m unittest tests.test_security tests.test_schema_migration` (44 tests, OK).

## Phase 4: Command Categories, Rate Limits, and Args Policies

### Target Files and Modules
- `app/models.py`
- `app/routes.py`
- `app/templates/admin/telegram_command_templates.html`
- `migrations/versions/b6e2d4c8a1f9_add_telegram_command_controls_and_invocations.py`
- `tests/test_security.py`
- `tests/test_schema_migration.py`
- `README.md`
- `ADMIN_QUICK_START.md`

### Intended Behavior Changes
- Add category metadata for custom Telegram commands.
- Add optional argument policies (any, none, required, regex) and failure guidance.
- Add optional per-command, per-chat rate limits.
- Keep built-in command reservation and linked-user/private-chat boundaries intact.

### Implemented Changes
- Extended `TelegramCommandTemplate` with category, args policy/regex/help, and rate-limit fields.
- Added new `TelegramCommandInvocation` table/model for per-command rate-limit accounting.
- Added additive Alembic revision `b6e2d4c8a1f9_add_telegram_command_controls_and_invocations.py`.
- Extended Telegram command template admin form with category, argument, and rate-limit controls.
- Added save-time validation for args policy/regex and rate-limit paired fields.
- Updated webhook command execution to:
	- enforce args policy before reply,
	- enforce per-command rate limits,
	- render custom rate-limit message placeholders,
	- persist invocation rows for accepted command executions.
- Updated custom-command list UI and `/help` output to include category labels.

### Security / Reliability / Optimization Notes
- Security: Commands remain restricted to non-reserved names; built-in and clickable status/join prefixes cannot be overridden.
- Security: Runtime command execution defaults to linked private users unless command-level non-private scope is explicitly enabled.
- Reliability: Regex patterns are validated at save time to prevent runtime regex crashes.
- Reliability: Rate limiting uses persisted invocation records, ensuring deterministic behavior across requests.
- Optimization: Rate-limit checks use indexed filters (`command_template_id`, `chat_id`, `created_at`) to keep lookup cost bounded.

### Validation Results
- Focused validation passed: `python -m unittest tests.test_security tests.test_schema_migration` (47 tests, OK).

## Phase 5: Command Chat/Thread Scope Controls

### Target Files and Modules
- `app/models.py`
- `app/routes.py`
- `app/templates/admin/telegram_command_templates.html`
- `migrations/versions/c9f1e2a4b7d6_add_telegram_command_scope_controls.py`
- `tests/test_security.py`
- `tests/test_schema_migration.py`
- `README.md`
- `ADMIN_QUICK_START.md`

### Intended Behavior Changes
- Let each custom Telegram command opt into non-private execution.
- Allow per-command restriction to explicit Telegram chat IDs.
- Allow optional per-command restriction to explicit topic thread IDs.
- Preserve existing behavior where non-private bot traffic is ignored unless explicitly allowed for a custom command.

### Implemented Changes
- Added new command-template fields:
	- `allow_non_private`
	- `allowed_chat_ids`
	- `allowed_thread_ids`
- Added additive Alembic migration `c9f1e2a4b7d6_add_telegram_command_scope_controls.py`.
- Extended Telegram command template form/UI with non-private toggle and allowlist fields.
- Added save-time parsing/validation for allowed thread ID formats.
- Added shared command-scope evaluation helper and webhook command execution helper.
- Updated webhook flow so non-private chats can execute only command templates that explicitly allow and match configured scope.
- Added regression tests for:
	- scope-field persistence,
	- allowed group+thread execution,
	- disallowed thread suppression,
	- schema presence for new fields.

### Security / Reliability / Optimization Notes
- Security: Default remains fail-closed for non-private traffic; only explicitly scoped commands execute in groups/channels.
- Security: Scoped non-private commands still cannot override built-in command names/prefixes.
- Reliability: Invalid thread allowlist values are rejected at save-time.
- Reliability: Non-matching scope is suppressed in non-private chats to avoid accidental chat noise.
- Optimization: Scope matching is lightweight string/int comparison against stored comma lists.

### Validation Results
- Focused validation passed: `python -m unittest tests.test_security tests.test_schema_migration` (50 tests, OK).

## Admin Settings Hub

### Implemented Changes
- Added `/admin/settings` as the single entry point for admin configuration.
- Grouped existing destinations into Notifications, Bot Integrations, Bot Commands, Message Templates, Payments, and Storage.
- Reduced the Admin navigation menu to one Settings item for configuration pages.
- Kept Create Test, Action Queue, Public Results, and Manage Users in the operational Admin menu; Public Results remains a direct operational workflow.
- Preserved existing configuration routes and keys so this navigation change does not duplicate persistence logic or break existing links.
- Added `/admin/settings/bots` as the canonical provider directory for Telegram, Discord, and Root integrations.
- Added `/admin/settings/commands` as the provider-neutral entry point for the existing shared command registry.
- Added provider anchors and neutral labels without duplicating the existing configuration POST handlers.
- Moved Discord and Root editable fields into the Bot Integrations form; Notification Config now contains only email delivery and diagnostics.
- Added a shared `_save_notification_config_values` helper so provider and email forms persist through one path.

### Security / Reliability / Optimization Notes
- Security: The Settings hub and all linked pages retain the existing admin-only protection.
- Reliability: Existing routes remain canonical, avoiding a migration of configuration data during the navigation change.
- Optimization: The hub performs one configuration lookup for setup-status badges and reuses existing forms/pages.
- Optimization: Provider status and form hydration reuse the existing key/value configuration store without a schema migration.

### Validation Results
- Settings hub regression passed for anonymous, non-admin, and admin users.
- Bot Integrations and Bot Commands navigation regression passed.
- Bot Integrations persistence regression passed for Discord and Root settings.

## Unified Bot Integration Settings

### Implemented Changes
- Moved Telegram provider fields onto the canonical `/admin/settings/bots` page beside Discord and Root.
- Preserved `/admin/telegram-config` as a compatibility route for existing bookmarks, tests, and webhook workflows.
- Added a provider-neutral Bot Status Message Templates editor under Message Templates at `/admin/settings/message-templates/status`.
- Kept status-template configuration keys stable while moving their admin ownership out of Telegram Config.
- Corrected Settings back links from Notification Config, Storage Config, Telegram Config, and Message Templates.
- Preserved masked secret handling for Telegram and Discord tokens.

### Security / Reliability / Optimization Notes
- Security: All provider and template routes remain admin-only; blank secret fields preserve existing secrets.
- Reliability: Existing Telegram webhook action routes and configuration keys remain compatible during the UI migration.
- Optimization: One canonical provider form and shared configuration save helper avoid duplicate persistence logic.
- Save semantics: Bot Integrations writes the complete submitted provider form values, not a field-level diff. Unchanged values are harmlessly rewritten; masked secrets are preserved.

### Provider Lifecycle Notes
- Telegram uses explicit Register/Unregister Webhook actions because Telegram delivers inbound updates through an app webhook.
- Discord uses its gateway process and command synchronization, so it needs connection/sync controls rather than webhook registration.
- Root is outbound-webhook-only and needs a future Send Test Message action rather than registration.

### Validation Results
- Settings consolidation compatibility slice passed.
- Canonical Telegram/Discord/Root persistence regression passed.
- Full unittest discovery completed without reported failures.
- Full security suite passed.
- Route compilation passed; no template diagnostics were reported for the new hub or updated navigation.

## Cross-Platform Public Results Bot Command

### Intended Behavior
- Enable `/publicresults` through the shared Bot Command Registry.
- Show Public Result tags alphabetically, paged 10 per page.
- Show results for a selected tag newest-first by creation date, paged 10 per page.
- Provide only the external COA link; do not expose Group Test results or add a website-result link.
- Require linked users in private Telegram/Discord interactions.
- Permit unlinked group/channel use only when the command's existing non-private and chat/guild/thread scope controls allow it.

### Implemented Changes
- Added shared public-results query logic in `app/public_results_bot.py` using only `PublicResult` tag relationships.
- Added Telegram inline keyboards for tag selection, pagination, back navigation, and COA URL buttons.
- Added Telegram callback-query handling with scope revalidation and message editing.
- Added Discord native `discord.ui.View` buttons with ephemeral response editing and COA link buttons.
- Added the empty state `No Public Results Available.`.
- Added Bot Command Registry guidance explaining `/publicresults` setup and private/group scope behavior.

### Security / Reliability / Optimization Notes
- Security: Group Test records are excluded at the query boundary; private interactions require an account link; group/channel interactions still require configured command scope.
- Security: Callback interactions re-check command scope instead of trusting the original button message.
- Reliability: Both providers cap each page at 10 tags/results and provide back/pagination controls where applicable.
- Optimization: Queries are indexed through the existing tag association and result ordering fields; no duplicate result dataset or provider-specific persistence was added.

### Validation Results
- Five focused public-results tests passed for ordering/exclusion, private linking, scoped group use, callback editing, COA URLs, and empty state.
- Security and notification suites passed.
- All feature modules compiled successfully.

## Media-Enabled Configurable Bot Commands

### Planned Behavior
- Add an `Allow admin bot updates` checkbox to generic bot command configuration.
- Support one optional image per command using the existing private object-storage provider.
- Preserve the existing command text exactly, including plain-text external links such as EzForm URLs.
- Support Telegram and Discord command responses immediately.
- Telegram should send the configured image with the configured text as the message caption.
- Discord should send the configured image as an attachment with the configured text in the same message; embeds are not required for the first implementation.
- Allow a linked Group Test Tracker admin to reply to an existing bot-generated command message in any chat/channel when admin updates are enabled.
- Store provider, chat/channel ID, bot message ID, and command-template ID so replies update only the originating command response.

### Exact Admin Reply Semantics
- Image plus text replaces both the command image and text.
- Image without text replaces the image and clears existing text.
- Text without an image replaces the text and removes the existing image.
- Empty replies are rejected because they would leave the command without a response.
- The bot sends an explicit update confirmation after a successful reconfiguration.

### Planned Data and Transport Changes
- Add command media fields such as `response_image_key` and `allow_admin_bot_updates`.
- Add durable bot-message ownership records for Telegram and Discord provider message IDs.
- Extend storage upload/delete handling for command images and fail closed on invalid or unavailable storage.
- Extend Telegram webhook parsing for admin replies containing photos and text.
- Add Discord message-event handling and the required message-content/message-reference permissions.
- Preserve admin identity checks using linked `User.is_admin`; platform moderator status is not an implicit substitute.

### Security / Reliability / Optimization Notes
- Only linked Group Test Tracker admins may update commands.
- Updates require a reply to a message previously generated by that command.
- Existing command scope controls remain separate from the admin-update authorization policy.
- Replacing media must delete the previous stored object after the database update is safely persisted.
- Provider message ownership prevents admins from editing unrelated bot messages.
- One image per command keeps payload size, storage cleanup, and provider behavior bounded.

### Estimated AI Implementation Effort
- Architecture and data-model design: 2,000-3,000 tokens.
- Storage/model/migration changes: 2,000-3,000 tokens.
- Shared command rendering and ownership tracking: 3,000-4,000 tokens.
- Telegram photo/reply parsing and replacement flow: 3,000-4,500 tokens.
- Discord message-event/attachment/reply flow: 4,000-6,000 tokens.
- Admin UI, upload controls, and status feedback: 2,000-3,000 tokens.
- Security, migration, provider, and regression tests: 4,000-6,000 tokens.
- Documentation and validation/debugging: 2,000-3,000 tokens.

**Estimated total:** approximately **22,000-32,500 AI tokens** for a complete implementation, assuming the existing storage provider and command model remain the foundation. The main uncertainty is Discord message-event permissions and attachment handling, which may require an additional integration/debugging pass.

## Public Results Notifications and JSON Enrichment

### Planned Behavior
- Send a notification when a new `PublicResult` is created through configured Telegram and Discord status destinations.
- Include the public-result title, summary when available, sanitized itemized JSON result values, posted date, and an external COA link/button.
- Do not notify or expose Group Test results through this public-results notification path.
- Enrich `/publicresults` result pages with sanitized summary and itemized JSON values while keeping button labels compact.
- Keep ordinary edits notification-free by default; add an explicit admin re-notify action later if needed.

### Input Normalization and Command-Injection Protection
- Treat `item_results` as untrusted structured input even when entered by an admin.
- Validate that itemized results are JSON objects/rows with bounded field lengths and a bounded total item count.
- Normalize values to plain text before rendering provider messages.
- Escape Telegram HTML/Markdown content and prevent user values from becoming Telegram commands, callback data, mentions, or markup.
- Disable or explicitly control Discord mentions using `allowed_mentions`; prevent `@everyone`, role, and user mention injection.
- Never place arbitrary result text in callback-data values or button URLs.
- Validate external COA URLs before rendering provider link buttons.
- Truncate oversized summaries/result values and provide a safe “View Full Result” path when appropriate.
- Add tests for slash-command-looking text such as `/join`, `/start`, `/publicresults`, bot mentions, HTML tags, Discord mentions, malformed JSON, and oversized values.

### Reliability and Delivery
- Send notifications only after the Public Result database transaction commits.
- Notification failure must not roll back Public Result creation.
- Add an idempotent notification event keyed by Public Result ID and notification event type to prevent duplicate sends on retries.
- Use provider-specific adapters: Telegram formatted text plus inline COA URL button, Discord formatted content plus native link button, and Root text/webhook payload.
- Keep button labels short; detailed JSON belongs in the message body rather than button labels.

### Validation Plan
- Add focused model/helper tests for JSON normalization, field limits, URL validation, and provider escaping.
- Add route tests for post-commit notification dispatch on new Public Results.
- Add Telegram/Discord payload tests proving malicious result text cannot trigger commands, markup, or broad mentions.
- Add `/publicresults` tests covering summary/itemized rendering, empty values, malformed values, and large-value truncation.

## Telegram Media-Enabled Configurable Commands

### Implemented Changes
- Added provider-neutral command fields for one response image and `allow_admin_bot_updates`.
- Added additive migration `b2c4d6e8f0a1_add_command_media_and_bot_messages.py`.
- Added durable `BotCommandMessage` ownership records for Telegram bot message IDs.
- Added admin command-registry image upload, remove-image control, and admin-update checkbox using existing object storage.
- Added Telegram photo/caption response sending through presigned storage URLs.
- Added Telegram admin reply updates for any chat where the sender is a linked Group Test Tracker admin and the command permits updates.
- Exact replacement semantics are enforced:
	- image + text replaces both;
	- image only replaces image and clears text;
	- text only replaces text and removes the existing image;
	- empty replies are rejected.
- Existing text-only commands retain their prior send path unless media or admin updates are enabled.

### Security / Reliability Notes
- Admin updates require `User.is_admin`, a reply to an owned bot message, matching Telegram chat/message ownership, and the command-level opt-in.
- Previous stored images are deleted only after the replacement database update commits.
- Storage validation and signed URL generation reuse the existing result-file security boundary.
- Discord media sending and reply-based updates remain intentionally deferred; labels and model fields remain provider-neutral for that future phase.

### Validation Results
- Telegram exact-replacement regression passed.
- Existing command-registry regression passed.
- Full unittest discovery completed without reported failures.
- Changed Python modules compiled successfully.

## Telegram Admin Command Update Thread-Routing Fix

### Bug
- Admin replies used to update a media-enabled command (`allow_admin_bot_updates`) landed in the wrong Telegram forum topic instead of the topic where the admin's reply occurred.

### Root Cause
- `_process_telegram_admin_command_update` (app/routes.py) never read `message.get('message_thread_id')` and never forwarded it to any of its three `send_telegram_chat_message(...)` calls (the "reply with text/image" prompt, the storage-error message, and the "Command response updated." confirmation). Telegram's `sendMessage` defaults to the chat's general topic when `message_thread_id` is omitted, so replies in non-general topics were silently misrouted. The webhook handler already extracted `message_thread_id` from the incoming update but never passed it into this function.

### Fix
- Added `message_thread_id=None` parameter to `_process_telegram_admin_command_update` and forwarded it to all three `send_telegram_chat_message` calls.
- Updated both call sites in `telegram_webhook` to pass `message_thread_id=message_thread_id`.
- Verified `send_telegram_command_response` (used for the original command send) already threads `message_thread_id` correctly, so no change was needed there.

### Validation Results
- Added `test_telegram_admin_reply_stays_in_originating_message_thread` (tests/test_security.py) asserting the confirmation reply carries the incoming `message_thread_id`.
- Existing `test_telegram_linked_admin_reply_replaces_command_response_exactly` still passes.
- Full unittest suite run (background, long-running due to per-test DB setup); focused regression tests confirmed passing.

## Telegram Admin Command Update: GIF/Animation Support

### Bug
- Replying to a media-enabled command with a GIF produced "Reply with text, an image, or both to replace this command response." instead of updating the command, because Telegram sends GIFs as an `animation` attachment (not `photo`).

### Root Cause
- `_process_telegram_admin_command_update` (app/routes.py) only inspected `message.get('photo')`. GIFs and image-typed documents arrive under `message['animation']` / `message['document']`, so they were never recognized as media.

### Fix
- Extended media detection to accept `photo`, `document` (only when `mime_type` starts with `image/`), or `animation`, falling back through them in that order.
- Reused the existing download/upload/validation pipeline (`download_telegram_photo` → `upload_result_image`) unchanged; genuine non-GIF video animations still fail with a clear `StorageUploadError` message (unsupported format) rather than the previous misleading "no media" prompt.
- Updated the fallback prompt text to mention GIFs.

### Validation Results
- Added `test_telegram_admin_reply_with_animation_updates_command_image` confirming an `animation` reply downloads/uploads and updates `response_image_key`.
- Full unittest suite (130 tests) passes via the workspace `.venv` interpreter.

## Automated Result Analysis Provider Plan Expansion

### Planning Change

- Expanded the approved, implementation-pending result-analysis plan from an OpenAI-first abstraction to concrete OpenAI, xAI Grok, and Anthropic Claude adapters.
- Defined a shared capability-aware `AnalysisDocument` contract, explicit per-run provider selection, common structured extraction schema, normalized errors/usage, and a shared fixture-evaluation gate.
- Planned Grok PDF handling through local text extraction and ordered JPEG/PNG page rendering because its documented vision inputs are JPEG/PNG.
- Planned Claude PDF/image handling through inline base64 Messages content blocks.
- Explicitly excluded silent cross-provider fallback and provider Files APIs from the analysis path.

### Security / Reliability / Performance Notes

- Provider selection is fixed and audited per run so a failure cannot silently transmit a report to another processor.
- Secrets and raw provider errors stay masked; connection tests use minimal text and do not transmit reports.
- Provider-side stored-file lifecycles are avoided; xAI ZDR status is trusted only when returned by the response header.
- PDF extraction/rendering is bounded and performed once for reuse by capability-specific adapters.

### Validation

- Documentation-only validation is recorded in the current `PROJECT_MAP.md` change record.
- No application tests were required because no runtime code or dependencies changed.

## Automated Result Analysis Implementation

### Applied Changes

- Added durable `ResultAnalysisRun` and `ResultAnalysisFinding` persistence with additive Alembic migration `e4b7c9d1a2f3`.
- Added a provider-neutral extraction contract and concrete OpenAI Responses, xAI Grok, and Anthropic Claude adapters.
- Added bounded private-object and ordinary public-web source acquisition, PDF text/page handling, image normalization, source hashing, leasing, retries, deduplication, and safe failure states.
- Added administrator settings, provider connection tests, explicit upload/link queue controls, evidence review, and atomic application.
- New uploads can queue automatically after the owning transaction commits; links remain manual-only.
- Group Test application fills only blank existing rows. Public Result application creates canonical non-duplicate rows. Both retain evidence and append approved metadata to a managed description block.
- Added a dedicated `result-analysis-worker` process entry and documented setup, deployment, review, limitations, and recovery in `README.md` and `ADMIN_QUICK_START.md`.

### Security / Reliability / Performance Review

- Analysis routes remain administrator-only and use existing CSRF protection.
- Provider secrets are environment-first and masked in the UI; raw provider errors and responses are not surfaced or logged.
- Public links reject credentials, non-HTTP(S) schemes, nonstandard ports, private/reserved targets, unsafe redirects, and peer-address mismatches.
- Source size, HTML size, PDF pages, rendered pixels, and total image payload are bounded before provider submission.
- Provider tools, remote file storage, prompt caching, and silent cross-provider fallback are disabled by design.
- Durable jobs use conditional claims, expiring leases, bounded retries, source hashes, and status history; apply rechecks current rows in one transaction.
- Explicit laboratory aggregates are preferred, but the application never calculates missing averages.

### Validation History

- Initial `python -m unittest` discovery returned `Ran 0 tests` because the existing `tests` directory was not a package in this environment.
- Added `tests/__init__.py`; focused automated-analysis coverage then passed 10 tests.
- Actual Alembic schema upgrade coverage passed 3 tests.
- Combined result-analysis, schema, security, and storage coverage passed 80 tests in 102.039 seconds.
- Full discovery passed 145 tests in 180.209 seconds using the bundled Python runtime with dependencies installed into a temporary local target.
- `git diff --check` passed. Remaining warnings are existing Python/SQLAlchemy deprecations around `datetime.utcnow`, `Query.get`, and Flask-Migrate `get_engine`.
- Live provider calls and accuracy/cost evaluation were intentionally not run without production credentials; provider/network tests use mocks.

## Bounded Result Analysis Provider Diagnostics

### Applied Changes

- Added a dedicated JSON-lines diagnostic log for provider connection tests and report-analysis failures.
- Preserved structured SDK context across safe provider errors: exception class, HTTP status, provider error code/parameter, and request ID.
- Displayed recent diagnostics inside the existing administrator-only Result Analysis Settings page.
- Added optional `RESULT_ANALYSIS_DIAGNOSTIC_LOG_PATH` and `RESULT_ANALYSIS_DIAGNOSTIC_LOG_MAX_BYTES` operational overrides.
- Added a narrow `.gitignore` rule so runtime diagnostics are not accidentally committed.

### Security / Reliability / Performance Review

- No API key, report body, report text, or raw provider response is intentionally retained.
- Known OpenAI/xAI/Anthropic and bearer credential patterns are redacted; every field is normalized to one line and length bounded.
- Unexpected internal worker exceptions record their class but omit their detail to reduce report-content exposure risk.
- Jinja auto-escaping prevents provider-supplied HTML or script text from executing in the administrator view.
- The writer uses an exclusive Linux file lock around append/prune operations; read failures and write failures do not alter the provider workflow.
- The log defaults to 128 KiB, cannot be configured above 1 MiB, and prunes its oldest complete entries after crossing the bound. Reads are bounded as well.
- The log is operational rather than durable. Separately deployed web and worker components need a shared configured path to expose one combined log.

### Validation Results

- Focused diagnostics/result-analysis suite: 12 tests passed.
- Combined result-analysis and security suites: 75 tests passed in 97.712 seconds.
- Full unittest discovery: 147 tests passed in 191.616 seconds.
- Final UTC timestamp/redaction refactor: focused 12-test suite passed again.
- `git diff --check` passed. Existing unrelated SQLAlchemy and `datetime.utcnow` deprecation warnings remain.

## DigitalOcean Worker Startup Hardening

### Applied Changes

- Wrapped Discord lifecycle logging and status delivery in short-lived Flask application contexts so startup, ready, and command-error callbacks can safely use database-backed notification configuration.
- Changed the result-analysis Procfile process to `python -m flask --app app:create_app` for explicit interpreter and application-factory discovery.
- Clarified that DigitalOcean's Run Command field accepts only the command after the Procfile label.
- Added regression coverage for Discord lifecycle helpers invoked outside a request/application context.

### Security / Reliability / Performance Review

- Existing Discord token and channel configuration boundaries are unchanged; the patch only establishes context around existing operations.
- Contexts are scoped to individual log/status calls instead of being retained for the lifetime of the asynchronous bot.
- Explicit module invocation avoids reliance on a shell-installed `flask` executable and makes factory discovery deterministic.
- No new network calls, retries, persistent loops, or material hot-path overhead were added.

### Validation Results

- Flask CLI help exposed `result-analysis-worker` using the explicit factory invocation.
- Focused Discord lifecycle and result-analysis coverage passed 13 tests.
- A migrated temporary SQLite database completed `result-analysis-worker --once` successfully.
- The Discord module's missing-token path exited cleanly without an application-context error.
- Full post-fix unittest discovery passed 148 tests in 179.352 seconds.
- `git diff --check` passed; only existing Python, SQLAlchemy, and Flask-Migrate deprecation warnings remain.

## Result Analysis Queue Snapshot Refresh

### Applied Changes

- Closed the read transaction whenever a poll finds no eligible analysis run, ensuring the next poll sees a fresh database snapshot under MySQL's default repeatable-read isolation.
- Removed the scoped SQLAlchemy session after every worker-loop iteration so identity-map and transaction state never persist between polls.
- Added a startup log line that confirms the configured polling interval in DigitalOcean runtime logs.

### Security / Reliability / Performance Review

- Queue authorization and provider selection are unchanged.
- Existing conditional claims still prevent two workers from successfully claiming the same queued row.
- Rollback on an empty read discards no writes, and session removal runs after completed result logging.
- One transaction cleanup per poll adds negligible database overhead relative to the five-second default polling interval.

### Validation Results

- Restarting the DigitalOcean worker immediately processed rows that had remained queued, confirming stale worker transaction state as the failure mode.
- Automated tests were explicitly skipped at the user's request.
- Diff/whitespace and repository-state review passed before commit.

## Unified Administrator Action Queue

### Applied Changes

- Surface result-analysis runs awaiting review or requiring failure intervention in the existing Admin Action Queue.
- Keep result-analysis attention independent from participation filters and pagination while preserving queue context across participation actions.
- Establish the project-wide invariant that every feature requiring administrator approval or attention must contribute an item to the Admin Action Queue until resolved.
- Allow administrators to acknowledge failed analysis runs without changing or deleting the retained failure record.

### Security / Reliability / Performance Review

- Retain the existing administrator-only boundary and Jinja auto-escaping.
- Link to existing review pages instead of duplicating approval mutations.
- Paginate and eager-load the new queue section to keep query count and memory bounded.
- Keep failure acknowledgment POST-only and CSRF-protected, and store the acknowledging administrator and timestamp in existing audit fields.

### Validation Results

- Focused result-analysis and participation suites passed 26 tests in 32.336 seconds.
- Full unittest discovery passed 149 tests in 158.283 seconds.
- Coverage verifies needs-review and failed runs render, resolved runs do not render, participation filters do not hide analysis attention, and acknowledged failures leave the queue while retaining their record.
- The final pagination-context adjustment passed its two targeted Action Queue tests.
- `git diff --check` passed; existing Python, SQLAlchemy, and Flask-Migrate deprecation warnings remain.
