# Group Test Manager Release Notes

This file records the product and engineering changes preserved in the repository
history. Dates and version labels are shown only when the history documents them.
The original release date and semantic version were not recorded; that baseline is
identified explicitly below.

## Unreleased

### Security and licensing hardening

- Added Flask-Limiter throttling for login and password-reset POST requests.
- Added same-origin validation for the login `next` redirect parameter.
- Made password-reset responses uniform so account existence is not disclosed.
- Added baseline security response headers: content-type sniffing protection,
  same-origin framing protection, referrer policy, and HTTPS HSTS behavior.
- Removed user-controlled values from dynamic admin form HTML interpolation by
  assigning them through DOM properties.
- Replaced the GPLv3 project license with a proprietary commercial license that
  requires prior written authorization before deployment, operation, copying,
  modification, or redistribution.
- Added reviewed direct and transitive dependency notices in
  `THIRD_PARTY_NOTICES.md`.
- Added license and third-party attribution information to the Version page.
- Identified PyMuPDF's AGPL/commercial licensing choice as a distribution gate.

## 4.0 - 2026-09-16

### Managed SaaS and control-plane parity

- Added signed control-plane bootstrap and support endpoints.
- Added replay protection and idempotent operation receipts for control-plane
  requests.
- Added reserved support-account immutability, credential versions, expiry, and
  session-epoch invalidation.
- Added entitlement and subscription-state gating for managed deployments.
- Added managed public URL and user/admin documentation URL handling.
- Added signed instance-to-control-plane events with bounded status/resource data.
- Added worker startup status reporting and managed readiness behavior.
- Added support-access request and emergency-disable actions.
- Added recovery export handling with sanitized data.
- Added required `run-discord-bot` and `run-result-analysis-worker` CLI entry
  points for managed process provisioning.
- Added regressions for canonical event signing and managed URL isolation.
- Hardened unknown subscription states to fail closed and prevented caller data
  from overriding authoritative event types.

### Automated result analysis

- Added durable result-analysis runs, findings, leases, duplicate handling, and
  administrator review/apply workflows.
- Added OpenAI, xAI Grok, and Anthropic provider adapters with explicit provider
  selection and bounded source acquisition.
- Added provider diagnostics with bounded, sanitized status information.
- Added upload and public-link analysis queueing for Group Tests and Public
  Results.
- Added Telegram COA submission intake and administrator review integration.
- Added a dedicated result-analysis worker command and DigitalOcean startup
  hardening.
- Added explicit analysis-run duplicate bypass support.

## 2026-09-12

### Public Result source and publishing improvements

- Allowed Public Results to use an uploaded image/PDF without an external link.
- Added route-level validation requiring at least one result source.
- Preserved existing files until a replacement prospective state was valid.
- Fixed `#`, blank, `None`, `null`, and `about:blank` result links so Telegram
  uses the authenticated Public Result fallback URL.
- Added approval validation requiring a Public Result name.
- Added Telegram review name/value reply handling and publication coverage.

## 2026-09-11

### Telegram COA review and Public Results

- Added linked-user `/submitcoa` intake for PDF/image attachments and HTTP(S)
  report links.
- Created queued Public Results and durable analysis runs for Telegram COAs.
- Added administrator review controls for finding selection, corrected values,
  evidence, result naming, metadata, approval, and rejection.
- Added source context, direct submitted-link access, and retained uploaded
  report files on reviewed Public Results.
- Added staged link, file, and tag editing before approval.
- Added paginated tag selection with ten tags per page and Save/Cancel controls.
- Added a dedicated Public Result page with Back to My Results navigation and
  authenticated inline image/PDF rendering.
- Added image-only Public Results Telegram navigation fallback.
- Added bounded Telegram callback diagnostics and fresh-message recovery when
  edit operations fail.
- Preserved Telegram forum-thread routing and normalized malformed thread/message
  IDs.

## 2026-09-10

### Result storage, analysis planning, and operational documentation

- Added the automated result-analysis implementation plan and acceptance criteria.
- Added private S3-compatible/AWS S3/DigitalOcean Spaces storage support.
- Added authenticated result-image routes with short-lived signed URLs.
- Added upload size/type validation and provider-aware storage configuration.
- Added secure result access for administrators and approved, paid participants.
- Added image/PDF thumbnails, modals, and download actions across result views.
- Added backward compatibility for legacy image-only storage format settings.
- Expanded README and administrator quick-start documentation.

## 2026-08-25

### Production result image hosting

- Added result image uploads for Group Tests and Public Results.
- Added S3-compatible object storage integration for AWS and DigitalOcean Spaces.
- Added administrator Storage Config UI for credentials, buckets, endpoints, and
  upload constraints.
- Added stored image-key schema fields and additive migration support.
- Added result thumbnails and full-size modal viewing.

## 2026-08-20

### Participant workflow and administrator action queue

- Added the administrator Action Queue for centralized pending-participant review.
- Added queue filtering, pagination, single actions, bulk approval, and filtered
  approval with explicit confirmation.
- Added dashboard quick-request actions and Pending, Approved, Joined, and Denied
  participation states.
- Added denied-request persistence with timestamp and reason.
- Added user reapply flow for denied participation requests.
- Added administrator deny, reopen, reactivate, and manual-add parity across the
  Action Queue and Manage Participants pages.
- Added denial visibility and reasons to dashboard, test detail, and management
  views.
- Fixed nested action forms and tightened row-level queue action behavior.

## Historical feature development

