# Group Test Manager

Group Test Manager is a Flask-based web app for coordinating group lab tests, participant requests, cost sharing, result publishing, and notification-driven follow-up without spreadsheets.

This README is a practical how-to guide for every major feature in the app.

Quick admin one-pager: [ADMIN_QUICK_START.md](ADMIN_QUICK_START.md)

## Table of Contents

- [What This App Includes](#what-this-app-includes)
- [Application Map](#application-map)
- [Setup and Run](#setup-and-run)
	- [1. Install](#1-install)
	- [2. Configure Environment](#2-configure-environment)
	- [3. Apply Migrations](#3-apply-migrations)
	- [4. Create Initial Admin User](#4-create-initial-admin-user)
	- [5. Run](#5-run)
- [Feature How-To (By Role)](#feature-how-to-by-role)
- [End User How-To](#end-user-how-to)
	- [Register and Login](#register-and-login)
	- [Reset Password](#reset-password)
	- [Update Your Profile](#update-your-profile)
	- [Use Dashboard](#use-dashboard)
	- [Request Participation](#request-participation)
	- [Update Your Participation Status](#update-your-participation-status)
	- [View Results (My Results)](#view-results-my-results)
- [Admin How-To](#admin-how-to)
	- [Create Group Test](#create-group-test)
	- [Edit Group Test](#edit-group-test)
	- [Delete Group Test](#delete-group-test)
	- [Manage Participants (Per Test)](#manage-participants-per-test)
	- [Admin Action Queue (Cross-Test)](#admin-action-queue-cross-test)
	- [Manually Add Participant](#manually-add-participant)
	- [Set Results Link Quickly](#set-results-link-quickly)
	- [Manage Public Results](#manage-public-results)
	- [Manage Users](#manage-users)
	- [Manage Payment Options](#manage-payment-options)
	- [Notification Templates](#notification-templates)
	- [Notification Config](#notification-config)
	- [Send Notifications to Test Participants](#send-notifications-to-test-participants)
	- [Export Test Data](#export-test-data)
- [Object Storage and Result Image Upload How-To](#object-storage-and-result-image-upload-how-to)
	- [Configure Storage](#configure-storage)
	- [AWS S3 Settings Example](#aws-s3-settings-example)
	- [DigitalOcean Spaces Settings Example](#digitalocean-spaces-settings-example)
	- [Upload and Display Behavior](#upload-and-display-behavior)
	- [Bucket Policy and Security Recommendations](#bucket-policy-and-security-recommendations)
- [Access and Visibility Rules](#access-and-visibility-rules)
- [Notification Template Variables](#notification-template-variables)
- [Testing and Validation](#testing-and-validation)
- [Troubleshooting](#troubleshooting)
	- [Storage Upload Says Disabled or Misconfigured](#storage-upload-says-disabled-or-misconfigured)
	- [Images Upload But Do Not Render](#images-upload-but-do-not-render)
	- [Notifications Not Delivering](#notifications-not-delivering)
	- [Migration Errors](#migration-errors)
- [Key Files](#key-files)

## What This App Includes

- Account registration, login, logout, profile management, and password reset.
- Group test lifecycle management (recruiting, ready_for_payment, testing, closed).
- Participant request, approve, deny, reopen, and status management.
- Cost split automation with donor-credit logic.
- Admin Action Queue for cross-test pending approvals.
- Dashboard controls for search, grouping, sorting, and hide/unhide.
- My Results page that combines closed group-test results and public results.
- Public Results CRUD for admins, including itemized lab values.
- Result file upload with S3-compatible object storage (AWS S3 or DigitalOcean Spaces), including image and PDF support.
- Payment option matrix with method-aware payment links, destinations, and QR payload previews.
- Telegram bot account linking, webhook processing, status channel posts, digest mode, and Telegram password reset delivery for linked users.
- Editable Telegram status message templates with variables for channel updates and user status replies.
- Notification templates/configuration for email/Telegram.
- Excel export for test backups/reporting.

## Application Map

- App factory and config: [app/__init__.py](app/__init__.py)
- Data models: [app/models.py](app/models.py)
- Main routes/forms/business logic: [app/routes.py](app/routes.py)
- Notification transport and templating: [app/notifications.py](app/notifications.py)
- Object storage and image validation: [app/storage.py](app/storage.py)
- Templates: [app/templates](app/templates)
- Migrations: [migrations/versions](migrations/versions)

## Setup and Run

### 1. Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the project root.

Minimum values:

```env
SECRET_KEY=replace-with-random-secret
DATABASE_URL=sqlite:///group_tests.db
```

Optional values:

```env
FLASK_ENV=development
NOTIFICATION_LOG_MAX_BYTES=200000
MAX_CONTENT_LENGTH_MB=12
```

Notes:

- `SECRET_KEY` is required outside test mode.
- If `DATABASE_URL` is missing, the app falls back to local SQLite.
- `MAX_CONTENT_LENGTH_MB` sets a global request-size ceiling.

### 3. Apply Migrations

```bash
flask --app app db upgrade head
```

### 4. Create Initial Admin User

```bash
flask --app app create-admin --username admin --email admin@example.com --password change-me
```

### 5. Run

```bash
python run.py
```

## Feature How-To (By Role)

## End User How-To

### Register and Login

1. Open Register.
2. Enter username, email, password, and optional Telegram username.
3. Submit and log in from the Login page.

### Reset Password

1. Open Password Reset.
2. Enter your username.
3. Choose delivery channel (email or Telegram).
4. Submit to receive a temporary password.

Telegram note:

- Telegram reset requires a linked bot chat. If not linked, open the bot and press Start first, then retry Telegram reset.

### Update Your Profile

1. Open My Profile.
2. Edit username, email, Telegram username, and notification preferences.
3. Optionally set a new password.
4. Save Profile.

### Use Dashboard

Dashboard shows tests based on visibility rules:

- Recruiting tests are visible to all authenticated users.
- Testing/Closed tests are visible to admins and approved participants.

Steps:

1. Use search to find tests by title/metadata.
2. Use Group By and Sort controls.
3. Click Request Join on recruiting tests.
4. Click Hide to remove a test from your personal dashboard view.
5. Use the show-hidden option to unhide as needed.

### Request Participation

Two paths are available:

1. Quick request from Dashboard card.
2. Detailed request from test detail page.

State behavior:

- Pending requests show as pending.
- Denied requests show denial reason (if provided).
- If denied and still recruiting, you can reapply.

### Update Your Participation Status

If approved:

1. Open a test detail page.
2. Click Update My Order and Payment Status.
3. Update order progress, payment flags, amount paid, and notes.
4. Save.

Payment method behavior:

- If the test is in ready_for_payment or testing and payment options are configured, you can choose your preferred payment method and view generated destination/link/QR details.

### View Results (My Results)

1. Open My Results.
2. Use search/group/sort to filter combined results.
3. Click Open Results for source link.
4. If a thumbnail exists, click it to open full-size modal image.
5. If the result file is a PDF, the modal opens an embedded PDF preview and includes a direct download action.

Note:

- Group test result images are issued through authenticated signed URLs.
- You must be an approved participant marked as paid (or admin) to open group test result images.

## Admin How-To

### Create Group Test

1. Open Admin -> Create Test.
2. Fill basic metadata (title, vendor, batch, compound, size, dates, description).
3. Add optional tags (comma-separated).
4. Add lab/provider and itemized lab rows.
5. Fill cost fields (lab, shipping, donor-shipping, refund-per-donor).
6. Set status (recruiting, ready_for_payment, testing, or closed).
7. Select allowed payment options for this test if payment collection is in scope.
8. If status is closed, add results link and optional result file upload (image or PDF).
9. Save.

### Edit Group Test

1. Open test -> Edit Test.
2. Update fields, lab rows, tags, and status.
3. Update payment options assigned to the test as needed.
4. Update or remove result file if needed.
4. Save.

Important behavior:

- If status is changed away from closed, results link and result file are cleared.

### Manage Payment Options

1. Open Admin -> Payment Options.
2. Create method entries for Venmo, Cash App, PayPal, Crypto Wallet, or Other.
3. Fill destination details by method (handle, link, wallet address, network, or custom fields).
4. Use generated matrix preview to confirm destination label, payment link, and QR payload behavior.
5. Toggle Active to hide/show options for new assignments.
6. Edit existing options to refine details.
7. Delete unused options. If an option is already assigned or selected, delete safely deactivates it.

### Delete Group Test

1. Open Edit Test.
2. Use Delete Test in the danger area.
3. Confirm.

### Manage Participants (Per Test)

1. Open Admin -> Manage Participants from a test.
2. Approve pending requests.
3. Deny with required reason.
4. Reopen denied requests.
5. Remove participant if needed.
6. Recalculate costs after major membership changes.

### Admin Action Queue (Cross-Test)

Use for fast pending-request triage across all tests.

1. Open Admin -> Action Queue.
2. Filter by status and keyword.
3. Approve or deny single requests.
4. Select multiple rows for bulk approve/deny.
5. Use Approve All Filtered for large backlogs.
6. Enter confirmation text when prompted for filtered bulk approval.

### Manually Add Participant

1. Open Manage Participants for a test.
2. Click Add Participant.
3. Select user.
4. Submit to auto-approve.

If the user was previously denied for that test, the record is reactivated and approved.

### Set Results Link Quickly

1. Open a test detail page as admin.
2. Use quick close/results form.
3. Submit to set link and close test if needed.

### Manage Public Results

1. Open Admin -> Public Results.
2. Create a result with title, summary, tags, link, and itemized lab rows.
3. Optionally upload a result image.
4. Save.
5. Use Edit to update values/image.
6. Use Delete to remove entries.

### Manage Users

1. Open Admin -> Manage Users.
2. Create users or edit existing users.
3. Toggle active state.
4. Trigger password reset delivery for selected user.

### Notification Templates

1. Open Admin -> Manage Templates.
2. Create or edit template fields:
- email subject
- email body
- telegram body
3. Mark defaults for password-reset and registration-welcome templates.
4. Mark templates hidden from participant-notify picker if needed.
5. Use Open Telegram Status Template Config to jump to Telegram status-specific templates.

### Notification Config

1. Open Admin -> Notification Config.
2. Configure Mailjet keys/sender email.
3. Configure Telegram bot token and bot username.
4. Configure Telegram webhook URL override (optional) and allowed source IP CIDRs (optional).
5. Configure Telegram status chat target. Thread targets are supported using chatId_threadId format.
6. Configure digest mode and digest window.
7. Edit Telegram status message templates (linked from Notification Templates) and variables for:
- digest header
- digest line item
- digest participants line
- new-test channel post
- user /status no-request reply
- user /status denied reply
- user /status approved reply
- user /status pending reply
8. Set service base URL (used for fully qualified links in templates and Telegram message links).
9. Use Register Telegram Webhook / Unregister Telegram Webhook actions to manage bot webhook from the UI.
10. Optionally enable debug logs.
11. Save.

### Send Notifications to Test Participants

1. Open a test detail page as admin.
2. Pick a notification template in Notify Test Participants.
3. Send.

The app renders participant-specific values (including amount owed) per recipient.

### Export Test Data

1. Open test detail page.
2. Click Export to Excel.
3. Download `.xlsx` backup/report.

## Object Storage and Result Image Upload How-To

Result files are optional and uploaded to S3-compatible storage.

### Configure Storage

1. Open Admin -> Storage Config.
2. Enable object storage uploads.
3. Select provider:
- AWS S3
- DigitalOcean Spaces
4. Set bucket/space name.
5. Set region.
6. Set Access Key ID and Secret Access Key.
7. Optionally set endpoint URL.
8. Keep Upload with public-read ACL disabled for private-bucket mode.
9. Set signed URL TTL (seconds). Recommended: 60.
10. Set path prefix, max upload size, and allowed formats.
11. Save.

### AWS S3 Settings Example

- Provider: AWS S3
- Bucket: `my-group-test-results`
- Region: `us-east-1` (or your region)
- Endpoint URL: blank (usually)
- Public Base URL: optional (blank usually fine)

### DigitalOcean Spaces Settings Example

- Provider: DigitalOcean Spaces
- Bucket/Space: `my-results`
- Region: `nyc3` (or your region)
- Endpoint URL: `https://nyc3.digitaloceanspaces.com`
- Public Base URL: `https://my-results.nyc3.digitaloceanspaces.com`

### Upload and Display Behavior

- Upload on Group Test create/edit when results are present.
- Upload on Public Result create/edit.
- Thumbnails and modal previews are fetched through app-controlled authenticated routes.
- The app generates short-lived signed object URLs on demand (default 60 seconds).
- Group test result images require admin access or approved plus paid participation in that test.
- Public result images require login.
- PDFs are supported for result uploads and render in embedded modal preview with download option.
- Replacing image deletes old object best-effort.
- Clearing image removes object key and attempts remote delete.

### Bucket Policy and Security Recommendations

1. Use least-privilege API keys scoped to target bucket/path.
2. Rotate credentials regularly.
3. Use lifecycle rules for stale object cleanup.
4. Keep secrets in secure env/deployment secret stores.
5. If using private buckets, implement signed URLs (not enabled by default).

## Access and Visibility Rules

- Admin-only routes are protected by login and admin checks.
- CSRF is enabled for forms.
- Group test visibility:
- Recruiting: visible to authenticated users.
- Ready_for_payment/Testing/Closed: visible to admins and approved members.
- Results links/images for group tests are shown only when closed and user is authorized.
- Group test result images specifically require admin or approved+paid participant access before signed URL issuance.

## Notification Template Variables

Use double-curly placeholders, for example `{{ username }}`.

Supported variables:

- `username`
- `new_password`
- `amount_owed`
- `test_title`
- `test_link`
- `test_id`
- `login_url`

Telegram status template variables:

- `test_id`
- `test_title`
- `old_status`
- `old_status_label`
- `new_status`
- `new_status_label`
- `new_status_phrase`
- `status`
- `status_label`
- `status_phrase`
- `test_url`
- `mentions`
- `denied_reason`
- `order_status`
- `amount_owed`
- `amount_paid`

## Testing and Validation

Run full suite:

```bash
python -m unittest
```

Useful focused runs:

```bash
python -m unittest tests.test_schema_migration tests.test_security
python -m unittest tests.test_participant_removal
python -m unittest tests.test_notifications
```

## Troubleshooting

### Storage Upload Says Disabled or Misconfigured

Check Admin -> Storage Config:

1. `storage_enabled` equivalent checkbox is on.
2. Bucket, region, access key, and secret are populated.
3. Endpoint/public URL values are valid for your provider.

### Images Upload But Do Not Render

1. Verify object is present in bucket/space.
2. Verify public URL pattern or custom base URL.
3. Verify object ACL/bucket policy allows read.

### Notifications Not Delivering

1. Verify Notification Config keys.
2. Verify user has channel-compatible address and linked Telegram chat if Telegram delivery is expected.
3. Enable debug logging and inspect notification log in Admin -> Notification Config.
4. For Telegram bot delivery, verify webhook registration status and that bot token includes full value (including colon separator).
5. For Telegram status channel posts, verify status chat target format and optional thread suffix.

### Migration Errors

1. Ensure virtual environment is active.
2. Run `flask --app app db upgrade head`.
3. Confirm DB URL credentials and network access.

## Key Files

- [app/__init__.py](app/__init__.py): app factory, extension wiring, config, CLI.
- [app/models.py](app/models.py): SQLAlchemy models.
- [app/routes.py](app/routes.py): forms, routes, business rules.
- [app/storage.py](app/storage.py): S3-compatible image upload, validation, URL construction.
- [app/notifications.py](app/notifications.py): notification rendering and transport.
- [app/templates](app/templates): UI templates.
- [migrations/versions](migrations/versions): schema migration history.
