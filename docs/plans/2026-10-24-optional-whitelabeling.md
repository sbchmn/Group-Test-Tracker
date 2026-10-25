# Optional GTM white-labeling

Status: implemented and validated in version 4.2. Deployment migration remains an
operator step; no existing application database was changed during implementation.

## Implementation task list

- [x] Shared draft/published settings, revision history, validation, and branding assets.
- [x] Theme foundation and persistent member/device preferences.
- [x] Responsive admin editor, protected previews, publish, restore, and reset.
- [x] Apply branding to pages, legal/help content, emails, and bot wording.
- [x] Automated checks, migration checks, responsive review, and documentation.

Validation records and screenshots:
[`../reviews/whitelabeling-2026-10-24/README.md`](../reviews/whitelabeling-2026-10-24/README.md).

## Agreed scope

Any customer administrator can enable and configure white-labeling. No separate
paid entitlement or platform-operator approval is required. Existing deployments
keep their current GTM appearance until an administrator publishes changes.

Customers already have a `customer.grouptest.online` address. Branding uses that
existing address; this project does not add domain provisioning or DNS setup.

White-labeling covers the application, public pages, registration and login,
legal-page branding, help links, email presentation, and bot message wording. A
small, non-removable **Powered by GTM** credit remains.

Admins can select fonts and configure light/dark appearance while retaining the
existing page layouts and responsive behavior. Admins choose the default theme;
members can select light, dark, or their device preference.

Admins edit a draft, preview desktop/tablet/mobile, and explicitly publish it.
Draft changes do not affect members or outgoing messages.

## Settings and boundaries

| Area | Planned settings and behavior |
| --- | --- |
| Identity | Enable white-labeling; display name; optional short name for narrow spaces; tagline and introductory text. Text fields use plain text with length limits. |
| Images | Primary logo, optional dark-background logo, and favicon. Preserve aspect ratios and supply accessible text/fallbacks. Uploaded images use validated raster formats and generated size variants. |
| Colors | Controlled brand accent, navigation, and surface settings for light/dark palettes. Derive text, borders, focus, hover, and disabled states. Status colors retain clear success/warning/error meanings. No arbitrary CSS or layout editor. |
| Fonts | A small curated, locally served selection, including the current system font. No arbitrary font URLs or customer font uploads in this release. |
| Themes | Admin default: light, dark, or device preference. A member's explicit choice overrides that default; choosing device preference follows the device. Include a way to return to the site's default. |
| Help | Support contact and optional user-help/admin-help links. Admin-help links remain restricted to admins. Existing managed documentation destinations remain defaults. Branding links do not change platform billing or support-access endpoints. |
| Legal | Continue using GTM's built-in Terms and Privacy text. Substitute the customer app name and configured operator/contact details, including the existing legal fields. No policy text editor or external policy replacement in this release. |
| Email | Use the published brand name for the default sender display name and branded message wrapper. Existing sender addresses, credentials, verified-domain configuration, and customized message bodies remain in place. |
| Bots | Use the published display name in application-generated help, onboarding, linking instructions, and default messages. Existing customer message templates and explicitly configured webhook names keep their values. Provider-side bot names, usernames, avatars, and registrations remain managed through their existing integrations/provider tools. |
| Attribution | Show the credit in the site footer and default email footer; include it in bot help/about output rather than appending it to every chat message. Preserve software licensing and third-party notices. |

Custom branding replaces customer-facing GTM identity. Internal product/version
metadata, control-plane identifiers, entitlement names, environment variable names,
provider identity IDs, and existing URLs remain stable.

Existing customized message bodies are never rewritten automatically. Add explicit
brand variables for templates and explain how admins can use them. Previously sent
messages and uploaded documents are not retroactively changed.

## Administrator workflow

Add **Branding & Appearance** to Admin Settings. Organize the editor into identity,
images, colors/fonts, themes, help/contact details, and legal/operator details.

1. Save edits to a persistent draft. Show validation beside the relevant field.
2. Preview the draft privately in desktop, tablet, and phone sizes. Include the
   public landing page, login/registration, a populated dashboard, a table/card
   view, and legal pages. Offer light/dark previews and a sample email.
3. Publish the complete validated draft in one operation. Published branding is
   used by page requests, email senders, and bot workers.
4. Allow discarding a draft, restoring the previous published revision, and
   publishing a return to the default GTM branding.

