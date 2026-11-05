# Optional branding and appearance review — 2026-10-24

Implemented version 4.2 against baseline `e79ba83` (Version 4.1). Changes are
uncommitted at review time. The staged implementation checklist is in
[`../../plans/2026-10-24-optional-whitelabeling.md`](../../plans/2026-10-24-optional-whitelabeling.md).

## Delivered behavior

Any customer administrator can enable branding in **Admin → Settings → Branding &
Appearance**, with no new entitlement. The editor supports app identity, logo and
favicon uploads, light/dark colors, locally served font choices, help destinations,
and built-in legal-page operator details. Members can keep the site default or
choose light, dark, or device preference.

Drafts and their images are private. Administrators preview real public/auth/legal
templates and sample dashboard/email content, then publish a saved draft. Public
previews show visitor navigation and disable interactions. Revision checks reject
stale edits; publication history supports restore. Returning to GTM branding keeps
the saved draft and legal details. Attribution remains visible.

Published images have stable URLs and are stored in the database with revision
history. Logos are validated and stripped of metadata; no object-storage setup is
required. Published images remain available for existing emails and restores.
Database backups must include these tables.

Email display names/wrappers and default bot wording use published identity.
Existing custom message bodies, explicit Discord webhook names, transport
credentials, account links, and Telegram username delivery fallback are preserved.
Bot profiles and email sender addresses remain in their existing integration
settings. Internal product/control-plane identities remain canonical GTM values.

## Automated validation

The broad regression command was:

```powershell
python -m pytest tests/test_branding.py tests/test_security.py tests/test_notifications.py tests/test_control_plane.py tests/test_bot_identity.py tests/test_root_bridge.py tests/test_telegram_bot_retorts.py tests/test_account_merge.py tests/test_schema_migration.py tests/test_registration_setup.py tests/test_payment_proofs.py tests/test_managed_integrations.py -q --disable-warnings --maxfail=5
```

Result: **386 passed, 50 subtests passed**. See `regression-tests.txt`.

After the final contrast, identity, version, and preview changes:

```powershell
python -m pytest tests/test_branding.py tests/test_security.py::SecurityTests::test_version_page_and_footer_expose_application_version tests/test_telegram_bot_retorts.py -q --disable-warnings --maxfail=1
```

Result: **39 passed, 37 subtests passed** (`branding-and-retort-tests.txt`). A
subsequent branding/version check after visitor-preview navigation changes passed
**20 tests and 16 subtests** (`branding-tests.txt`). A fresh control-plane run
passed **13 tests** (`control-plane-tests.txt`). These counts overlap; they are not
an aggregate count of unique tests. Existing deprecation warnings remain.

Two final email checks also pass (`email-tests.txt`): sender display name and
wrapper use the same published settings snapshot, custom message bodies remain
intact, and logos use stable customer URLs.

Coverage includes migration upgrade/downgrade and SQLite deleted-ID preservation,
draft isolation, CSRF/role/subscription boundaries, conflicting edits, publish and
restore, image validation/privacy/stable URLs, readable colors, theme persistence,
safe theme redirects, preserved custom templates, and branded bot persona text.
Compilation and `git diff --check` pass.

## Browser review

`check_responsive.py` uses a temporary database and the locally cached Playwright
package with Edge. The full run passed **150 layout checks** at 320, 390, 820,
1024, 1280, and 1440 pixels. Both themes cover the editor, real dashboard, settings,
users, profile, action queue, test detail, payment modal, public welcome, login,
registration, and terms. A separate six-width preview checks an unbroken 80-character
app name and 32-character short name. The script also exercises publication, both
local fonts, private email previews, and live device-theme changes.

Screenshots capture representative phone, tablet, and desktop layouts. After the
last landing-logo adjustment, a follow-up public-page run checks light/dark logo
visibility, long-name navigation, status-badge contrast, and twenty-four layouts
(`public-logo-checks.txt`).

Earlier checks found and resolved:

- An initial module syntax error was corrected before workflow validation.
- Three early workflow assertions needed fixture corrections: a literal HTML
  ampersand and authenticated requests to `/` redirecting to the dashboard.
- A contrast test caught a 4.39:1 near-black button foreground; using true black
  and deriving hover/link colors fixed the failed minimum contrast check.
- The first browser run completed all layout checks but checked a device-theme
  change before its media event ran. Waiting for the resulting theme attribute
  fixed the check; live device switching now passes.
- Visual review found dim secondary buttons in dark mode; their text and border
  colors were corrected before final screenshots.
- The longest permitted short name could wrap the mobile menu button onto a new
  line. Reserving its full width fixed that case; the follow-up browser check
  explicitly verifies that the button remains beside the brand.
- Dark-theme warning/info badges retain dark text on their bright backgrounds;
  light badges use the dark theme's surface/text pair. The follow-up test measures
  the real status badges' contrast rather than relying on screenshots alone.

## Deployment

Run `flask --app run db upgrade` before serving the updated code. Migration
`e7a9b1c3d5f6` adds branding state, revisions, binary assets, and member theme
preferences. Existing deployments start with their original GTM identity and light
default. No existing application database, external integration, or domain was
changed during implementation or review.

Provider deliveries are tested with mocks. Live Mailjet/bot delivery and production
database migration remain deployment checks.
