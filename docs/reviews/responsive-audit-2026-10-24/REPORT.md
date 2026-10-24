# Responsive interface audit ? October 24, 2026

**Audit and proposal only. No further application code changes were made.** The existing pending Manage Participants template/CSS changes were preserved exactly. This folder contains review artifacts, not implementation changes.

## Scope and method

- Audited the current local checkout in headless Chrome using an isolated temporary database and synthetic records. No live participant data, bucket objects, actual credentials, notification sends, approvals or production settings were used or changed.
- Reviewed 45 main route/template views plus payment, navigation, filter, image-viewer and managed-support states: **59 page/state views ? 6 viewport widths = 354 captures/checks**.
- Widths: **320, 390, 820, 1024, 1280 and 1440 CSS pixels**, covering small phones, phones, portrait tablets, landscape tablets/smaller laptops and desktops.
- Saved **404 raw screenshots**, including focused captures of tables below the fold. The extra screenshots are evidence views, not additional tested states.
- Measured page overflow, local table scrolling, compressed controls, overlapping controls and modal geometry, then visually reviewed the screenshot overviews and the important findings at full resolution. A table that scrolls locally is distinguished from page-wide overflow; both can still hide an essential action.
- The new report with no previous payment was tested with multiple configured payment methods and, separately, with a single method. Pending, denied, verified and administrator review states were also checked.
- [Screenshot gallery](index.html), [raw measurements](metrics.json), [browser exception evidence](browser-exceptions.json), and [source-diff verification](source-verification.json).

## Findings and screenshot evidence

| ID | Priority | Page / state | Proof |
|---|---|---|---|
| F1 | First fix | New payment report with multiple methods | [Screenshot](participant-payment-new-390.png) |
| F2 | First fix | Payment proof settings preview | [Screenshot](edit-payment-option-390.png) |
| F3 | High | Payment Options and Edit Payment Option | [Screenshot](payment-options-820-table2.png) |
| F4 | High | Manage Users, including managed support variant | [Screenshot](manage-users-820-table1.png) |
| F5 | High | Tags and merge view | [Screenshot](tags-320-table2.png) |
| F6 | High | Admin Action Queue: both sections | [Screenshot](action-queue-320-table1.png) |
| F7 | Next | Saved Bot Command Registry, including edit view | [Screenshot](custom-commands-820-table1.png) |
| F8 | Next | Participant list on test-detail pages | [Screenshot](group-test-member-1024-table2.png) |
| F9 | Next | Result Analysis Review | [Screenshot](analysis-review-320-table1.png) |
| F10 | Polish | Page headers and shared action spacing | [Screenshot](admin-dashboard-320.png) |

### F1. New payment report with multiple methods

**Observed:** The modal displays an exception and no form when the participant has no previous report or preferred method and several methods are available. Reproduced at all six widths.

**Recommended change:** Require an existing latest report before restoring its transaction ID/image. Keep the blank method-selection state valid, and keep Submit disabled until initialization succeeds. Add a browser check with multiple methods and no saved selection.

Source: `app/static/js/payments.js:96`. [Open the screenshot](participant-payment-new-390.png).

### F2. Payment proof settings preview

**Observed:** Add/Edit Payment Option pages throw a JavaScript exception because the script expects a preview element absent from the template. Twelve exceptions were captured across the two pages and six widths. Server-side form submission was not tested in this audit; the confirmed failure is the live preview initialization.

**Recommended change:** Add the intended preview element and guard optional elements so one missing helper cannot abort the whole script. Verify live requirement summaries and zero console exceptions on both pages.

Source: `app/static/js/payments.js:9; app/templates/admin/_payment_proof_settings.html`. [Open the screenshot](edit-payment-option-390.png).

The missing preview is confirmed by `browser-exceptions.json` and source inspection; the screenshot shows the affected form, while the exception log is the direct evidence of this JavaScript fault.

### F3. Payment Options and Edit Payment Option

**Observed:** The configured-options table hides actions beyond the viewport. At 820px the page expands to 922px; at 1440px it still expands to 1482px. The static Payment Matrix also overflows; on the edit page it expands a 320px page to 385px.

**Recommended change:** Render configured options as cards with a clear Edit action and a More menu, wrap destinations and links, and make QR previews fit their container. Stack or reformat the Payment Matrix at narrow widths. Keep the create/edit forms usable independently of the list.

Source: `app/templates/admin/payment_options.html:35; app/templates/admin/payment_options.html:64; app/templates/admin/edit_payment_option.html`. [Open the screenshot](payment-options-820-table2.png).

