"""
Group Test Manager - Flask Application Factory
This follows the official Flask application factory pattern for better testability,
configuration management, and deployment (especially DigitalOcean App Platform + gunicorn).
All extensions initialized here without circular imports.
"""

import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_migrate import Migrate
from dotenv import load_dotenv

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
    
    # === Configuration ===
    # SECRET_KEY required for sessions, CSRF, Flask-Login
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-insecure-change-in-prod')
    
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

    # Ensure csrf_token() is always available in Jinja2 templates
    @app.context_processor
    def inject_csrf_token():
        from flask_wtf.csrf import generate_csrf
        return dict(csrf_token=lambda: generate_csrf())
    
    # Apply any test overrides
    if config_overrides:
        app.config.update(config_overrides)
    
    # === Initialize Extensions ===
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
        return User.query.get(int(user_id))
    
    # === Register Blueprints ===
    from .routes import main_bp
    app.register_blueprint(main_bp)
    
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