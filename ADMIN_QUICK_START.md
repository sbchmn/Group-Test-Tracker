# Admin Quick Start

This guide is the fastest path to get Group Test Manager running and operational as an admin.

## 1) First-Time Setup

1. Open a terminal in the repository root.
2. Create and activate a virtual environment.
3. Install dependencies.
4. Configure environment variables.
5. Apply database migrations.
6. Create your first admin account.
7. Start the app.

Recommended command sequence:

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
flask --app app db upgrade head
flask --app app create-admin --username admin --email admin@example.com --password change-me
python run.py

Minimum .env values:

SECRET_KEY=replace-with-random-secret
DATABASE_URL=sqlite:///group_tests.db

## 2) Initial Admin Configuration (After Login)

1. Open Admin -> Notification Config.
2. Enter Mailjet values.
3. Optionally enable debug logs.
4. Save.

1. Open Admin -> Telegram Config.
2. Enter Telegram bot token and username.
3. Set status chat target and digest mode/window.
4. Optionally set webhook URL override, webhook secret, and allowed source IP CIDRs.
5. Set Service Base URL for links in templates.
6. Use Register Telegram Webhook to publish webhook settings to Telegram.
7. Save.

1. Open Admin -> Manage Templates.
2. Create or edit templates for:
- password reset
- registration welcome
- participant notifications
3. Mark defaults as needed.
4. Use Open Telegram Status Template Config for Telegram status-specific message templates.
5. Save.

1. From Manage Templates, click Open Telegram Status Template Config.
2. Review Telegram Status Message Templates.
3. Customize digest, new-test, and user status response text using placeholders.
4. Save and test from Telegram.

1. Open Admin -> Telegram Commands.
2. Create custom slash commands (for example `/pricecheck`) with reply text.
3. Optionally set category, args policy (any/none/required/regex), and args help text.
4. Optionally set rate-limit window + max calls and a custom throttle message.
5. Optionally allow non-private use and restrict each command by chat IDs and topic thread IDs.
6. Enable/disable templates as needed.
7. Use optional placeholders such as `{{ username }}` and `{{ args }}`.

Common Telegram template placeholders:
- test_id
- test_title
- old_status, old_status_label
- new_status, new_status_label, new_status_phrase
- test_url
- mentions
- denied_reason
- order_status
- amount_owed, amount_paid

## 3) Optional: Enable Result Image Uploads

1. Open Admin -> Storage Config.
2. Enable object storage uploads.
3. Select provider:
- AWS S3
- DigitalOcean Spaces
4. Fill bucket/space, region, access key, and secret key.
5. Set endpoint URL if needed.
6. Keep public-read upload disabled for private-bucket mode.
7. Set signed URL TTL to 60 seconds.
8. Save.

AWS S3 example:
- Provider: AWS S3
- Bucket: my-group-test-results
- Region: us-east-1
- Endpoint URL: leave blank (typical)

DigitalOcean Spaces example:
- Provider: DigitalOcean Spaces
- Space: my-results
- Region: nyc3
- Endpoint URL: https://nyc3.digitaloceanspaces.com

Secure access behavior:
- Group test images are accessible only to admins or approved+paid participants.
- Public result images are accessible only to logged-in users.
- Image links are signed on demand and expire automatically.

## 4) Optional: Enable Automated Result Analysis

Automated analysis extracts reported laboratory values into an administrator review queue. It never publishes a value without review and does not provide medical interpretation.

1. Apply the latest database migration:
`flask --app app db upgrade head`
2. Add the API key for each provider you intend to use to the deployment environment:
- `OPENAI_API_KEY`
- `XAI_API_KEY`
- `ANTHROPIC_API_KEY`
3. Open Admin Settings -> Result Analysis.
4. Enable only configured providers and verify the model identifiers.
5. Choose the active provider used for automatic upload runs.
6. Keep automatic analysis disabled initially and run the provider's Connection Test. It sends minimal text, not a report.
   - If it fails, inspect Recent Provider Diagnostics on the same page for the sanitized HTTP status, provider code, parameter, and request ID.
