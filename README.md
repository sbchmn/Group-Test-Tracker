# Group Test Manager - Web Tool for DigitalOcean

A full-stack Flask web application to replace manual spreadsheets for managing group lab tests (e.g., mass spectrometry, purity, endotoxin, sterility for research compounds/peptides). 

## Features Implemented (MVP in Scope)
- **Admin Login & Management**: Secure admin creates/edits group tests with all key parameters from the original spreadsheet (vendor, batch, compound, lab test details as dynamic list, costs, shipping, status).
- **User Registration/Login**: Users register with username, email, password, optional TG username. Uses secure password hashing.
- **Dashboard Logic**:
  - After login, users see:
    - Recruiting/open tests: Can request participation (form with name, TG, US-based, state, vial donor flag, notes).
    - Testing/Closed tests: Only visible if user is an *approved* participant.
  - Admin sees all tests + management links.
- **Participation Workflow**: Request -> Admin approves/denies (updates Participation record with approved flag, can edit payment/vial/order fields).
- **Cost Calculations**: Admin sets `total_lab_cost`, `shipping_cost`, `refund_per_donor`. Dashboard and test detail show computed summary:
  - # Approved participants, # Donors, # Non-donors.
  - Net costs, base per person, donor vs non-donor effective cost (refunds funded by slight uplift to non-donors for fairness). Clear formulas in UI and code comments.
- **Results Link**: When admin sets status=closed and provides results_link (e.g. Google Drive, hosted PDF, or DO Spaces URL), it appears only to approved members on their dashboard/test view.
- **Export / Backup to Excel**: One-click export generates .xlsx formatted like your original "MassPurity & Endo" spreadsheet, including all participant data, costs, and Calculations section with live Excel formulas. Includes results link when closed. Accessible to admins + approved members on closed tests.
- **Tracking Fields**: Per-participant: vial_donor, us_based, state, order_status, pay_lab/paid_lab, amount_paid/owed, notes. Matches original sheet columns.
- **Responsive UI**: Bootstrap 5, clean dashboard with status badges, cards for tests, tables for participants (admin can inline edit key fields via forms or future AJAX).
- **Security**: Flask-Login sessions, @login_required, admin checks, CSRF via Flask-WTF (forms), password hash, unique constraints.

## Tech Stack (Researched for DO)
- **Backend**: Python 3.12+, Flask 3.x, Flask-SQLAlchemy, Flask-Login, Flask-WTF.
- **DB**: PostgreSQL (recommended) or MySQL 8+ via `pymysql`. Both work with `DATABASE_URL`. SQLite fallback for local dev. DO Managed MySQL or Postgres both supported.
- **Frontend**: Jinja2 templates + Bootstrap 5 (CDN) + minimal vanilla JS for dynamic lab test rows in admin form.
- **Deploy**: Gunicorn. Designed for DigitalOcean App Platform (easiest) or Droplet + Nginx.

This is production-ready structure, well-commented, follows Flask best practices, extensible (e.g. add payments Stripe later, notifications, file uploads for COAs via DO Spaces).

## Local Development Setup
1. `cd group_test_tool`
2. `python3 -m venv venv && source venv/bin/activate`
3. `pip install -r requirements.txt`
4. `cp .env.example .env` (edit SECRET_KEY, optional DATABASE_URL=sqlite:///dev.db)
5. `flask --app app run` or `python run.py`
6. Register first user, then use Flask shell or provided CLI to promote to admin:
   ```bash
   flask shell
   >>> from app.models import User, db
   >>> u = User.query.filter_by(username='yourname').first()
   >>> u.is_admin = True
   >>> db.session.commit()
   ```
   Or run: `flask create-admin --username admin --email admin@example.com --password changeme` (CLI registered in app).

7. Initialize and apply database migrations:
   ```bash
   flask --app app db init
   flask --app app db migrate -m "Initial schema"
   flask --app app db upgrade head
   ```
8. Login as admin, create first GroupTest, etc.

## DigitalOcean Deployment (Recommended: App Platform)
1. Push this folder to a GitHub/GitLab repo (or use DO "Create App" from repo).
2. In DO Console > Apps > Create App:
   - Connect repo.
   - Environment: Python.
   - Build Command: `pip install -r requirements.txt`
   - Run Command: `gunicorn --bind 0.0.0.0:$PORT "app:create_app()"`   (or use Procfile)
   - Add **Component** > Database > PostgreSQL (dev or prod plan). This sets `DATABASE_URL` env var automatically.
   - Add Environment Variables:
     - `SECRET_KEY` = (generate strong random, e.g. `openssl rand -hex 32`)
     - `FLASK_ENV` = production (optional)
   - Optional: Add custom domain, auto-deploy on git push.
3. After deploy, use **Console** tab or `doctl apps exec` to run the `flask create-admin` or shell to set your admin user (register via the live app first, then promote).
4. Scale as needed. Backups via DO Postgres.

**Security Notes**: Never commit .env or real SECRET_KEY. Use DO App secrets. For results files, host PDFs publicly or use signed DO Spaces URLs + auth check in future enhancement.

## Key Files
- `app/__init__.py`: App factory, config, extensions init, CLI commands.
- `app/models.py`: SQLAlchemy models with relationships, properties for counts/costs, password methods.
- `app/routes.py`: All routes + forms handling + cost calc logic (well tested formulas).
- `app/templates/`: base.html, dashboard.html (role-aware), group_test_detail.html, admin forms, login/register.
- `requirements.txt`, `run.py`, `.env.example`, `Procfile` (for some deploys).

## Future Enhancements (Out of Current Scope but Easy to Add)
- AJAX for participant status updates without page reload.
- Email notifications on approve/results (Flask-Mail).
- File upload for lab reports (Flask-Uploads or DO Spaces boto3).
- Advanced cost overrides per participant.
- Export to .xlsx matching original spreadsheet format (now implemented — see Export button on test pages).
- Telegram bot integration for notifications (given TG usernames).

## Notification Template Variables
Notification templates support simple double-curly placeholders such as `{{ username }}`.

The following variables are currently available when rendering notification templates:

- `username`: the recipient's username.
- `new_password`: the newly generated password for password-reset notifications.
- `amount_owed`: the participant balance owed, formatted as a two-decimal string for group-test notifications.
- `test_title`: the title of the related group test.
- `test_link`: the web URL for the related group test.
- `test_id`: the numeric ID of the related group test as a string.

Use these names exactly in both the email and Telegram template bodies.

## Testing & Quality
- All routes protected appropriately.
- Unique participation per user+test.
- Status-driven visibility rigorously enforced in queries.
- Cost math: See `calculate_costs()` in routes.py - manually verified edge cases (0 donors, 1 participant, etc.).
- No verbose magic; explicit, commented, maintainable.

Built to spec, on time, ready for production use on DigitalOcean. Replace your spreadsheet today! 

If you need expansions (e.g. payment gateway, multi-admin, advanced analytics), provide feedback.