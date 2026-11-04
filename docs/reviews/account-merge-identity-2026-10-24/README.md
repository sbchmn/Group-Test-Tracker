# Merged participant identity correction

October 24, 2026. All verification used disposable local accounts and databases.

The reported case was a paid participation belonging only to the duplicate account. Ownership transferred correctly during the merge, but the separate saved participant name still contained the duplicate's name. Both participant lists, payment review and exports preferred that saved name over the account username.

Future merges now set transferred and combined participant records to the primary username and retained Telegram handle. Original labels remain in the merge audit. Membership, charges, payment status, review timestamps, transaction IDs and proof files retain their existing merge behavior.

Migration `c5e7a9b1d3f4` repairs completed merges using exact participant IDs and affected tests from the audit records. It changes identity fields only when they still match the post-merge audit snapshot. It skips removed/reassigned records and preserves later manual name/handle edits. Each repaired row's revision increases to invalidate stale open payment forms. The repair does not recalculate charges, change payment verification, rewrite proof history or send notifications.

## Validation

- **78 targeted tests passed**: account merging, automatic/frozen pricing, payment proofs, participant removal and schema migrations. See [tests.log](tests.log).
- The regression test checks a paid participation unique to the duplicate: the primary name appears on both pages, the payment API identifies the primary, and assigned/paid amounts, verification and original evidence survive.
- A second regression covers overlapping tests when duplicate membership/payment values are chosen.
- The data-repair test recreates an older merge's saved labels and checks repaired identity, untouched payments/proofs, unrelated rows, changed ownership, subsequent manual edits and repeat upgrade behavior.
- **25 real Chrome layout checks passed** across 320, 390, 820, 1024 and 1440 pixels. The browser merged a paid record unique to the duplicate, verified the transferred record and its original transaction, then checked both participant lists for the primary name. See [browser.log](browser.log) and [metrics.json](metrics.json).
- The tablet Manage Participants and phone group-detail screenshots were visually inspected: both show the primary username and retain the paid status.

## Screenshot proof

| Participant page | Phone | Tablet | Desktop |
| --- | --- | --- | --- |
| Group detail | [390 px](paid-transfer-group-participant-390.png) | [820 px](paid-transfer-group-participant-820.png) | [1440 px](paid-transfer-group-participant-1440.png) |
| Manage Participants | [390 px](paid-transfer-manage-participant-390.png) | [820 px](paid-transfer-manage-participant-820.png) | [1440 px](paid-transfer-manage-participant-1440.png) |

## Apply the correction

After updating the application, run `flask --app run.py db upgrade` to repair prior merges. There is no need to merge those accounts again. The existing development/live database was not changed during verification.