### F4. Manage Users, including managed support variant

**Observed:** User columns and actions extend off-screen on tablets and phones. At 820px the populated page is 1061px wide. The current table cannot keep identity, status, notifications, and actions simultaneously visible.

**Recommended change:** Use labelled user cards below the width where the table genuinely fits. Keep Edit visible and group secondary controls in More. Stack the support-reason input and its action on narrow screens.

Source: `app/templates/admin/manage_users.html:43`. [Open the screenshot](manage-users-820-table1.png).

### F5. Tags and merge view

**Observed:** At 320px the page expands to 638px. Rename inputs shrink to about 18px, making the current value unreadable; merge and secondary actions are off-screen.

**Recommended change:** Use cards on small screens with a full-width rename field and stable Save control. Group merge/retire/bot visibility actions. Reflow duplicate suggestions and merge confirmation controls using the same pattern.

Source: `app/templates/admin/tags.html:82`. [Open the screenshot](tags-320-table2.png).

### F6. Admin Action Queue: both sections

**Observed:** The Result Analysis section keeps a wide table on phones: Review Findings, Inspect Failure and Acknowledge are off-screen until horizontal scrolling. The participation/payment section switches only below 576px, leaving tablet rows with narrow, unevenly stacked action buttons.

**Recommended change:** Use consistent queue cards when either section no longer fits, with one primary review/approval action and a tidy secondary group. Preserve join-request checkboxes, Select All, selection counts, filters and pagination. Make bulk actions wrap into a deliberate toolbar.

Source: `app/templates/admin/action_queue.html:21; app/templates/admin/action_queue.html:137; app/templates/admin/action_queue.html:150`. [Open the screenshot](action-queue-320-table1.png).

Additional evidence: [tablet participation/payment actions](action-queue-820-table2.png).

### F7. Saved Bot Command Registry, including edit view

**Observed:** The saved-command table clips its rightmost actions at tablet width and requires substantial horizontal scrolling on phones. At 820px its local scroll area overflows by 43px; at 320px by 443px.

**Recommended change:** Use command cards with command name, description and state visible, Edit as the primary action, and secondary actions grouped. Put long reply previews and advanced scope/rate-limit details in expandable areas within the same page.

Source: `app/templates/admin/telegram_command_templates.html:120`. [Open the screenshot](custom-commands-820-table1.png).

### F8. Participant list on test-detail pages

**Observed:** This is a separate participant table from Manage Participants. In the narrow desktop/tablet sidebar it hides later columns: 172px of horizontal scrolling at 1024px, and 252px at 320px. The payment methods panel also gets cramped beside its QR images in the sidebar.

**Recommended change:** Make the participant list adapt to its actual container width, or move it to a full-width section. Use labelled rows/cards when necessary. Stack QR previews beneath details when the payment panel itself is narrow, even if the viewport is wide.

Source: `app/templates/group_test_detail.html:269; app/templates/group_test_detail.html:412`. [Open the screenshot](group-test-member-1024-table2.png).

### F9. Result Analysis Review

**Observed:** At 320px the findings table needs 85px of horizontal scrolling. Proposed-result inputs are narrow enough to obscure values such as Confirmed, and evidence/state cannot be reviewed comfortably together.

**Recommended change:** Present each finding as a card with its acceptance control, test, full-width editable result, evidence and state. Keep the existing submission form and review behavior.

Source: `app/templates/admin/result_analysis_review.html:27`. [Open the screenshot](analysis-review-320-table1.png).

### F10. Page headers and shared action spacing

**Observed:** No page-wide overflow is required to produce a poor layout: the dashboard Create New Group Test button wraps to three lines at 320px. Back/action buttons on My Results, Tags and some edit/configuration pages also squeeze beside long headings or explanatory text.

**Recommended change:** Give header actions their own row on narrow screens. Standardize button gaps and minimum tap sizes, and avoid incidental inline margins. Apply the shared pattern to dashboard/test headers and the affected form footers without redesigning otherwise usable forms.

Source: `app/templates/dashboard.html:16; app/templates/my_results.html:88; app/templates/group_test_detail.html:50`. [Open the screenshot](admin-dashboard-320.png).

## Proposed implementation sequence

