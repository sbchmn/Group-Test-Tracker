# Revision History (Since Admin Action Queue)

## Short Version (Chat-Ready)
- 2026-08-20: Added Admin Action Queue for centralized approval workflows across tests.
- 2026-08-20: Expanded queue and dashboard grouping/filter behavior with usability improvements.
- 2026-08-20: Added denied-request tracking (state, timestamp, reason), surfaced denied status in UI, and enabled reapply flow.
- 2026-08-20: Added admin action parity across views (queue + manage participants) and improved participant state visibility.
- 2026-08-20: Refined group test detail behavior for denied/pending participants and tightened display logic.
- 2026-08-25: Added production-ready result image uploads with S3-compatible object storage (AWS S3 and DigitalOcean Spaces), admin storage configuration UI, thumbnails, and full-size modal viewing.

## Detailed Version (With Commit References)
1. 233ed50 (2026-08-20)
- Introduced Admin Action Queue.
- Added queue page and admin navigation entry.
- Added test coverage for participant queue operations.

2. 6dc5a68 (2026-08-20)
- Enhanced queue usability and grouping behavior.
- Added UI/UX refinements for dashboard and queue filtering/grouping.
- Expanded related participant workflow tests.

3. 1717e63 (2026-08-20)
- Added denied-request persistence fields and migration.
- Updated request lifecycle behavior to preserve denied records with reason and timestamp.
- Updated dashboard and detail views to reflect denied state and allow reapply flow.
- Updated migration/schema and participant workflow tests.

4. d5b4f9c (2026-08-20)
- Applied hotfixes to admin participant management behavior.
- Improved consistency between queue actions and manage-participants actions.

5. bf33f69 (2026-08-20)
- Refined group test detail rendering for participant state visibility.
- Improved denied/pending presentation edge cases.

6. 2c72166 (2026-08-20)
- Additional participant-state and detail-page behavior fixes.
- Finalized denied-user flow polish for that release cycle.

7. a13f33f (2026-08-25)
- Added result image uploads for Public Results and Group Test results.
- Implemented S3-compatible object storage integration for AWS S3 and DigitalOcean Spaces.
- Added admin Storage Config page for enablement and credentials/configuration.
- Added thumbnails next to result links and full-size modal image viewing.
- Added additive schema migration for stored image keys.

## One-Liner Summary
From the Admin Action Queue onward, this branch evolved from queue-first participant workflow management into a production-ready results experience with denied-request lifecycle controls and S3-compatible result image hosting/display.
