# Account merge and username validation

Implemented October 24, 2026. Screenshots use disposable local accounts and databases. No live accounts or storage objects were changed.

## Workflow

Open **Admin → Manage Users → Merge Duplicate Accounts**. Choose the primary account and duplicate, preview, resolve any overlaps, then confirm.

- The primary retains its username, email, password, permissions, active status and notification preferences.
- For each shared test, explicitly choose which membership/donor details, assigned charge and payment/verification record survive. Amounts are never automatically added together. Unique participation records transfer intact.
- Both payment proof histories and notes survive. The unselected payment history is marked as archived by the merge; it cannot become the current report merely because it was submitted later. Proof IDs and image keys remain intact.
- Missing messaging links transfer; conflicting Telegram, Discord or Root links require a choice.
- Ownership, reviewer references, hidden dashboard records and digest records transfer. Duplicate pending digest entries are consolidated.
- Frozen shares remain fixed. Unlocked Recruiting tests recalculate the funding cohort quietly after duplicate participation rows are combined.
- The duplicate account is removed. Both accounts' sessions and unused link tokens are invalidated. SQLite user IDs cannot be reused by a later account. Legacy sessions without an epoch cannot bypass invalidation.
- An audit row preserves the administrator, account identities, original participant values, chosen resolutions, transferred reference counts and final values. System accounts, the signed-in duplicate and merges removing the last active administrator are blocked. Changes since preview require a fresh preview.

New usernames and changed usernames reject leading, embedded and trailing whitespace, including tabs and Unicode whitespace. Forms show the error without silently trimming the input. Model writes, CLI creation and managed provisioning enforce the same policy. Existing usernames are left intact.

## Validation

- **Full regression: 471 tests and 34 subtests passed** in 8 minutes 57 seconds. See [regression.log](regression.log). The final focused run also passed after the deterministic preview ordering adjustment.
- **15 focused tests passed**, including retained/current proof selection, explicit overlap decisions, frozen pricing, Recruiting repricing, linked identity conflicts, reference transfers with SQLite foreign-key checks enabled, session invalidation, permission/CSRF guards, stale previews, transaction rollback after evidence moves, whitespace forms/model/CLI/provisioning and migration upgrade/downgrade.
- **15 real Chrome geometry checks passed:** Manage Users, merge selection and merge preview at 320, 390, 820, 1024 and 1440 pixels. No page overflow, overlapping controls, clipped buttons or offscreen content was detected. See [metrics.json](metrics.json).
- The browser submitted a merge with explicit payment/membership/charge choices and a conflicting Telegram link, then verified the resulting account, assigned amounts, retained proof history and username validation.
- The existing payment browser workflow passed again: image and transaction submission, update, denial, resubmission, approval, read-only verified history and responsive modal footers.
- Phone and desktop merge screenshots were visually inspected. All accounts and payment details are synthetic.

Reproduce with `python -m pytest tests/test_account_merge.py -q`, `python tests/browser/account_merge.py` and `python tests/browser/payment_workflow.py`. The full regression command is `python -m pytest tests -q --disable-warnings --tb=short`.

## Screenshots

| View | Phone | Tablet | Desktop |
| --- | --- | --- | --- |
| Manage Users | [390 px](manage-users-390.png) | [820 px](manage-users-820.png) | [1440 px](manage-users-1440.png) |
| Account selection | [390 px](merge-select-390.png) | [820 px](merge-select-820.png) | [1440 px](merge-select-1440.png) |
| Merge preview | [390 px](merge-preview-390.png) | [820 px](merge-preview-820.png) | [1440 px](merge-preview-1440.png) |
| Retained payment history | [390 px](merged-payment-history-390.png) | [820 px](merged-payment-history-820.png) | [1440 px](merged-payment-history-1440.png) |
| Username error | [390 px](username-validation-390.png) | [820 px](username-validation-820.png) | [1440 px](username-validation-1440.png) |

## Deployment

Apply `flask --app run.py db upgrade` before serving this version. The migration adds merge audit/history metadata and SQLite ID protection without rewriting existing usernames. Only disposable databases were migrated during validation.