1. **Repair the two payment UI regressions first (F1?F2).** Both are in the payment work added during this session. Validate an unselected method, multiple methods, a saved report, and both Add/Edit proof-settings forms. Confirm no JavaScript exceptions and keep failed initialization from exposing an active Submit button.
2. **Fix pages that hide essential controls (F3?F6).** Apply consistent action groups and responsive cards to Payment Options, Manage Users, Tags and both Action Queue sections. Choose breakpoints from the content width instead of assuming everything above phone size fits a table.
3. **Fix remaining review/list friction (F7?F9).** Reflow the command registry, test-detail participant list and analysis findings. Preserve existing URLs, permissions, forms, selection behavior and review decisions.
4. **Apply restrained shared polish (F10).** Use a reusable responsive header/action layout, wrap long destinations and names, and give important phone controls usable tap areas. Keep the existing Bootstrap design language.
5. **Recheck the same evidence cases.** Capture before/after screenshots at all six widths; check dropdowns, bulk-selection controls, payment modal initialization and scrolling, focus/keyboard operation, and long labels/IDs. Run the affected existing workflow tests and add focused browser coverage for the two missed payment states.

Approval of this plan would authorize implementation; this audit does not apply these changes.

## Pages without a major obstruction in the tested states

The revised Manage Participants view, ordinary create/edit user and participant forms, settings hub, built-in command settings, bot integrations, notification and storage configuration forms, profile, participation request, authentication pages, public result detail, legal pages and version page did not show page-wide overflow or overlapping controls in these fixtures. My Results content also remained within the viewport. Some header/button wrapping remains covered by F10.

Existing payment reports (pending/denied), verified payment viewing, administrator proof review, the single-method new-report flow, validation errors, expanded filters, navigation menus and the result-image modal stayed within the tested viewport. This does **not** override F1: the fresh **multiple-method** payment-report state fails functionally before the form appears.

## Coverage matrix

?Fits? below means no page-wide horizontal overflow in that view; it is not a claim that every local table, action group, or conditional state is optimal. ?Table scroll? identifies a local/table constraint for review. Known compressed header actions and JavaScript faults are listed in the findings above.

