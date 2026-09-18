import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect, text
from flask_migrate import upgrade

from app import create_app, db


class SchemaMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path}",
        })

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def test_database_schema_matches_current_models(self):
        with self.app.app_context():
            db.create_all()

            inspector = inspect(db.engine)
            columns = [column["name"] for column in inspector.get_columns("users")]
            participation_columns = [column["name"] for column in inspector.get_columns("participations")]
            telegram_command_columns = [column["name"] for column in inspector.get_columns("telegram_command_templates")]
            table_names = set(inspector.get_table_names())

            self.assertIn("tg_username", columns)
            self.assertIn("discord_username", columns)
            self.assertIn("discord_user_id", columns)
            self.assertIn("telegram_chat_id", columns)
            self.assertIn("telegram_user_id", columns)
            self.assertIn("is_admin", columns)
            self.assertIn("is_active", columns)
            self.assertIn("digest_frequency", columns)
            self.assertIn("digest_hourly_minute_utc", columns)
            self.assertIn("digest_daily_hour_utc", columns)
            self.assertIn("digest_last_sent_at", columns)
            self.assertIn("created_at", columns)
            self.assertIn("preferred_payment_option_id", participation_columns)
            self.assertIn("preferred_payment_snapshot", participation_columns)
            self.assertIn("payment_claimed_at", participation_columns)
            self.assertIn("payment_verified_at", participation_columns)
            self.assertIn("payment_verified_by_id", participation_columns)
            template_columns = [column["name"] for column in inspector.get_columns("notification_templates")]
            self.assertIn("is_default_payment_review", template_columns)
            self.assertIn("payment_options", table_names)
            self.assertIn("group_test_payment_options", table_names)
            self.assertIn("telegram_link_tokens", table_names)
            self.assertIn("discord_link_tokens", table_names)
            self.assertIn("telegram_webhook_updates", table_names)
            self.assertIn("telegram_status_digest_events", table_names)
            self.assertIn("user_digest_events", table_names)
            self.assertIn("telegram_command_templates", table_names)
            self.assertIn("telegram_command_invocations", table_names)
            self.assertIn("discord_command_invocations", table_names)
            self.assertIn("result_analysis_runs", table_names)
            self.assertIn("result_analysis_findings", table_names)
            analysis_columns = [column["name"] for column in inspector.get_columns("result_analysis_runs")]
            self.assertIn("source_sha256", analysis_columns)
            self.assertIn("lease_expires_at", analysis_columns)
            self.assertIn("provider_model", analysis_columns)
            self.assertIn("bypass_duplicate_check", analysis_columns)
            public_result_columns = [column["name"] for column in inspector.get_columns("public_results")]
            self.assertIn("publication_status", public_result_columns)
            self.assertIn("review_state_json", public_result_columns)
            self.assertIn("allow_non_private", telegram_command_columns)
            self.assertIn("allowed_chat_ids", telegram_command_columns)
            self.assertIn("allowed_thread_ids", telegram_command_columns)

    def test_latest_migration_includes_lab_name_column(self):
        migration_dir = Path(__file__).resolve().parent.parent / "migrations" / "versions"
        migration_files = sorted(migration_dir.glob("*.py"))
        self.assertTrue(migration_files)

        migration_text = "\n".join(path.read_text(encoding="utf-8") for path in migration_files)
        self.assertIn("lab_name", migration_text)
        self.assertIn("public_results", migration_text)
        self.assertIn("dashboard_hidden_group_tests", migration_text)
        self.assertIn("results_posted_at", migration_text)
        self.assertIn("denied_reason", migration_text)
        self.assertIn("telegram_chat_id", migration_text)
        self.assertIn("telegram_user_id", migration_text)
        self.assertIn("payment_options", migration_text)
        self.assertIn("group_test_payment_options", migration_text)
        self.assertIn("telegram_link_tokens", migration_text)
        self.assertIn("discord_link_tokens", migration_text)
        self.assertIn("telegram_webhook_updates", migration_text)
        self.assertIn("telegram_status_digest_events", migration_text)
        self.assertIn("digest_frequency", migration_text)
        self.assertIn("digest_hourly_minute_utc", migration_text)
        self.assertIn("digest_daily_hour_utc", migration_text)
        self.assertIn("user_digest_events", migration_text)
        self.assertIn("telegram_command_templates", migration_text)
        self.assertIn("telegram_command_invocations", migration_text)
        self.assertIn("discord_command_invocations", migration_text)
        self.assertIn("args_policy", migration_text)
        self.assertIn("rate_limit_window_seconds", migration_text)
        self.assertIn("allow_non_private", migration_text)
        self.assertIn("allowed_chat_ids", migration_text)
        self.assertIn("allowed_thread_ids", migration_text)
        self.assertIn("result_analysis_runs", migration_text)
        self.assertIn("result_analysis_findings", migration_text)
        self.assertIn("payment_claimed_at", migration_text)
        self.assertIn("payment_verified_at", migration_text)
        self.assertIn("payment_verified_by_id", migration_text)
        self.assertIn("is_default_payment_review", migration_text)

    def test_alembic_upgrade_creates_result_analysis_schema(self):
        migration_dir = Path(__file__).resolve().parent.parent / 'migrations'
        with self.app.app_context():
            upgrade(directory=str(migration_dir))
            inspector = inspect(db.engine)
            tables = set(inspector.get_table_names())
            self.assertIn('result_analysis_runs', tables)
            self.assertIn('result_analysis_findings', tables)
            run_indexes = {item['name'] for item in inspector.get_indexes('result_analysis_runs')}
            self.assertIn('ix_result_analysis_status_queue', run_indexes)
            run_columns = {item['name'] for item in inspector.get_columns('result_analysis_runs')}
            self.assertIn('bypass_duplicate_check', run_columns)
            public_result_columns = {item['name'] for item in inspector.get_columns('public_results')}
            self.assertIn('publication_status', public_result_columns)
            self.assertIn('review_state_json', public_result_columns)

    def test_alembic_upgrade_adds_payment_review_fields(self):
        migration_dir = Path(__file__).resolve().parent.parent / 'migrations'
        with self.app.app_context():
            upgrade(directory=str(migration_dir))
            inspector = inspect(db.engine)
            participation_columns = {item['name'] for item in inspector.get_columns('participations')}
            self.assertIn('payment_claimed_at', participation_columns)
            self.assertIn('payment_verified_at', participation_columns)
            self.assertIn('payment_verified_by_id', participation_columns)
            template_columns = {item['name'] for item in inspector.get_columns('notification_templates')}
            self.assertIn('is_default_payment_review', template_columns)


if __name__ == "__main__":
    unittest.main()
