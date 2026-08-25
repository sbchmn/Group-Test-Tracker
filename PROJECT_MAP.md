# Project Map

## Target Files and Modules
- app/models.py
- app/routes.py
- app/storage.py
- app/notifications.py
- app/templates/dashboard.html
- app/templates/group_test_detail.html
- app/templates/admin/edit_test.html
- app/templates/admin/create_test.html
- app/templates/admin/storage_config.html
- app/templates/base.html
- likely new templates for my results and public result admin pages
- migrations/versions/<new_revision>.py
- tests/test_notifications.py
- tests/test_schema_migration.py
- tests/test_security.py
- likely new tests for tags, results, dashboard visibility, and public results

## Intended Behavior Changes
- Add production-ready result image uploads backed by S3-compatible object storage (AWS S3 and DigitalOcean Spaces).
- Add admin storage settings page to enable/disable uploads and configure provider credentials/bucket/endpoint behavior.
- Add optional image attachment for both group test results and public results.
- Render a thumbnail next to result links and open full-size image in a modal on click.
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
- Ensure test-detail and dashboard join CTAs reflect existing pending/denied requests.
- Persist denied request state with admin-provided reason and show that reason to end users.
- Add a reapply workflow for denied users.
- Ensure admins can still manually add/approve users after a denial.
- Make denial state/reason visible on Manage Participants and align available admin actions across Action Queue and Manage Participants.

## Implemented Changes
- Added production-oriented object storage module (`app/storage.py`) for S3-compatible uploads with image validation, size limits, and provider-aware URL generation.
- Added storage-backed result image fields (`results_image_key`) to both group tests and public results models, plus additive migration `c3d9e1f4a7b2_add_result_image_keys.py`.
- Added admin storage configuration page and route (`/admin/storage-config`) with provider selection (AWS/DO), bucket credentials, endpoint controls, and upload constraints.
- Added image upload handling to create/edit flows for group tests and public results, including replace/remove behavior and best-effort remote cleanup.
- Added thumbnail rendering and Bootstrap modal full-size viewing in group test detail, My Results, and Public Results admin listing.
- Added navigation entry for Storage Config in admin menu.
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
- Updated test detail participation lookup to include pending/denied requests so CTA/status always reflects existing requests.
- Added participation denial fields (`denied`, `denied_at`, `denied_reason`) with a new additive migration.
- Updated queue deny actions to mark requests denied (instead of deleting) and require denial reasons.
- Displayed denied status and reason on dashboard cards and test detail page.
- Hid dashboard Request Join button once any participation record exists (pending/approved/denied).
- Added `POST /test/<id>/reapply` to reset denied requests back to pending review and notify admins.
- Added Reapply action on group-test detail when a denied request is shown.
- Updated admin add-participant flow to allow denied users to be selected and reactivated/approved instead of blocked by uniqueness.
- Added shared participation transition helpers (approve, deny with reason, reopen) used by both action-queue and manage-participants admin flows.
- Updated Manage Participants table to explicitly show Pending/Approved/Denied state and denial reason.
- Added Manage Participants deny/reopen endpoints so admins can perform queue-equivalent request-state actions within the test page.
- Updated test-detail participant table to show explicit request state (Approved/Pending/Denied) so denied users are never rendered as pending.
- Filtered denied participants out of group-test detail participant list entirely.

## Risks and Assumptions
- Object storage credentials and bucket policy are admin-managed; upload feature should fail closed when disabled/misconfigured.
- Uploaded files must be strictly validated as images and bounded by max size.
- Stored object references should remain provider-agnostic and safe to render without exposing secrets.
- Tags should be normalized to a shared tag table so they work across group tests and public results.
- Hidden dashboard state should be per-user and should not alter test visibility rules.
- Existing Alembic revisions must remain untouched; all schema additions go in one new revision.
- Public results should be additive and not disturb existing closed-test `results_link` behavior.
- Dashboard grouping is best handled client-side using data attributes to avoid changing core query logic.
- Bulk approval must recalculate `amount_owed` for all approved participants in affected tests to avoid stale balances.
- Deny actions remove pending participation records; this intentionally allows users to submit a fresh request later.
- Denied requests are now retained for auditability and user feedback; re-request policy remains blocked unless admin clears/changes status.

## Validation Plan
- Add focused tests for storage config enforcement and upload validation failure paths.
- Run core unit tests including schema/security slices after upload + config changes.
- Run targeted unit tests for notification rendering and new schema behavior.
- Add or update tests for tag persistence, my-results aggregation, and dashboard hide toggles.
- Run a narrow test command before broader verification.
- Check migrations or schema-related tests to confirm the new revision is additive only.
- Add/extend admin route tests to verify action queue approvals and recalculated costs.
- Extend queue tests for deny/remove workflow, pagination behavior, and approve-all-filtered confirmation safety.
- Add focused tests for dashboard quick-request flow and join-state grouping labels.
- Update queue denial tests to assert stored denied state/reason, and add detail-page denied reason rendering test.
- Add focused tests for denied-user reapply and admin add-participant reactivation after denial.
- Add focused tests to confirm queue denial appears in Manage Participants and manage-page deny/reopen actions persist correctly.

## Validation Results
- Focused post-change validation passed: `python -m unittest tests.test_schema_migration tests.test_security`.
- Focused test slice passed: `tests.test_notifications`, `tests.test_lab_costs`, and `tests.test_schema_migration`.
- New focused queue validation passed: `python -m unittest tests.test_participant_removal`.
- Re-ran queue suite after form-structure fix; all queue tests still passed.
- Dashboard + queue participant suite passed: `python -m unittest tests.test_participant_removal` (7 tests, OK).
- Reapply/admin-reactivation workflow validated in updated participant suite (`python -m unittest tests.test_participant_removal`, 10 tests, OK).
- Cross-page action parity + denial visibility validated in updated participant suite (`python -m unittest tests.test_participant_removal`, 12 tests, OK).
- Reconfirmed denied-vs-pending detail-page rendering via updated participant suite assertions (`python -m unittest tests.test_participant_removal`, 12 tests, OK).
- Reconfirmed denied participants are excluded from detail participant table while denied requester messaging still renders (`python -m unittest tests.test_participant_removal`, 12 tests, OK).

## Documentation Updates
- README updated to cover tags, public results, dashboard controls, and the current unittest-based validation command.
- README expanded into a comprehensive feature-by-feature how-to guide covering end-user flows, admin workflows, action queue usage, notification setup, object storage setup for AWS/DO Spaces, result image behavior, testing commands, and troubleshooting.
- Added a dedicated admin one-pager quick start guide in `ADMIN_QUICK_START.md` for onboarding and day-to-day operations.
- README now includes a full Table of Contents and a prominent top-level link to `ADMIN_QUICK_START.md` for faster admin navigation.