| Page / state | Route | Page-wide overflow at | Table scroll/overflow at | Phone | Tablet | Desktop |
|---|---|---|---|---|---|---|
| admin-dashboard | `/dashboard` | Fits | None | [390](admin-dashboard-390.png) | [820](admin-dashboard-820.png) | [1440](admin-dashboard-1440.png) |
| action-queue | `/admin/action-queue` | Fits | 390, 320 | [390](action-queue-390.png) | [820](action-queue-820.png) | [1440](action-queue-1440.png) |
| manage-participants | `/admin/manage-participants/1` | Fits | None | [390](manage-participants-390.png) | [820](manage-participants-820.png) | [1440](manage-participants-1440.png) |
| payment-options | `/admin/payment-options` | 1440, 1280, 1024, 820, 390, 320 | 1440, 1280, 1024, 820, 390, 320 | [390](payment-options-390.png) | [820](payment-options-820.png) | [1440](payment-options-1440.png) |
| edit-payment-option | `/admin/payment-options/1/edit` | 320 | 390, 320 | [390](edit-payment-option-390.png) | [820](edit-payment-option-820.png) | [1440](edit-payment-option-1440.png) |
| manage-users | `/admin/users` | 1024, 820, 390, 320 | 1024, 820, 390, 320 | [390](manage-users-390.png) | [820](manage-users-820.png) | [1440](manage-users-1440.png) |
| create-user | `/admin/users/new` | Fits | None | [390](create-user-390.png) | [820](create-user-820.png) | [1440](create-user-1440.png) |
| edit-user | `/admin/users/1/edit` | Fits | None | [390](edit-user-390.png) | [820](edit-user-820.png) | [1440](edit-user-1440.png) |
| admin-settings | `/admin/settings` | Fits | None | [390](admin-settings-390.png) | [820](admin-settings-820.png) | [1440](admin-settings-1440.png) |
| tags | `/admin/tags` | 390, 320 | 390, 320 | [390](tags-390.png) | [820](tags-820.png) | [1440](tags-1440.png) |
| tags-merge | `/admin/tags?merge_source=2&merge_target=1` | 390, 320 | 390, 320 | [390](tags-merge-390.png) | [820](tags-merge-820.png) | [1440](tags-merge-1440.png) |
| notification-templates | `/admin/notification-templates` | Fits | None | [390](notification-templates-390.png) | [820](notification-templates-820.png) | [1440](notification-templates-1440.png) |
| edit-notification-template | `/admin/notification-templates/1/edit` | Fits | None | [390](edit-notification-template-390.png) | [820](edit-notification-template-820.png) | [1440](edit-notification-template-1440.png) |
| custom-commands | `/admin/telegram-command-templates` | Fits | 820, 390, 320 | [390](custom-commands-390.png) | [820](custom-commands-820.png) | [1440](custom-commands-1440.png) |
| edit-custom-command | `/admin/telegram-command-templates/1/edit` | Fits | 820, 390, 320 | [390](edit-custom-command-390.png) | [820](edit-custom-command-820.png) | [1440](edit-custom-command-1440.png) |
| builtin-commands | `/admin/settings/commands/builtins` | Fits | None | [390](builtin-commands-390.png) | [820](builtin-commands-820.png) | [1440](builtin-commands-1440.png) |
| bot-integrations | `/admin/settings/bots` | Fits | None | [390](bot-integrations-390.png) | [820](bot-integrations-820.png) | [1440](bot-integrations-1440.png) |
| notification-config | `/admin/notification-config` | Fits | None | [390](notification-config-390.png) | [820](notification-config-820.png) | [1440](notification-config-1440.png) |
| telegram-config | `/admin/telegram-config` | Fits | None | [390](telegram-config-390.png) | [820](telegram-config-820.png) | [1440](telegram-config-1440.png) |
| storage-config | `/admin/storage-config` | Fits | None | [390](storage-config-390.png) | [820](storage-config-820.png) | [1440](storage-config-1440.png) |
| analysis-config | `/admin/settings/result-analysis` | Fits | None | [390](analysis-config-390.png) | [820](analysis-config-820.png) | [1440](analysis-config-1440.png) |
| analysis-review | `/admin/result-analysis/1` | Fits | 390, 320 | [390](analysis-review-390.png) | [820](analysis-review-820.png) | [1440](analysis-review-1440.png) |
| public-results-admin | `/admin/public-results` | Fits | None | [390](public-results-admin-390.png) | [820](public-results-admin-820.png) | [1440](public-results-admin-1440.png) |
| edit-public-result | `/admin/public-results/1/edit` | Fits | None | [390](edit-public-result-390.png) | [820](edit-public-result-820.png) | [1440](edit-public-result-1440.png) |
| create-test | `/admin/create-test` | Fits | None | [390](create-test-390.png) | [820](create-test-820.png) | [1440](create-test-1440.png) |
| edit-test | `/admin/edit-test/1` | Fits | None | [390](edit-test-390.png) | [820](edit-test-820.png) | [1440](edit-test-1440.png) |
| add-participant | `/admin/add-participant/1` | Fits | None | [390](add-participant-390.png) | [820](add-participant-820.png) | [1440](add-participant-1440.png) |
| edit-participant | `/admin/update-participant/1` | Fits | None | [390](edit-participant-390.png) | [820](edit-participant-820.png) | [1440](edit-participant-1440.png) |
| root-credentials | `/audit-root-credentials` | Fits | None | [390](root-credentials-390.png) | [820](root-credentials-820.png) | [1440](root-credentials-1440.png) |
| group-test-admin | `/test/1` | Fits | 1440, 1280, 1024, 390, 320 | [390](group-test-admin-390.png) | [820](group-test-admin-820.png) | [1440](group-test-admin-1440.png) |
| member-dashboard | `/dashboard` | Fits | None | [390](member-dashboard-390.png) | [820](member-dashboard-820.png) | [1440](member-dashboard-1440.png) |
| my-results | `/my-results` | Fits | None | [390](my-results-390.png) | [820](my-results-820.png) | [1440](my-results-1440.png) |
| profile | `/profile` | Fits | None | [390](profile-390.png) | [820](profile-820.png) | [1440](profile-1440.png) |
| group-test-member | `/test/1` | Fits | 1440, 1280, 1024, 390, 320 | [390](group-test-member-390.png) | [820](group-test-member-820.png) | [1440](group-test-member-1440.png) |
| group-test-closed | `/test/4` | Fits | 1024, 390, 320 | [390](group-test-closed-390.png) | [820](group-test-closed-820.png) | [1440](group-test-closed-1440.png) |
| update-status | `/test/1/my-status` | Fits | None | [390](update-status-390.png) | [820](update-status-820.png) | [1440](update-status-1440.png) |
| request-participation | `/test/2/request` | Fits | None | [390](request-participation-390.png) | [820](request-participation-820.png) | [1440](request-participation-1440.png) |
| public-result-detail | `/public-results/1` | Fits | None | [390](public-result-detail-390.png) | [820](public-result-detail-820.png) | [1440](public-result-detail-1440.png) |
| version | `/version` | Fits | None | [390](version-390.png) | [820](version-820.png) | [1440](version-1440.png) |
| home | `/` | Fits | None | [390](home-390.png) | [820](home-820.png) | [1440](home-1440.png) |
| login | `/login` | Fits | None | [390](login-390.png) | [820](login-820.png) | [1440](login-1440.png) |
| register | `/register` | Fits | None | [390](register-390.png) | [820](register-820.png) | [1440](register-1440.png) |
| password-reset | `/password-reset` | Fits | None | [390](password-reset-390.png) | [820](password-reset-820.png) | [1440](password-reset-1440.png) |
| terms | `/terms` | Fits | None | [390](terms-390.png) | [820](terms-820.png) | [1440](terms-1440.png) |
| privacy | `/privacy` | Fits | None | [390](privacy-390.png) | [820](privacy-820.png) | [1440](privacy-1440.png) |
| payment-review | `/admin/manage-participants/1` | Fits | None | [390](payment-review-390.png) | [820](payment-review-820.png) | [1440](payment-review-1440.png) |
| payment-verified | `/admin/manage-participants/1` | Fits | None | [390](payment-verified-390.png) | [820](payment-verified-820.png) | [1440](payment-verified-1440.png) |
| payment-denied | `/admin/manage-participants/1` | Fits | None | [390](payment-denied-390.png) | [820](payment-denied-820.png) | [1440](payment-denied-1440.png) |
| manage-users-managed | `/admin/users` | 1024, 820, 390, 320 | 1024, 820, 390, 320 | [390](manage-users-managed-390.png) | [820](manage-users-managed-820.png) | [1440](manage-users-managed-1440.png) |
| participant-payment-new | `/test/1` | Fits | 1440, 1280, 1024, 390, 320 | [390](participant-payment-new-390.png) | [820](participant-payment-new-820.png) | [1440](participant-payment-new-1440.png) |
| participant-payment-pending | `/test/1` | Fits | 1440, 1280, 1024, 390, 320 | [390](participant-payment-pending-390.png) | [820](participant-payment-pending-820.png) | [1440](participant-payment-pending-1440.png) |
| participant-payment-verified | `/test/1` | Fits | 1440, 1280, 1024, 390, 320 | [390](participant-payment-verified-390.png) | [820](participant-payment-verified-820.png) | [1440](participant-payment-verified-1440.png) |
| participant-payment-denied | `/test/1` | Fits | 1440, 1280, 1024, 390, 320 | [390](participant-payment-denied-390.png) | [820](participant-payment-denied-820.png) | [1440](participant-payment-denied-1440.png) |
| participant-payment-single-method | `/test/1` | Fits | 1440, 1280, 1024, 390, 320 | [390](participant-payment-single-method-390.png) | [820](participant-payment-single-method-820.png) | [1440](participant-payment-single-method-1440.png) |
| participant-payment-validation | `/test/1` | Fits | 1440, 1280, 1024, 390, 320 | [390](participant-payment-validation-390.png) | [820](participant-payment-validation-820.png) | [1440](participant-payment-validation-1440.png) |
| admin-navigation | `/dashboard` | Fits | None | [390](admin-navigation-390.png) | [820](admin-navigation-820.png) | [1440](admin-navigation-1440.png) |
| dashboard-filters-expanded | `/dashboard` | Fits | None | [390](dashboard-filters-expanded-390.png) | [820](dashboard-filters-expanded-820.png) | [1440](dashboard-filters-expanded-1440.png) |
| results-filters-expanded | `/my-results` | Fits | None | [390](results-filters-expanded-390.png) | [820](results-filters-expanded-820.png) | [1440](results-filters-expanded-1440.png) |
| result-image-modal | `/my-results` | Fits | None | [390](result-image-modal-390.png) | [820](result-image-modal-820.png) | [1440](result-image-modal-1440.png) |

## Limits

This is a local Chrome layout and state audit, not a production deployment inspection or a full cross-browser/accessibility certification. Native iOS/Android file pickers, on-screen keyboards, Safari, unusual zoom/font settings, PDF viewer internals, every possible empty/error/pagination state and real cloud/notification delivery were not exhaustively tested. The Root credentials screenshot is a direct render with explicit fake values; no real bridge credential was generated. The managed-support view was rendered against synthetic data with managed mode enabled for that view only.
