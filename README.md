# Group Test Manager

Group Test Manager is a Flask-based web app for coordinating group lab tests, participant requests, cost sharing, and notification-driven follow-up without relying on spreadsheets.

## Application map

The app is organized around a single Flask app factory and a small set of domain modules:

- App factory and configuration: [app/__init__.py](app/__init__.py)
  - Creates the Flask app, loads environment settings, wires SQLAlchemy/Flask-Login/CSRF, registers the main blueprint, and exposes CLI commands such as `create-admin` and `init-db`.
- Data model: [app/models.py](app/models.py)
  - Defines users, group tests, participations, notification templates, and notification configuration.
- Route layer and business logic: [app/routes.py](app/routes.py)
  - Handles authentication, registration, password reset, profile editing, dashboard routing, group-test CRUD, participant requests/approvals, exports, and admin management screens.
- Notification layer: [app/notifications.py](app/notifications.py)
  - Sends Mailjet email and Telegram messages, renders template variables, appends notification logs, and handles fallback behavior.
- Templates and UI: [app/templates](app/templates)
  - Contains the Bootstrap-based interface for public pages, dashboard, test detail, and admin workflows.
- Database migrations: [migrations/versions](migrations/versions)
  - Tracks schema changes for the app over time.

## Feature inventory

### Public and authenticated user flows
- User registration with username, email, password, and optional Telegram username.
- Login and logout with Flask-Login session protection.
- Password reset flow that can send a reset message through email or Telegram.
- Self-service profile editing for the signed-in user, including username, email, Telegram username, notification settings, and password.
- Dashboard that shows recruiting tests to all users and testing/closed tests only to approved participants.

### Group-test workflow
- Admin can create and edit group tests with fields such as title, description, start date, vendor, batch number, compound, size, lab/provider, cost inputs, shipping, donor-reimbursement policy, and results link.
- Users can request to join recruiting tests.
- Admins can approve, remove, or manually add participants.
- Each participant record tracks fields such as name, Telegram username, approval status, verified/active flags, order/payment state, donor status, state, and notes.
- Cost calculations are computed from the group test inputs and displayed in the UI for both admins and approved participants.

### Admin capabilities
- Manage users, create/edit accounts, toggle active status, and trigger password resets.
- Manage notification templates and notification configuration.
- Send participant notifications for a test using a selected template.
- Export test data to Excel-compatible output for backup or reporting.
- View and manage participant approvals and status updates.

### Notifications and templating
- Supports Mailjet email delivery and Telegram delivery.
- Telegram notification support is still a work in progress and may require additional validation or refinement depending on the deployment environment.
- Uses a configurable service base URL to build fully qualified links into notifications.
- Supports editable notification templates for:
  - default password reset emails
  - default registration welcome emails
  - participant notification emails/Telegram messages
- Debug logging can be enabled for notification request/response details.
- Existing notification config values are displayed partially masked in the admin form for safety.

### Security and data handling
- Password hashing uses Werkzeug’s strong password hashing.
- Login and admin routes are protected by Flask-Login and route decorators.
- CSRF protection is enabled for forms.
- Unique constraints and access rules help prevent duplicate participation entries and unauthorized access.

## Environment and deployment notes

The app expects these runtime settings:

- `SECRET_KEY`: required in production and non-test environments.
- `DATABASE_URL`: optional; if absent the app falls back to a local SQLite file for development.
- `FLASK_ENV`: optional; useful for local development and deployment hints.
- `NOTIFICATION_LOG_MAX_BYTES`: optional; controls notification log size trimming.

Recommended deployment target: DigitalOcean App Platform or a similar container or VM-based deployment with Gunicorn and a managed PostgreSQL or MySQL database.

## Local development

1. Create and activate a Python virtual environment.
2. Install dependencies from `requirements.txt`.
3. Create a local `.env` file and set at least `SECRET_KEY`.
4. Run the app with `python run.py` or `flask --app app run`.
5. Initialize the database and apply migrations if needed:
   ```bash
   flask --app app db upgrade head
   ```
6. Create the first admin user with the CLI helper:
   ```bash
   flask --app app create-admin --username admin --email admin@example.com --password changeme
   ```

## Testing

Run the regression suite with:

```bash
python -m pytest
```

## Notification template variables

Template variables are rendered with double-curly placeholders such as `{{ username }}`.

The following variables are currently available:

- `username`: the recipient’s username.
- `new_password`: the newly generated password used in password-reset notifications.
- `amount_owed`: the participant balance owed, formatted as a two-decimal string for group-test notifications.
- `test_title`: the title of the related group test.
- `test_link`: the fully qualified web URL for the related group test.
- `test_id`: the numeric ID of the related group test as a string.
- `login_url`: the fully qualified login URL used in registration welcome emails.

Use these names exactly in both email and Telegram templates.

## Key project files

- [app/__init__.py](app/__init__.py): app factory, configuration, CLI registration, and extension initialization.
- [app/models.py](app/models.py): SQLAlchemy models and relationships.
- [app/routes.py](app/routes.py): route handlers, forms, feature logic, and permissions.
- [app/notifications.py](app/notifications.py): notification rendering, delivery, and logging.
- [app/templates](app/templates): UI templates for public, authenticated, and admin experiences.
- [migrations/versions](migrations/versions): migration history.
