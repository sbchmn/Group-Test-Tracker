# Payment and responsive browser checks

Run `python tests/browser/payment_workflow.py` from the repository root with Chrome,
the application dependencies, and the optional `websockets` development dependency
available. This script is separate from pytest discovery because it launches a browser.

On Windows it defaults to the standard Chrome installation. Set `CHROME_BINARY` to
use another Chrome/Chromium executable. Set `BROWSER_ARTIFACTS_DIR` to retain screenshots
in a specific directory; otherwise the script prints a temporary artifact directory.

The script starts its own localhost server and isolated temporary SQLite database.
Storage and notification delivery are mocked; no live records or external messages
are changed. It checks:

- New reports with several payment methods and no saved selection.
- Failed modal initialization hiding submission and decision controls.
- Image and transaction-ID submission, updates, denial, resubmission and approval.
- Verified payments displaying read-only evidence.
- Phone, tablet and desktop geometry with reachable modal footers.
- Live optional/either/all proof summaries on both payment-option forms.
- Missing optional preview markup leaving other initialization intact.
- Queue selection containing only join requests and preserving submitted IDs.
- More-menu keyboard navigation and Escape handling.

The broader responsive audit screenshots and measurements are in
`docs/reviews/responsive-audit-2026-10-24/`, with matching updated captures under `after/`.