7. Deploy/start the separate worker process:
`python -m flask --app app:create_app result-analysis-worker`
8. Upload a synthetic/sample report, use Analyze Uploaded File on its edit page, and review the extracted suggestions.
9. Enable automatic analysis after the dry run behaves correctly.

DigitalOcean/Procfile process type:
- Procfile entry: `result-analysis-worker: python -m flask --app app:create_app result-analysis-worker --poll-seconds 5`
- DigitalOcean Run Command: `python -m flask --app app:create_app result-analysis-worker --poll-seconds 5` (omit the `result-analysis-worker:` Procfile label)

Discord bot worker:

- DigitalOcean Run Command: `python -m app.discord_bot`
- Give the web and Discord worker components the same `DATABASE_URL` and bot configuration environment.
- After saving a new or changed command, open Admin Settings -> Bot Integrations and click **Synchronize Commands** in the Discord card. The running worker normally processes the request within five seconds and writes its status back to that page.
- A configured Discord Guild ID produces fast guild-scoped registration and also publishes global commands for bot DMs. Leaving it blank registers commands globally only. Global command propagation can take longer than guild registration.
- Custom-command text and configured images, GIFs, or MP4 loops are shared with Discord. Media is attached from private storage with an 8 MiB per-response limit; keep reply text configured when a textual fallback is desired.

Daily review behavior:

- New eligible uploads queue after the Group Test or Public Result record commits.
- Links never queue automatically. Use Analyze Linked Result on the edit page.
- Open Review Findings, verify the evidence and confidence, accept/reject each row, correct accepted text if needed, and optionally append metadata.
- Optional Telegram COA workflow: enable `/submitcoa` under Built-in Bot Commands, allowlist any groups/topics, and optionally set a dedicated review chat/topic. Linked users submit a PDF/image or public link; linked admins name, edit, select, and publish or reject it in that same review conversation.
- Group Tests only fill blank existing test rows.
- Public Results can add recognized canonical rows.
- Non-empty values are never overwritten. Unrecognized and conflicting findings remain review-only.
- Explicit report Net/Average/Batch Average values are preferred; no average is calculated by the app.
- A failed provider run never silently switches to a different provider.

Source boundaries:

- Upload formats are inherited from Storage Config. PDF, JPEG, PNG, WebP, and first-frame GIF analysis are supported when allowed there.
- Public HTTP/HTTPS PDF, image, and static HTML links are supported within the configured limits.
- Login-required, cookie-dependent, authenticated, CAPTCHA, anti-bot, private-network, and nonstandard-port sources are rejected. Download and upload those reports manually.
- Default ceilings: 20 MB, 25 PDF pages, 2 MB HTML, three redirects, and three worker attempts.

## 5) Daily Operating Flow

1. Create tests from Admin -> Create Test.
2. Keep recruiting tests open while collecting requests.
3. Move to ready_for_payment when you want payment options shown before active testing.
4. Use Admin -> Action Queue for result-analysis review/failures and participant approval/denial across tests.
5. Use Manage Participants inside each test for detailed per-user updates.
6. Send participant notifications from test detail pages.
7. Move tests to testing and then closed when complete.
8. Publish broader results from Admin -> Public Results.

## 6) Group Test Setup Checklist

1. Title, description, dates.
2. Vendor, batch, compound, size.
3. Lab/provider and itemized lab rows.
4. Cost fields: lab, shipping, donor-shipping, refund per donor.
5. Status selection:
- recruiting: collecting requests
- ready_for_payment: approved users can review payment instructions before testing
- testing: active processing, no new joins
- closed: results can be shown to approved members
6. Assign payment options for this test (optional but recommended for paid workflows).
7. Optional tags for search/grouping.
8. Optional result file upload (image or PDF) when closed.

## 7) Payment Options Quick Setup

1. Open Admin -> Payment Options.
2. Add one option per method/payee combination.
3. For app methods, confirm generated payment link and QR preview.
4. For crypto methods, set network carefully and verify address formatting.
5. Activate/deactivate options as needed; in-use options are protected by safe-delete behavior.
6. Assign relevant options per test in Create Test or Edit Test.