The following capabilities were developed after the initial baseline. The
repository history does not assign each item a formal release number or calendar
date, so they are grouped by product area rather than assigned invented versions.

### Initial release baseline - date not recorded

- Introduced the Flask Group Test Manager application and initial SQLAlchemy
  schema.
- Added users, administrators, Group Tests, participants, costs, statuses,
  results links, and notification configuration.
- Added Flask-Login authentication, password hashing, forms, CSRF protection,
  and administrator authorization.
- Added the initial Alembic revision `54b86edcab2f`.

### Group Tests, results, and dashboard

- Added recruiting, ready-for-payment, testing, and closed lifecycle states.
- Added lab details, itemized lab results, costs, shipping, reimbursements, and
  participant balance calculations.
- Added dashboard grouping, sorting, searching, filtering, and per-user hidden
  test state.
- Added My Results aggregation for eligible Group Test and Public Result content.
- Added Public Results administration, tags, itemized result rows, and publishing
  state.
- Added paid-participant result visibility enforcement and administrator bypass.
- Added exports and secure result-file access.

### Payments

- Added reusable payment options and per-test payment-option assignments.
- Added participant payment-option selection and historical snapshots.
- Added payment method profiles for Venmo, Cash App, PayPal, crypto wallets, and
  custom methods.
- Added provider-specific payment links, QR payloads, branding, and validation.
- Preserved payment selection as guidance rather than payment proof or accounting
  state.

### Notifications and scheduling

- Added email, Telegram, Discord, and Root notification channels.
- Added post-commit delivery behavior and bounded transport timeouts.
- Added configurable notification templates and provider-specific rendering.
- Added hourly/daily user digest preferences, durable digest events, and the
  `flask send-user-digests` command.
- Added Telegram status-channel digests, duplicate suppression, thread targets,
  configurable status templates, and ready-for-payment messaging.
- Added notification log isolation, sanitization, and bounded cleanup.

### Telegram integration

- Added Telegram webhook handling with configured secret validation, JSON checks,
  replay protection, optional source-IP allowlists, and duplicate-update storage.
- Added one-time account-link tokens, private chat binding, stable Telegram user
  IDs, and linked-user authorization.
- Added `/start`, `/help`, `/tests`, `/mytests`, `/status`, `/join`, `/testing`,
  and `/publicresults` workflows.
- Added Telegram password-reset delivery with email fallback behavior.
- Added configurable command templates, argument policies, regex validation,
  rate limits, chat/thread scope controls, and administrator updates.
- Added image, GIF, and MP4 command media support.
- Restricted ordinary command replies to private chats while retaining the public
  `/testing` onboarding path for groups and channels.

### Discord and Root integrations

- Added Discord account linking and command invocation records.
- Added Discord native interactions, early deferral, scoped Public Results
  browsing, tag callbacks, close controls, and DM/global command support.
- Added Discord guild synchronization and on-demand command refresh handling.
- Added configurable Discord and Root webhook notifications.
- Added custom command media parity with bounded attachments, mention suppression,
  and text fallbacks.
- Preserved application-admin authorization as distinct from provider moderator
  status.

### Administration and operations

- Added consolidated administrator Settings navigation for notifications, bots,
  commands, templates, payments, storage, and result analysis.
- Added dedicated Telegram configuration and webhook registration controls.
- Added masked secret preservation for provider configuration forms.
- Added readiness endpoint `/health/ready`.
- Added legal Terms and Privacy pages and Version-page plan information.
- Added worker commands and deployment documentation for web, Discord, and result
  analysis processes.

## Schema history

All schema changes are additive Alembic revisions. The current chain begins at
`54b86edcab2f` and ends at `b3c4d5e6f7a8`.

- `54b86edcab2f` - Initial schema.
- `f67a5b9c1d2e` - Add lab name.
- `084c3f28ae26` - Compatibility revision for historical Alembic state.
- `f5d832cd8f6a` - Notification, profile, and user fields.
- `9b7f1c2d4a5e` - Tags, Public Results, and dashboard hiding.
- `7c1a2b3d4e5f` - Public Result item results.
- `8f4d1e2a9b7c` - Participation denial fields.
- `c3d9e1f4a7b2` - Result image keys.
- `d12f4a9b8c7e` - Telegram linkage and payment options.
- `e3a1c9d4b7f2` - Telegram replay and digest tables.
- `f0c4a6b1d9e2` - User digest scheduling and event queue.
- `a4c9d2e7f1b3` - Telegram command templates.
- `b6e2d4c8a1f9` - Command controls and invocation logs.
- `c9f1e2a4b7d6` - Command chat/thread scope controls.
- `a7d9f1c2b3e4` - Discord linking and command invocations.
- `b2c4d6e8f0a1` - Bot command media and message ownership.
- `e4b7c9d1a2f3` - Durable automated result-analysis runs and findings.
- `d8a4f2c6b9e1` - Analysis duplicate bypass.
- `e9c2a7d4b6f1` - Public Result draft and Telegram review state.
- `f2b6c9a1d4e7` - Control-plane nonces and operation receipts.
- `a1b2c3d4e5f6` - Reserved support-account marker and session epoch.
- `b3c4d5e6f7a8` - Support credential state and expiry metadata.

## Validation milestones

- Initial and feature-specific focused unittest suites were added throughout the
  project history.
- The managed control-plane, security, notification, participant, storage, cost,
  and result-analysis test areas have dedicated regression coverage.
- Full-suite counts varied as features were added; the latest documented full
  regression before the current release-note and licensing work was 193 tests.