Publishing/restoring requires administrator authorization and CSRF protection.
If two admins edit the same draft, a revision check prevents one from silently
overwriting the other's changes. Record who published each revision and when.

Turning off white-labeling restores GTM identity and default branding links, while
retaining the customer's saved draft/assets for later use. Legal operator/contact
details, integration credentials, member accounts, and notification preferences
are not reset by a branding toggle. Previously selected member themes remain
available; the initial default for existing sites stays light.

## Implementation approach

### 1. Shared branding settings

Add typed, versioned draft/published settings and an audit record. Centralize
validation and default resolution in one branding service, shared by web requests
and background workers. Use the existing per-customer deployment/database boundary.
Do not turn the control plane into a second branding editor.

Keep a published revision/cache key so workers pick up changes without being
restarted. A new deployment must work with no branding record and resolve to GTM
defaults. Existing legal environment settings remain fallback values when no
customer setting has been published.

### 2. Asset handling

Use a dedicated branding asset path with stable published URLs and revisioned
filenames. Reuse existing storage infrastructure where appropriate, while keeping
draft assets inaccessible to ordinary visitors and preserving published assets
needed by rollback revisions. Published logos must be reachable by email clients.

Branding uploads must not require a customer to configure result storage first;
define a deployment-supported persistent fallback for sites without object
storage. Validate file content, dimensions, and size, and generate required variants.
Do not reuse expiring private-result links for public brand images.

### 3. Theme foundation

Replace hard-coded light colors with shared theme variables across templates,
tables, responsive cards, forms, menus, payment dialogs, status badges, and focus
states. Build on Bootstrap's existing theme support. This is an application-wide
visual pass, not just a new body background.

Save authenticated members' theme preferences with their accounts so choices
follow them across devices. Remember anonymous choices per browser. Apply the
resolved theme before the page paints to avoid a light flash on dark pages.
Device-preference mode reacts to device changes.

### 4. Branding editor and preview

Build the responsive draft editor with protected previews of actual application
templates and representative sample data. Preview must not send email or bot
messages, publish changes, or expose private customer records. Show the exact
validation problems that would prevent publication, including unreadable color
combinations and missing required image variants.

### 5. Apply branding to customer-facing surfaces

Replace hard-coded identity in shared navigation/footer, page titles, landing,
login/registration/linking screens, legal pages, default emails, bot help, and
system-generated messages. Preserve existing custom message templates and explicit
integration overrides. Keep Version/About and copyright notices accurate while
using the customer display name where appropriate.

### 6. Validate and document

Test enable/disable, defaults, draft isolation, publish/restore, multiple-admin
conflicts, member theme precedence, anonymous themes, asset replacement, and
cross-process adoption of published revisions. Check that settings stay within
the intended customer deployment and ordinary members cannot edit or preview
draft branding.

Review important screens at 320, 390, 820, 1024, 1280, and 1440px in both themes,
including long app names, wide/tall logos, missing images, keyboard navigation,
payment modals, and responsive tables. Verify readable email output and unchanged
delivery/linking behavior for Telegram, Discord, and Root.

Document the admin workflow, image requirements, integration overrides, and
default/rollback behavior. Include migrations and deployment instructions.

## Completion criteria

A customer admin can publish a consistent brand across the agreed surfaces
without modifying code or asking the platform operator. Members can choose their
theme without disturbing the site's branding. Drafts remain private, publication
is reversible, and existing sites retain their current behavior until configured.
The Powered by GTM credit remains visible, and the current desktop/tablet/mobile
layout quality is preserved in both themes.

## Implementation decisions

The font list is System Sans, Figtree, and Lora. Figtree and Lora are bundled with
their SIL Open Font License notices and served by GTM. The editor pairs color
pickers with hex inputs and derives readable text, hover, and link colors.

Uploaded PNG/JPEG/WebP images are limited to 2 MB and 16 megapixels, converted to
metadata-free PNG, and resized within 1600 × 800 pixels. Browser icon variants
are 32 × 32 pixels. The primary logo is the fallback browser icon.

Images are stored in the customer database, avoiding dependencies on optional
result storage or ephemeral application disks. Published assets have immutable
URLs, and old published assets remain available for emails and revision restores.
Draft assets require administrator access. Database backups include the assets.

Customer help URLs are branding-layer overrides. Existing managed documentation,
billing, support-access, and control-plane settings retain their existing contract.
