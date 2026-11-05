# Automatic pricing and frozen shares — verification

Implemented October 24, 2026. All screenshots use an isolated local fixture, with mocked notifications and no live payment or participant data.

## Behavior

- Unlocked Recruiting tests recalculate approved funding participants after approvals, removals, donor changes and cost edits. Manage Participants, Action Queue (including bulk approval), Add Existing User and the participant editor use the same policy.
- Leaving Recruiting finalizes charges and records the cost basis before status notifications are queued. Reopening Recruiting retains the freeze until an administrator previews and confirms an unlock.
- Late buy-ins default to the frozen non-donor share, with individual overrides and a separately editable default for future buyers. Late buy-ins stay outside the funding pool, including after an unlock.
- Manual recalculation previews current and proposed charges. Confirmation outside Recruiting applies the changes once and retains the freeze. Concurrent roster, payment or cost changes invalidate the preview.
- Group detail retains a single Amount Owed field per participant: assigned charge minus recorded payment, clamped to zero. Cost summaries and exports retain the frozen basis. Notifications, payment review and bot status retain the assigned-charge meaning of `amount_owed`.
- Existing non-Recruiting tests are frozen without repricing historical charges. An ambiguous historical non-donor rate requires administrator confirmation before approving late buyers. Recorded payments, proofs and verification records are preserved.
- Fixed an existing edit-page issue that inserted $650 of sample lab items into tests without itemized details; saving a status change now preserves the saved total.

## Validation

- Full regression: **456 passed, 34 subtests passed** (`python -m pytest tests -q --disable-warnings --tb=short`).
- Pricing-specific checks after the last template adjustment: **22 passed**, including migration upgrade/downgrade, notifications, exports, assigned balances, concurrent writes, bulk rollback and zero-dollar defaults.
- Real Chrome workflow: approvals through Manage Participants and Action Queue, freeze through Edit Test, individual late override, manual repricing, reopening and explicit unlock all passed.
- **40 responsive geometry checks:** eight views at 320, 390, 820, 1024 and 1440 pixels. No page overflow, clipped buttons, offscreen content or overlapping visible controls were detected. Measurements are in [metrics.json](metrics.json).
- Screenshots were visually inspected for tablet participant cards and phone repricing cards. Additional captures show the participant Amount Owed field at phone, tablet and desktop sizes.
- `git diff --check` passed.

Reproduce browser checks with `python tests/browser/cost_policy.py`. See [browser instructions](../../../tests/browser/README.md).

## Screenshot evidence

| View | Phone | Tablet | Desktop |
| --- | --- | --- | --- |
| Recruiting controls | [390 px](recruiting-390.png) | [820 px](recruiting-820.png) | [1440 px](recruiting-1440.png) |
| Frozen pricing and participants | [390 px](frozen-manage-390.png) | [820 px](frozen-manage-820.png) | [1440 px](frozen-manage-1440.png) |
| Action Queue | [390 px](frozen-queue-390.png) | [820 px](frozen-queue-820.png) | [1440 px](frozen-queue-1440.png) |
| Group detail | [390 px](group-detail-390.png) | [820 px](group-detail-820.png) | [1440 px](group-detail-1440.png) |
| Participant Amount Owed | [390 px](participant-balances-390.png) | [820 px](participant-balances-820.png) | [1440 px](participant-balances-1440.png) |
| Add participant | [390 px](add-participant-390.png) | [820 px](add-participant-820.png) | [1440 px](add-participant-1440.png) |
| Edit late buyer | [390 px](edit-late-buyer-390.png) | [820 px](edit-late-buyer-820.png) | [1440 px](edit-late-buyer-1440.png) |
| Recalculation preview | [390 px](reprice-preview-390.png) | [820 px](reprice-preview-820.png) | [1440 px](reprice-preview-1440.png) |
| Unlock preview | [390 px](unlock-preview-390.png) | [820 px](unlock-preview-820.png) | [1440 px](unlock-preview-1440.png) |

## Deployment

Apply `flask --app run.py db upgrade` before serving this version. This review migrated only disposable test databases; the development/live database has not been upgraded. Existing Recruiting records remain unlocked; other statuses preserve their existing assigned charges.
