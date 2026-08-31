import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect, text

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
            table_names = set(inspector.get_table_names())

            self.assertIn("tg_username", columns)
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
            self.assertIn("payment_options", table_names)
            self.assertIn("group_test_payment_options", table_names)
            self.assertIn("telegram_link_tokens", table_names)
            self.assertIn("telegram_webhook_updates", table_names)
            self.assertIn("telegram_status_digest_events", table_names)
            self.assertIn("user_digest_events", table_names)

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
        self.assertIn("telegram_webhook_updates", migration_text)
        self.assertIn("telegram_status_digest_events", migration_text)
        self.assertIn("digest_frequency", migration_text)
        self.assertIn("digest_hourly_minute_utc", migration_text)
        self.assertIn("digest_daily_hour_utc", migration_text)
        self.assertIn("user_digest_events", migration_text)


if __name__ == "__main__":
    unittest.main()
