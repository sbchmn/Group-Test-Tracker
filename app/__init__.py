"""
Group Test Manager - Flask Application Factory
This follows the official Flask application factory pattern for better testability,
configuration management, and deployment (especially DigitalOcean App Platform + gunicorn).
All extensions initialized here without circular imports.
"""

import os
from flask import Flask, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_migrate import Migrate
from dotenv import load_dotenv
from .version import APP_NAME, APP_VERSION
from .saas import (
    managed_admin_docs_url,
    managed_mode_enabled,
    managed_public_url,
    managed_user_docs_url,
    report_instance_event,
    subscription_status,
)

# Extensions (initialized in create_app to support factory)
db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()

# Load .env early for config
load_dotenv()


def create_app(config_overrides=None):
    app = Flask(__name__, 
                template_folder='templates',
                static_folder='static')
    # DigitalOcean App Platform and similar proxies terminate TLS upstream.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config['APP_VERSION'] = APP_VERSION
    app.config['LEGAL_OPERATOR_NAME'] = os.environ.get('LEGAL_OPERATOR_NAME', '').strip()
    app.config['LEGAL_CONTACT_EMAIL'] = os.environ.get('LEGAL_CONTACT_EMAIL', '').strip()
    app.config['LEGAL_MAILING_ADDRESS'] = os.environ.get('LEGAL_MAILING_ADDRESS', '').strip()
    app.config['LEGAL_GOVERNING_LAW'] = os.environ.get('LEGAL_GOVERNING_LAW', '').strip()
    app.config['LEGAL_EFFECTIVE_DATE'] = os.environ.get('LEGAL_EFFECTIVE_DATE', 'September 12, 2026').strip()

    @app.context_processor
    def inject_app_version():
        return {
            'app_version': app.config['APP_VERSION'],
            'legal_operator_name': app.config.get('LEGAL_OPERATOR_NAME') or f'{APP_NAME} operator',
            'legal_contact_email': app.config.get('LEGAL_CONTACT_EMAIL'),
            'legal_mailing_address': app.config.get('LEGAL_MAILING_ADDRESS'),
            'legal_governing_law': app.config.get('LEGAL_GOVERNING_LAW'),
            'legal_effective_date': app.config.get('LEGAL_EFFECTIVE_DATE') or 'September 12, 2026',
            'managed_mode': managed_mode_enabled(),
            'managed_public_url': managed_public_url(),
            'managed_user_docs_url': managed_user_docs_url(),
            'managed_admin_docs_url': managed_admin_docs_url(),
            'subscription_status': subscription_status(),
        }

    @app.get('/health/ready')
    def readiness_probe():
        return jsonify({'status': 'ready'}), 200
    
    # === Configuration ===
    # SECRET_KEY required for sessions, CSRF, Flask-Login
    testing_mode = bool(config_overrides and config_overrides.get('TESTING'))
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        if testing_mode:
            secret_key = 'test-secret-key'
        else:
            raise RuntimeError('SECRET_KEY environment variable is required for this application.')
    app.config['SECRET_KEY'] = secret_key
    
    # Database URL handling - supports PostgreSQL, MySQL 8+, and SQLite
    database_url = os.environ.get('DATABASE_URL')

    if database_url:
        # Normalize common cloud provider URL schemes for SQLAlchemy
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        elif database_url.startswith('mysql://'):
            database_url = database_url.replace('mysql://', 'mysql+pymysql://', 1)
            # DigitalOcean MySQL often uses ssl-mode=REQUIRED → convert to ssl_mode
            database_url = database_url.replace('ssl-mode=', 'ssl_mode=')
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    else:
        # Fallback for local development
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///group_tests.db'
        print("WARNING: DATABASE_URL not found. Using SQLite fallback.")

    # Safety check to catch bad URLs early (common with passwords containing # or special chars)
    try:
        from sqlalchemy.engine import make_url
        make_url(app.config.get('SQLALCHEMY_DATABASE_URI', ''))
    except Exception as e:
        print(f"ERROR parsing DATABASE_URL: {e}")
        raw_url = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        preview = raw_url[:80] + "..." if len(raw_url) > 80 else raw_url
        print(f"Received URL preview: {preview}")
        print("Check that DATABASE_URL is correctly set in your Heroku config (no extra spaces/quotes).")
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///group_tests.db'

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    # WTF/CSRF settings
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['WTF_CSRF_TIME_LIMIT'] = 3600  # 1 hour forms
    app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH_MB', '12')) * 1024 * 1024

    # Ensure csrf_token() is always available in Jinja2 templates
    @app.context_processor
    def inject_csrf_token():
        from flask_wtf.csrf import generate_csrf
        return dict(csrf_token=lambda: generate_csrf())
    
    # Apply any test overrides
    if config_overrides:
        app.config.update(config_overrides)
    
    # === Initialize Extensions ===
    # Keep migration history intact when changing database schema: prefer adding a new
    # Alembic revision on top of the existing chain rather than rewriting earlier ones.
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    
    # Flask-Login config
    login_manager.login_view = 'main.login'
    login_manager.login_message_category = 'info'
    login_manager.session_protection = 'strong'
    
    @login_manager.user_loader
    def load_user(user_id):
        from .models import User
        # get_id() embeds the session epoch as "<id>:<epoch>"; a mismatch (e.g. after a
        # support-account disable/rotate) must invalidate the session immediately.
        try:
            raw_id, _, raw_epoch = str(user_id).partition(':')
            user = User.query.get(int(raw_id))
        except (TypeError, ValueError):
            return None
        if user is None:
            return None
        if raw_epoch and str(user.session_epoch) != raw_epoch:
            return None
        return user
    
    # === Register Blueprints ===
    from .routes import main_bp
    app.register_blueprint(main_bp)
    from .control_plane_routes import control_plane_bp
    app.register_blueprint(control_plane_bp)

    # === Notification defaults ===
    with app.app_context():
        from .models import NotificationTemplate
        try:
            if not NotificationTemplate.query.filter_by(is_default_password_reset=True).first():
                default_template = NotificationTemplate(
                    name='Default Password Reset',
                    description='Default password reset message',
                    email_subject='Your password has been reset',
                    email_body='<p>Hello {{ username }},</p><p>Your temporary password is: {{ new_password }}</p>',
                    telegram_body='Hello {{ username }}, your temporary password is: {{ new_password }}',
                    is_default_password_reset=True,
                    is_active=True,
                )
                db.session.add(default_template)
                db.session.commit()
        except Exception:
            # The table may not exist yet when the app boots in a fresh test/database context.
            # The normal create_all() path will populate it afterward.
            db.session.rollback()
    
    # === CLI Commands (for admin bootstrap on DO) ===
    from .models import User
    import click
    
    @app.cli.command('create-admin')
    @click.option('--username', prompt=True, help='Username of user to promote (or create)')
    @click.option('--email', prompt=True, help='Email (required only when creating a new user)')
    @click.option('--password', prompt=False, hide_input=True, default=None, help='Password (only needed when creating a new user)')
    def create_admin(username, email, password):
        """Promote an existing user to admin, or create a new admin user."""
        with app.app_context():
            user = User.query.filter_by(username=username).first()

            if not user:
                # Creating new user
                if not password:
                    click.echo("Error: --password is required when creating a new user.")
                    return
                user = User(username=username, email=email, is_admin=True)
                user.set_password(password)
                db.session.add(user)
                click.echo(f"Created new admin user: {username}")
            else:
                # Promoting existing user (no password needed)
                user.is_admin = True
                click.echo(f"Promoted existing user to admin: {username}")

            db.session.commit()
            click.echo("Admin privileges set successfully.")

    @app.cli.command('demote-admin')
    @click.option('--username', prompt=True, help='Username of admin to demote')
    def demote_admin(username):
        """Remove admin privileges from a user."""
        with app.app_context():
            user = User.query.filter_by(username=username).first()
            if not user:
                click.echo(f"User '{username}' not found.")
                return
            if not user.is_admin:
                click.echo(f"User '{username}' is not an admin.")
                return

            user.is_admin = False
            db.session.commit()
            click.echo(f"Successfully demoted '{username}' from admin.")
    
    @app.cli.command('init-db')
    def init_db():
        """Create all tables for development environments."""
        with app.app_context():
            db.create_all()
            click.echo("Development tables created/verified.")

    @app.cli.command('send-user-digests')
    def send_user_digests():
        """Send due hourly/daily digest emails for users who opted in via profile settings."""
        from .notifications import send_due_user_digests

        with app.app_context():
            result = send_due_user_digests()
            click.echo(f"Digest delivery complete: users={result.get('users', 0)} events={result.get('events', 0)}")

    @app.cli.command('result-analysis-worker')
    @click.option('--once', is_flag=True, help='Process at most one queued run and exit.')
    @click.option('--poll-seconds', type=click.IntRange(1, 60), default=5, show_default=True)
    def result_analysis_worker(once, poll_seconds):
        """Process durable laboratory result-analysis jobs."""
        import time
        from .result_analysis.jobs import process_next_run

        with app.app_context():
            report_instance_event('status', {
                'component': 'result-analysis-worker',
                'contract_version': os.environ.get('GTT_CONTRACT_VERSION', '1').strip() or '1',
            })
            click.echo(f'Result analysis worker started; polling every {poll_seconds} seconds.')
            while True:
                run = None
                try:
                    run = process_next_run()
                    if run:
                        click.echo(f'Result analysis run {run.id}: {run.status}')
                finally:
                    # Never retain an identity map or transaction across polls.
                    db.session.remove()
                if once:
                    return
                if not run:
                    time.sleep(poll_seconds)

    # Alias matching the SaaS control plane's provisioned run_command exactly.
    app.cli.add_command(result_analysis_worker, name='run-result-analysis-worker')

    @app.cli.command('report-control-plane-status')
    def report_control_plane_status():
        """Report the current managed tenant status to the control plane."""
        from .version import APP_VERSION
        result = report_instance_event('status', {
            'app_version': APP_VERSION,
            'contract_version': os.environ.get('GTT_CONTRACT_VERSION', '1').strip() or '1',
        })
        click.echo('Control-plane status reported.' if result is not False else 'Control-plane status report failed.')

    @app.cli.command('run-discord-bot')
    def run_discord_bot():
        """Start the Discord gateway worker (control-plane managed deployments)."""
        from . import discord_bot

        report_instance_event('status', {
            'component': 'discord-bot-worker',
            'contract_version': os.environ.get('GTT_CONTRACT_VERSION', '1').strip() or '1',
        })
        discord_bot.main()

    # === Shell context for easy debugging ===
    @app.shell_context_processor
    def make_shell_context():
        from .models import User, GroupTest, Participation
        return {'db': db, 'User': User, 'GroupTest': GroupTest, 'Participation': Participation, 'app': app}
    
    return app


# For direct `python run.py` or some gunicorn setups
if __name__ == '__main__':
    app = create_app()
    app.run(debug=os.environ.get('FLASK_ENV') == 'development')