## 8) Public Results Checklist

1. Title and optional summary.
2. Required results link.
3. Optional itemized result rows.
4. Optional tags.
5. Optional image upload.

Result image behavior:
- Thumbnail appears in results views.
- Clicking thumbnail opens full-size modal or embedded PDF preview.
- Modal includes download action.
- Replacing file removes old file best-effort.

## 9) User and Access Management

1. Admin -> Manage Users for account changes.
2. Use Toggle Active for temporary access control.
3. Use admin password reset action when needed.
4. Keep admin accounts minimal and controlled.

Telegram account-linking notes:
- Users must open the bot and press Start before Telegram direct delivery can work.
- Telegram delivery depends on stored linked chat identity, not just username text.
- The configured Telegram status group/topic is outbound-only for status posts; users should use a private DM with the bot for commands.
- The one public exception is `/testing`, which replies with sign-up and login links in a group or channel.
- Bot command quick reference for participants:
- `/tests` lists visible tests in ascending test-number order.
- `/mytests` lists only their own pending/approved/denied group-test interactions in ascending test-number order.
- Both list commands include per-test clickable `/status_<test_id>` hints and `/join_<test_id>` when that recruiting test can still be joined.
- `/testing` returns sign-up and login links for Group Test Manager.
- `/status <test_id>` returns their current status for a specific test, including denied records. For closed tests where they are marked paid, it returns the results URL.
- Active admin-created custom commands also appear in `/help` under Custom commands.

## 10) Troubleshooting Quick Hits

Storage upload fails:
1. Verify Storage Config is enabled.
2. Verify bucket/region/credentials.
3. Verify endpoint/public URL values.
4. Verify bucket policy/object readability.

Notifications fail:
1. Verify Notification Config keys.
2. Verify Telegram Config keys.
3. Verify recipient email and Telegram linking status.
4. Enable notification debug logs.
5. Review notification log in Notification Config page.
6. Re-run Register Telegram Webhook after changing bot token or base URL.
7. For status channel posts, verify chat target format and optional thread suffix.

Migrations fail:
1. Activate venv.
2. Re-run flask --app app db upgrade head.
3. Verify DATABASE_URL and DB access.

Result analysis remains queued or fails:
1. Confirm the `result-analysis-worker` process is running.
2. Confirm the run's selected provider is enabled and configured.
3. Run `python -m flask --app app:create_app result-analysis-worker --once` for one safe status check.
4. Confirm the worker can read the private object-storage bucket.
5. For linked sources, confirm the page is public and does not require login, cookies, or anti-bot interaction.
6. Review Recent Provider Diagnostics under Admin Settings -> Result Analysis. The log excludes credentials/report content and automatically drops old entries at 128 KiB by default (1 MiB hard maximum).

## 11) Pre-Release Admin Checklist

1. Run tests:
python -m unittest

2. Verify core admin pages load:
- Dashboard
- Action Queue
- Manage Users
- Notification Config
- Telegram Config
- Telegram Commands
- Storage Config
- Public Results
- Result Analysis settings and review page

3. Verify one end-to-end dry run:
- Create recruiting test
- Submit request from non-admin account
- Approve from Action Queue
- Switch test to ready_for_payment and verify payment panel/link/QR renders correctly
- Close test and set results link
- Confirm appearance in My Results
- Upload a sample report, process it with `result-analysis-worker --once`, review findings, and confirm existing values are not overwritten

4. Verify Telegram flow:
- Generate Telegram link from a user profile
- Complete /start in bot
- Trigger a status update and confirm channel post formatting
- Trigger password reset via Telegram for linked user

## 12) Security Best Practices

1. Use strong SECRET_KEY and rotate when required.
2. Use least-privilege object storage credentials.
3. Rotate Mailjet/Telegram/storage secrets periodically.
4. Keep debug logging disabled in normal production operations.
5. Limit number of admin users and review access regularly.
6. Use webhook IP allowlists where possible and re-check after infrastructure changes.
7. Keep unused analysis providers disabled and store provider keys in deployment secrets.
8. Review every extracted value and its evidence before applying it.
