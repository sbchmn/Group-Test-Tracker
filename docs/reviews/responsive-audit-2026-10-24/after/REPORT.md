# Responsive fixes: implementation and verification

All ten findings in the approved audit plan have been addressed. The original audit remains in the parent folder; this folder contains updated evidence. No schema changes or deployment actions were needed for these fixes.

## Verification

- Rechecked the original **354** combinations and added **12** result-viewer combinations: **366 checks across 61 page/state views**, at 320, 390, 820, 1024, 1280 and 1440 CSS pixels.
- Page-wide overflow: **19 cases before, 0 after**. Local table overflow: **73 cases before, 0 after** in the final captures.
- No detected overlapping visible controls or browser JavaScript exceptions. Overlap checks consider the active modal and ancestor clipping, rather than counting obscured background controls or scrolled-out content.
- The complete regression suite passed **434 tests and 34 subtests**. The focused run passed 64 tests; 9 final view checks passed after moving the participant list.
- The persistent browser workflow passed multi-method initialization, failed-load handling, image/transaction submission, update, denial, resubmission, approval, verified viewing, live proof-policy changes, queue selection IDs and keyboard navigation.
- Tall images now scroll inside all three existing result-image modals while their download controls remain reachable.

[Before/after screenshot comparison](index.html) | [Original audit](../REPORT.md) | [Machine-readable verification](verification.json) | [Final measurements](metrics.json) | [Regression output](tests-regression.txt)

## Changes and proof

| Finding | Change | Before | After |
|---|---|---|---|
| F1: New payment report | A new report opens normally with several methods and no saved selection. Submit stays disabled until a method is selected. Failed loading hides decision controls. | [Screenshot](../participant-payment-new-390.png) | [Screenshot](participant-payment-new-390.png) |
| F2: Proof-setting preview | Both configuration forms render live optional/either/all summaries. Missing optional helper markup cannot abort other script initialization. | [Screenshot](../edit-payment-option-390.png) | [Screenshot](edit-payment-option-390.png) |
| F3: Payment Options | Configured destinations and the Payment Matrix adapt to available space. Edit remains visible; secondary actions are in More. | [Screenshot](../payment-options-820-table2.png) | [Screenshot](payment-options-820-table2.png) |
| F4: Manage Users | Identity and status fields remain visible in cards when the table will not fit. Reset and activation actions are grouped under More. The managed support form stacks on phones. | [Screenshot](../manage-users-820-table1.png) | [Screenshot](manage-users-820-table1.png) |
| F5: Tags | Rename fields use the card width instead of shrinking to a few pixels. Merge stays visible; other actions are grouped. Duplicate and retired-tag tables also reflow. | [Screenshot](../tags-320-table2.png) | [Screenshot](tags-320-table2.png) |
| F6: Action Queue | Both queue sections adapt to their container. Primary review/approval actions remain visible. Join-request selection, counts, bulk forms, filters and pagination are preserved. | [Screenshot](../action-queue-820-table2.png) | [Screenshot](action-queue-820-table2.png) |
| F7: Bot Command Registry | Saved commands use readable cards when needed, with Edit and More controls. Long reply previews expand within the current page. | [Screenshot](../custom-commands-820-table1.png) | [Screenshot](custom-commands-820-table1.png) |
| F8: Test-detail participant list | The participant list occupies a full-width section, with readable cards on smaller screens and a table when it fits. Narrow payment panels stack QR previews beneath the destination. | [Screenshot](../group-test-member-1024-table2.png) | [Screenshot](group-test-member-1024-table2.png) |
| F9: Result Analysis Review | Each finding has a labelled acceptance control, a full-width result input, readable evidence and its state on narrow screens. | [Screenshot](../analysis-review-390-table1.png) | [Screenshot](analysis-review-390-table1.png) |
| F10: Headers and action spacing | Header actions move to their own row on small screens. Shared gaps and tap targets replace incidental wrapping. Quick result-link forms also stack on phones. | [Screenshot](../admin-dashboard-320.png) | [Screenshot](admin-dashboard-320.png) |

## Design and behavior

Shared styles in `app/static/css/layout.css` use the available container width, so the same lists work in a full-width page or a narrow panel. Headers and secondary actions use consistent spacing, and long destinations, statuses and names wrap without pushing controls out of view. A shared More-menu macro keeps existing POST actions and CSRF inputs intact.

The participant list on test-detail pages was moved below the details/payment columns. Existing visibility conditions and financial data are unchanged. Queue checkboxes still apply only to join requests; moving them outside the hidden table header makes bulk selection usable at every width.

