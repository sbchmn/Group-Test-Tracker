# Project Map

## Target Files and Modules
- app/models.py
- app/routes.py
- app/notifications.py
- app/templates/dashboard.html
- app/templates/group_test_detail.html
- app/templates/admin/edit_test.html
- app/templates/admin/create_test.html
- app/templates/base.html
- likely new templates for my results and public result admin pages
- migrations/versions/<new_revision>.py
- tests/test_notifications.py
- tests/test_schema_migration.py
- likely new tests for tags, results, dashboard visibility, and public results

## Intended Behavior Changes
- Add reusable tags for group tests and public results.
- Add per-user hidden dashboard state for group tests.
- Add a My Results page that combines member group-test results and admin-created public results.
- Add admin UI to create public results entries.
- Add admin ability to delete group tests from the edit page.
- Add dashboard sorting/grouping controls defaulting to grouping by status.
- Fix notification emails so each recipient receives the correct rendered variables.
- Add an admin action queue to approve pending participants across multiple tests from one page.
- Split dashboard actions so users can request join directly from dashboard cards.
- Add dashboard grouping by personal participation state: Pending, Approved, Not Joined.

## Implemented Changes
- Added shared Tag, PublicResult, and dashboard-hide models plus a `results_posted_at` field on group tests.
- Wired group-test and public-result tag entry through comma-separated inputs with datalist suggestions.
- Added dashboard grouping/sorting controls, hide/unhide toggles, and tag badges.
- Added `/my-results` and admin public-results management pages.
- Added edit support for admin-created public results with prefilled form values and tag updates.
- Added admin group-test delete support from the edit page.
- Fixed participant notification rendering to use each participant's own amount owed.
- Expanded dashboard grouping to include compound and made filter panels collapsible on dashboard and My Results pages.
- Filter panels on dashboard and My Results now default collapsed to avoid reopening automatically for users.
- Added optional free-text results to each lab test item in `lab_test_details` and display them on group test detail and My Results views.
- Added itemized public result rows with a new JSON column and admin create/edit UI, rendered on My Results alongside public result entries.
- Added an admin action queue page for pending participation requests with single-approve and bulk-approve actions.
- Added queue filters (status + keyword) so admins can quickly find pending requests by test/participant.
- Added queue pagination (25 per page) for large pending-request backlogs.
- Added deny actions (single + selected) to remove pending requests directly from queue.
- Added an "Approve All Filtered" action with explicit confirmation text requirement.
- Refactored action queue HTML form structure to avoid nested forms so row-level Approve/Deny buttons submit only their own row action.
- Split dashboard card action into separate "View Details" and request-status controls.
- Added dashboard quick-request POST route and card states: "Request Join", "Join Request Pending", and "Joined".
- Added dashboard filter support for grouping/sorting by personal join state.

## Risks and Assumptions
- Tags should be normalized to a shared tag table so they work across group tests and public results.
- Hidden dashboard state should be per-user and should not alter test visibility rules.
- Existing Alembic revisions must remain untouched; all schema additions go in one new revision.
- Public results should be additive and not disturb existing closed-test `results_link` behavior.
- Dashboard grouping is best handled client-side using data attributes to avoid changing core query logic.
- Bulk approval must recalculate `amount_owed` for all approved participants in affected tests to avoid stale balances.
- Deny actions remove pending participation records; this intentionally allows users to submit a fresh request later.

## Validation Plan
- Run targeted unit tests for notification rendering and new schema behavior.
- Add or update tests for tag persistence, my-results aggregation, and dashboard hide toggles.
- Run a narrow test command before broader verification.
- Check migrations or schema-related tests to confirm the new revision is additive only.
- Add/extend admin route tests to verify action queue approvals and recalculated costs.
- Extend queue tests for deny/remove workflow, pagination behavior, and approve-all-filtered confirmation safety.
- Add focused tests for dashboard quick-request flow and join-state grouping labels.

## Validation Results
- Focused test slice passed: `tests.test_notifications`, `tests.test_lab_costs`, and `tests.test_schema_migration`.
- New focused queue validation passed: `python -m unittest tests.test_participant_removal`.
- Re-ran queue suite after form-structure fix; all queue tests still passed.
- Dashboard + queue participant suite passed: `python -m unittest tests.test_participant_removal` (7 tests, OK).

## Documentation Updates
- README updated to cover tags, public results, dashboard controls, and the current unittest-based validation command.