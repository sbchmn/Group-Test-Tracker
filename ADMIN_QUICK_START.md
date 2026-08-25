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
2. Enter Mailjet and/or Telegram values.
3. Set Service Base URL for links in templates.
4. Save.

1. Open Admin -> Manage Templates.
2. Create or edit templates for:
- password reset
- registration welcome
- participant notifications
3. Mark defaults as needed.
4. Save.

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

## 4) Daily Operating Flow

1. Create tests from Admin -> Create Test.
2. Keep recruiting tests open while collecting requests.
3. Use Admin -> Action Queue to approve/deny quickly across tests.
4. Use Manage Participants inside each test for detailed per-user updates.
5. Send participant notifications from test detail pages.
6. Move tests to closed and set results link when complete.
7. Publish broader results from Admin -> Public Results.

## 5) Group Test Setup Checklist

1. Title, description, dates.
2. Vendor, batch, compound, size.
3. Lab/provider and itemized lab rows.
4. Cost fields: lab, shipping, donor-shipping, refund per donor.
5. Status selection:
- recruiting: collecting requests
- testing: active processing, no new joins
- closed: results can be shown to approved members
6. Optional tags for search/grouping.
7. Optional result image upload (if storage enabled).

## 6) Public Results Checklist

1. Title and optional summary.
2. Required results link.
3. Optional itemized result rows.
4. Optional tags.
5. Optional image upload.

Result image behavior:
- Thumbnail appears in results views.
- Clicking thumbnail opens full-size modal.
- Replacing image removes old image best-effort.

## 7) User and Access Management

1. Admin -> Manage Users for account changes.
2. Use Toggle Active for temporary access control.
3. Use admin password reset action when needed.
4. Keep admin accounts minimal and controlled.

## 8) Troubleshooting Quick Hits

Storage upload fails:
1. Verify Storage Config is enabled.
2. Verify bucket/region/credentials.
3. Verify endpoint/public URL values.
4. Verify bucket policy/object readability.

Notifications fail:
1. Verify Notification Config keys.
2. Verify recipient email/Telegram values.
3. Enable notification debug logs.
4. Review notification log in Notification Config page.

Migrations fail:
1. Activate venv.
2. Re-run flask --app app db upgrade head.
3. Verify DATABASE_URL and DB access.

## 9) Pre-Release Admin Checklist

1. Run tests:
python -m unittest

2. Verify core admin pages load:
- Dashboard
- Action Queue
- Manage Users
- Notification Config
- Storage Config
- Public Results

3. Verify one end-to-end dry run:
- Create recruiting test
- Submit request from non-admin account
- Approve from Action Queue
- Close test and set results link
- Confirm appearance in My Results

## 10) Security Best Practices

1. Use strong SECRET_KEY and rotate when required.
2. Use least-privilege object storage credentials.
3. Rotate Mailjet/Telegram/storage secrets periodically.
4. Keep debug logging disabled in normal production operations.
5. Limit number of admin users and review access regularly.