The payment initialization fixes retain the existing report and review APIs. Optional preview markup is guarded, saved evidence is restored only when there is an actual saved report, and loading failure does not leave an active decision button.

## Repeatable focused browser check

Run `python tests/browser/payment_workflow.py` from the repository root. See `tests/browser/README.md` for Chrome, optional dependencies and screenshot output settings. It starts a temporary localhost application and synthetic SQLite database, with storage and notifications mocked.

## Practical limits

The screenshots and layout measurements use local Chrome emulation and synthetic records. They do not certify every Safari/iOS/Android behavior, native file picker, on-screen keyboard, zoom setting or possible dataset. Real cloud upload and notification delivery were not exercised. Existing backend authorization and payment workflow tests remain part of the passing regression suite.

## Capture index

| Page/state | Phone | Tablet | Desktop |
|---|---|---|---|
| admin-dashboard | [390](admin-dashboard-390.png) | [820](admin-dashboard-820.png) | [1440](admin-dashboard-1440.png) |
| action-queue | [390](action-queue-390.png) | [820](action-queue-820.png) | [1440](action-queue-1440.png) |
| manage-participants | [390](manage-participants-390.png) | [820](manage-participants-820.png) | [1440](manage-participants-1440.png) |
| payment-options | [390](payment-options-390.png) | [820](payment-options-820.png) | [1440](payment-options-1440.png) |
| edit-payment-option | [390](edit-payment-option-390.png) | [820](edit-payment-option-820.png) | [1440](edit-payment-option-1440.png) |
| manage-users | [390](manage-users-390.png) | [820](manage-users-820.png) | [1440](manage-users-1440.png) |
| create-user | [390](create-user-390.png) | [820](create-user-820.png) | [1440](create-user-1440.png) |
| edit-user | [390](edit-user-390.png) | [820](edit-user-820.png) | [1440](edit-user-1440.png) |
| admin-settings | [390](admin-settings-390.png) | [820](admin-settings-820.png) | [1440](admin-settings-1440.png) |
| tags | [390](tags-390.png) | [820](tags-820.png) | [1440](tags-1440.png) |
| tags-merge | [390](tags-merge-390.png) | [820](tags-merge-820.png) | [1440](tags-merge-1440.png) |
| notification-templates | [390](notification-templates-390.png) | [820](notification-templates-820.png) | [1440](notification-templates-1440.png) |
| edit-notification-template | [390](edit-notification-template-390.png) | [820](edit-notification-template-820.png) | [1440](edit-notification-template-1440.png) |
| custom-commands | [390](custom-commands-390.png) | [820](custom-commands-820.png) | [1440](custom-commands-1440.png) |
| edit-custom-command | [390](edit-custom-command-390.png) | [820](edit-custom-command-820.png) | [1440](edit-custom-command-1440.png) |
| builtin-commands | [390](builtin-commands-390.png) | [820](builtin-commands-820.png) | [1440](builtin-commands-1440.png) |
| bot-integrations | [390](bot-integrations-390.png) | [820](bot-integrations-820.png) | [1440](bot-integrations-1440.png) |
| notification-config | [390](notification-config-390.png) | [820](notification-config-820.png) | [1440](notification-config-1440.png) |
| telegram-config | [390](telegram-config-390.png) | [820](telegram-config-820.png) | [1440](telegram-config-1440.png) |
| storage-config | [390](storage-config-390.png) | [820](storage-config-820.png) | [1440](storage-config-1440.png) |
| analysis-config | [390](analysis-config-390.png) | [820](analysis-config-820.png) | [1440](analysis-config-1440.png) |
| analysis-review | [390](analysis-review-390.png) | [820](analysis-review-820.png) | [1440](analysis-review-1440.png) |
| public-results-admin | [390](public-results-admin-390.png) | [820](public-results-admin-820.png) | [1440](public-results-admin-1440.png) |
| edit-public-result | [390](edit-public-result-390.png) | [820](edit-public-result-820.png) | [1440](edit-public-result-1440.png) |
| create-test | [390](create-test-390.png) | [820](create-test-820.png) | [1440](create-test-1440.png) |
| edit-test | [390](edit-test-390.png) | [820](edit-test-820.png) | [1440](edit-test-1440.png) |
| add-participant | [390](add-participant-390.png) | [820](add-participant-820.png) | [1440](add-participant-1440.png) |
| edit-participant | [390](edit-participant-390.png) | [820](edit-participant-820.png) | [1440](edit-participant-1440.png) |
| root-credentials | [390](root-credentials-390.png) | [820](root-credentials-820.png) | [1440](root-credentials-1440.png) |
| group-test-admin | [390](group-test-admin-390.png) | [820](group-test-admin-820.png) | [1440](group-test-admin-1440.png) |
| member-dashboard | [390](member-dashboard-390.png) | [820](member-dashboard-820.png) | [1440](member-dashboard-1440.png) |
| my-results | [390](my-results-390.png) | [820](my-results-820.png) | [1440](my-results-1440.png) |
| profile | [390](profile-390.png) | [820](profile-820.png) | [1440](profile-1440.png) |
| group-test-member | [390](group-test-member-390.png) | [820](group-test-member-820.png) | [1440](group-test-member-1440.png) |
| group-test-closed | [390](group-test-closed-390.png) | [820](group-test-closed-820.png) | [1440](group-test-closed-1440.png) |
| update-status | [390](update-status-390.png) | [820](update-status-820.png) | [1440](update-status-1440.png) |
| request-participation | [390](request-participation-390.png) | [820](request-participation-820.png) | [1440](request-participation-1440.png) |
| public-result-detail | [390](public-result-detail-390.png) | [820](public-result-detail-820.png) | [1440](public-result-detail-1440.png) |
| version | [390](version-390.png) | [820](version-820.png) | [1440](version-1440.png) |
| home | [390](home-390.png) | [820](home-820.png) | [1440](home-1440.png) |
| login | [390](login-390.png) | [820](login-820.png) | [1440](login-1440.png) |
| register | [390](register-390.png) | [820](register-820.png) | [1440](register-1440.png) |
| password-reset | [390](password-reset-390.png) | [820](password-reset-820.png) | [1440](password-reset-1440.png) |
| terms | [390](terms-390.png) | [820](terms-820.png) | [1440](terms-1440.png) |
| privacy | [390](privacy-390.png) | [820](privacy-820.png) | [1440](privacy-1440.png) |
| payment-review | [390](payment-review-390.png) | [820](payment-review-820.png) | [1440](payment-review-1440.png) |
| payment-verified | [390](payment-verified-390.png) | [820](payment-verified-820.png) | [1440](payment-verified-1440.png) |
| payment-denied | [390](payment-denied-390.png) | [820](payment-denied-820.png) | [1440](payment-denied-1440.png) |
| manage-users-managed | [390](manage-users-managed-390.png) | [820](manage-users-managed-820.png) | [1440](manage-users-managed-1440.png) |
| participant-payment-new | [390](participant-payment-new-390.png) | [820](participant-payment-new-820.png) | [1440](participant-payment-new-1440.png) |
| participant-payment-pending | [390](participant-payment-pending-390.png) | [820](participant-payment-pending-820.png) | [1440](participant-payment-pending-1440.png) |
| participant-payment-verified | [390](participant-payment-verified-390.png) | [820](participant-payment-verified-820.png) | [1440](participant-payment-verified-1440.png) |
| participant-payment-denied | [390](participant-payment-denied-390.png) | [820](participant-payment-denied-820.png) | [1440](participant-payment-denied-1440.png) |
| participant-payment-single-method | [390](participant-payment-single-method-390.png) | [820](participant-payment-single-method-820.png) | [1440](participant-payment-single-method-1440.png) |
| participant-payment-validation | [390](participant-payment-validation-390.png) | [820](participant-payment-validation-820.png) | [1440](participant-payment-validation-1440.png) |
| admin-navigation | [390](admin-navigation-390.png) | [820](admin-navigation-820.png) | [1440](admin-navigation-1440.png) |
| dashboard-filters-expanded | [390](dashboard-filters-expanded-390.png) | [820](dashboard-filters-expanded-820.png) | [1440](dashboard-filters-expanded-1440.png) |
| results-filters-expanded | [390](results-filters-expanded-390.png) | [820](results-filters-expanded-820.png) | [1440](results-filters-expanded-1440.png) |
| result-image-modal | [390](result-image-modal-390.png) | [820](result-image-modal-820.png) | [1440](result-image-modal-1440.png) |
| group-result-image-modal | [390](group-result-image-modal-390.png) | [820](group-result-image-modal-820.png) | [1440](group-result-image-modal-1440.png) |
| admin-result-image-modal | [390](admin-result-image-modal-390.png) | [820](admin-result-image-modal-820.png) | [1440](admin-result-image-modal-1440.png) |
