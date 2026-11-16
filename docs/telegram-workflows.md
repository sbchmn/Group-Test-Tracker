# Telegram COA intake and public-results menus

## Configuration

Open **Admin → Settings → Built-in Bot Commands** (`/admin/settings/commands/builtins`).

COA intake still requires an active, linked GTM account and uses the existing
analysis queue and administrator review. It does not publish submissions directly.

- Sending `/submitcoa` without a source produces a selective reply prompt. The
  requesting user can reply in the same chat/topic with a PDF, image, HTTP/HTTPS
  link, or both a file and a link. Prompts expire in 24 hours and are consumed
  after a successful submission. A caption or Telegram hidden link is supported.
- Enable **Automatically submit attachments and links** to watch the allowed
  submission chats. `/submitcoa` and non-private use must also be enabled, and
  explicit Chat IDs must be configured. An empty chat allowlist never enables
  watching everywhere. Optional Thread IDs narrow collection to those topics;
  thread IDs are interpreted within each allowed chat. For different topic
  policies per group, configure one group at a time until per-chat rules exist.
- Bot accounts, commands addressed to other bots, other slash commands, edited
  messages, and administrator review replies are excluded from passive intake.
  Photos/PDFs/images and HTTP/HTTPS links qualify. One message creates one COA;
  an album arrives as multiple messages and creates multiple submissions. The
  first link is used if a message contains several links.
- Give the bot administrator access, or disable privacy mode through BotFather,
  so it receives ordinary group messages. Channel posts without an attributable
  linked user are skipped; this feature does not assign anonymous posts to an
  arbitrary GTM account.

Public-results menus default to a **300-second** timeout (configurable from 10
to 86,400 seconds). Each menu belongs to its requesting user. Close and timeout
attempt to delete both the menu and the command that opened it. Navigation does
not reset the timeout. Failed edits leave the same menu in place for a retry.
Even the empty-results message is tracked and expires.

Ephemeral replies default to enabled in Telegram groups/supergroups. They use
`ephemeral_message_parameters.receiver_user_id`, with the corresponding
`editEphemeralMessageText` and `deleteEphemeralMessage` methods. The bot needs
administrator access for an initial ephemeral response to a normal command.
If Telegram rejects the ephemeral response, the bot posts an ordinary public menu
in the same group/topic, with the same owner-controlled buttons, timeout, and
cleanup of the menu and initiating command. Disable the setting to always use
ordinary shared messages with owner-controlled buttons. Private chats retain
their usual private messages. Discord behavior is unchanged.

Ephemeral delivery, updates, and deletion are best-effort at the Telegram client;
Telegram may discard ephemeral messages when a client restarts. Normal group
command deletion requires administrator/delete-message permission. A failed
delete is retried up to five times, with a log entry if cleanup is abandoned.

## Deployment

Apply migrations before starting the updated web and worker processes:

```sh
python -m flask --app app:create_app db upgrade
```

Restart the existing web and result-analysis processes after applying migrations.
Cleanup runs inside the existing `result-analysis-worker` polling loop; no new
process, scheduler, hosting component, or paid worker is required. It runs even
when the analysis queue is empty. With the existing five-second poll interval,
idle cleanup starts on the next poll. A running analysis job can delay deletion
until it finishes; expired menus reject navigation immediately when clicked.
Network errors and insufficient permissions can also delay deletion. Cleanup
errors are isolated so they do not prevent analysis jobs from running. The
existing process must remain running for automatic deletion during quiet periods.

Ownership and expiry are stored in `telegram_interactions`, so web-worker
restarts do not lose pending cleanup. Deletion work uses a short database lease
to avoid concurrent cleanup. Closed menu records are retained for one day, and
expired COA prompts are pruned. Existing menus from before this deployment retain
their legacy navigation/close behavior and have no automatic cleanup record.

