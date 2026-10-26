Registration notification setup
===============================

Registration offers Email and the configured personal messaging methods that can
complete account linking. It still redirects to Login without signing the member
in. Email remains active while the chosen messaging method is pending.

The linking page appears after login until the member links, chooses Email, or
reaches seven days from registration. Linking activates the chosen method; skip
and expiration retain Email. Members can change preferences later in My Profile.
The linking page preserves a safe local login destination and uses the existing
single-use provider token mechanism with CSRF-protected actions.

Duplicate protections compare account usernames without case differences, and
Telegram/Discord handles without case differences, surrounding whitespace, or a
leading `@`. Registration, admin creation, and identity changes cannot introduce
duplicates. Database constraints also reject simultaneous new account creations
with the same normalized name. Existing duplicate accounts are grandfathered:
the migration keeps their original values, links, credentials, and account IDs;
owners may keep their existing names while editing other profile information.
The existing Telegram username delivery fallback and username tags are preserved.

Deployment requires the included Alembic migration (`flask --app run db upgrade`).
No application database was migrated as part of this review; automated checks use
temporary databases. The migration preserves SQLite's deleted-ID high-water mark.

Browser review covers registration, duplicate validation, Telegram linking, and
Discord linking at 320, 390, 820, 1024, 1280, and 1440px. Screenshots and
`browser-checks.txt` are in this directory. The review script uses temporary data
and the locally installed Edge browser through the cached Playwright package.