Telegram references: [ephemeral messages](https://core.telegram.org/bots/api#ephemeral-messages-and-commands),
[deleteMessage permissions](https://core.telegram.org/bots/api#deletemessage),
[privacy mode](https://core.telegram.org/bots/features#privacy-mode).

## BST topic moderation

BST is independent of group-test participation and COA review. Applicants and
Telegram group admins do not need GTM accounts or account links. Vendor identity
comes from the numeric Telegram user ID supplied by Telegram, not a typed ID or
changeable username. Approval applies only to the configured group/topic pair
and lasts until revoked.

### Setup and application links

In GTM, open **Admin > B/S/T Vendors > Add BST topic**. Enter a label, numeric
negative group Chat ID, and positive topic ID. Alternatively, a Telegram group
admin or linked GTM admin can run `/bstadmin` inside the intended group topic,
or send `/bstadmin <group_chat_id> <topic_id>` in the bot DM. New policies start
with enforcement disabled. Before enabling, the bot checks that it is a group
administrator with Delete Messages permission.

Each topic has a reusable Apply to Sell link. Copy it from the GTM topic settings
into group rules or welcome messages. The `/bstadmin` topic menu can post an
onboarding card, or explicitly post and pin it; pinning also requires the bot's
Pin Messages permission. The link contains a public destination code, not an
account-link token or posting authorization. `/bst` in the topic also returns
its application button. Private group names and vendor details are not listed
to arbitrary users who open the bot.

### Applicant workflow

1. Open the topic's Apply to Sell link to start or resume an application in DMs.
   No GTM login, registration, or account linking is required.
2. The bot captures Telegram ID and asks for vendor name, email, vendor
   guarantees, dispute resolution contact, and dispute resolution process.
   Drafts are saved. Reopening the link resumes the draft or displays its status,
   rather than creating duplicate applications.
3. Review the answers, edit any field, optionally complete required email
   verification, and submit for review. Full answers remain accessible through
   **View complete application**, including answers longer than a menu summary.
4. Use `/bst` to return to applications and decisions. The applicant receives
   decision notifications in Telegram; a blocked DM does not undo the decision.

**Request changes** returns the same application to the applicant for revision.
**Denied** applications may also be revised and resubmitted. Both actions require
an applicant-visible reason. Drafts and applications awaiting applicant changes
are not pending admin work. **Revoked** approval can only be restored by an admin,
with a reason; reopening the link or resubmitting cannot bypass revocation.

An approved vendor may propose profile changes. Their previously approved
information and posting permission stay active while the changes are edited or
reviewed. Approval replaces the active profile. Denial or a change request leaves
the previous approved profile intact. The GTM review page shows both profiles;
Telegram reviewers can open **Full application / Approved profile** to compare.

### Email verification and admin-created vendors

Each topic independently controls **Require verified vendor email**. Disabled
means syntax validation only. Enabled means applicants must verify before
submitting, and posting requires a verified approved email.

Verification uses GTM's existing Mailjet email configuration. The bot sends a
six-digit code, expires it after 15 minutes, allows at most five attempts per
code, and limits resending to once per minute per application. Only a salted hash
is stored. Enter the code in the bot DM; verification does not create a GTM
account. Failed mail delivery produces an actionable error instead of marking
the address verified.

Admins can **Create and approve vendor** from GTM or `/bstadmin`, supplying the
numeric Telegram ID and required vendor information before that user applies.
An existing record must be managed rather than overwritten. If verification is
required, the preapproval is recorded immediately but posting remains blocked
until the vendor opens `/bst` and verifies their email. Admin creation cannot
silently bypass the configured email requirement. Turning verification on for
an existing topic similarly requires previously unverified vendors to verify.
Changing an email in a proposed profile does not invalidate a previously verified
approved email while that proposed change awaits review.

### Admin review, notification, and permissions

Pending BST applications appear in the **same Admin Action Queue table** as join
requests, payment reports, and result-analysis work. All types share sorting,
search, pagination, and an item-type filter. The test-status filter applies to
join/payment rows; it does not hide BST applications. Join-request checkboxes and
bulk approval/denial remain limited to join requests. The BST review page retains
queue filters and page when returning after a decision.

The dedicated B/S/T menu supports topic configuration, application review,
approved vendor management, preapproval, revocation, and restoration. It is a
management view of the same records, not a second required inbox.

In Telegram, `/bstadmin` offers those same actions in DMs. All current admins and
owners of the relevant group qualify automatically, without a GTM link. The bot
rechecks group authority on every management action. Linked, active GTM admins
also qualify. Group-derived authority is scoped to the relevant group and never
grants general GTM website administrator access. Vendor/application details are
only displayed privately to the applicant or authorized reviewers.

On submission, linked active GTM admins and Telegram group admins with linked,
active GTM profiles receive notifications through their configured GTM
notification channel, with the existing email fallback. Group admins do not
need a GTM administrator role to use their linked profile's notification channel.
Unlinked Telegram group admins receive no automatic notification; they find
pending applications in `/bstadmin`. No separate review chat or broadcast to all
group admins is required. Recipient authority is checked again before delivery.
Notifications are durable and retried up to five times
inside the existing process. Only one decision can succeed for a particular
application revision; stale cards/forms must be reopened. Decisions and submitted
profiles are retained in the audit history with the actor's Telegram/GTM identity.

### Topic content rules and enforcement

Configure these options independently per topic:

| Setting | Initial value |
| --- | --- |
| Text-only listings | Allowed |
| Photos | Allowed |
| Image documents | Disallowed |
| Captions | Allowed |
| Photo albums | Allowed |
| Links | Disallowed |
| Require an image | Off |
| Require captions on image listings/albums | Off |
| Forwarded listings | Disallowed |
| Verified email | Not required |

Dependent settings are validated: requiring an image needs an allowed image
format; requiring captions needs captions and an image format; albums need
photos. Image documents are checked from downloaded bytes rather than trusting
their filename or MIME type. Videos, audio, stickers, other files, and unsupported
media are removed. Album caption requirements apply across the whole album,
not independently to its uncaptained fragments. Album state is briefly buffered
and retained for one day to support moderation of caption edits.

Protected topics are vendor listings only. Unapproved users' messages, including
buyer replies and human admin listings, are deleted. Review/configuration rights
do not grant vendor posting permission. Approved vendors must comply with the
configured content rules. Anonymous posts cannot inherit an admin's approval.
The bot's own notices and Telegram service events are excluded from moderation.
BST commands are handled separately; normal commands in protected topics do not
bypass moderation or become COA submissions.

Both new and edited posts are checked. Edited updates never replay application,
COA, or other state-changing commands. Re-register the Telegram webhook after
upgrading so Telegram delivers edited-message updates.

After a successful removal, the user gets a reason and application button. If
DMs are unavailable, the bot posts a temporary topic notice. Reminders are limited
to once per user/topic per five minutes and topic notices expire after 60 seconds.
Failed deletion is logged and retried; the bot does not claim successful removal
when deletion failed. Retries are bounded to five maintenance attempts.

### Existing infrastructure and deployment

No extra hosting component, worker process, scheduler, or email service is added.
Apply the migrations, restart the existing web/result-analysis processes, and
re-register the Telegram webhook. The existing result-analysis loop performs
notification delivery, album evaluation, and deferred deletion/notice cleanup.
A running analysis job can delay deferred work until the job finishes. Ordinary
unauthorized messages are deleted immediately in the webhook request; Telegram
permissions/network availability still determine whether removal succeeds.

The new tables are `bst_topics`, `bst_vendors`, `bst_events`, `bst_notices`,
`bst_conversations`, and `bst_messages`. Accounts and group-test participation
remain separate. Disabling a policy stops topic enforcement; revoking a vendor
removes their posting approval without deleting their decision history.

Telegram references: [deep linking](https://core.telegram.org/bots/features#deep-linking),
[getChatMember](https://core.telegram.org/bots/api#getchatmember), and
[message deletion](https://core.telegram.org/bots/api#deletemessage).
