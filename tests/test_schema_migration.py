import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect, text
from flask_migrate import upgrade

from app import create_app, db
from app.models import User


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
            self.assertIn("discord_body", template_columns)
            self.assertIn("root_body", template_columns)
            tag_columns = [column["name"] for column in inspector.get_columns("tags")]
            self.assertIn("is_active", tag_columns)
            self.assertIn("merged_into_id", tag_columns)
            self.assertIn("hidden_from_bots", tag_columns)
            self.assertIn("tags", table_names)
            self.assertIn("payment_options", table_names)
            self.assertIn("group_test_payment_options", table_names)
            self.assertIn("bot_link_tokens", table_names)
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
        self.assertIn("discord_body", migration_text)
        self.assertIn("root_body", migration_text)
        self.assertIn("merged_into_id", migration_text)
        self.assertIn("hidden_from_bots", migration_text)

    def test_alembic_upgrade_adds_tag_retirement_fields(self):
        migration_dir = Path(__file__).resolve().parent.parent / 'migrations'
        with self.app.app_context():
            upgrade(directory=str(migration_dir))
            inspector = inspect(db.engine)
            tag_columns = {item['name'] for item in inspector.get_columns('tags')}
            self.assertIn('is_active', tag_columns)
            self.assertIn('merged_into_id', tag_columns)
            self.assertIn('hidden_from_bots', tag_columns)
            tag_indexes = {item['name'] for item in inspector.get_indexes('tags')}
            self.assertIn('ix_tags_merged_into_id', tag_indexes)

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

    def test_alembic_upgrade_merges_link_tokens_without_losing_rows(self):
        """Rows in both per-provider tables must survive the merge with their provider tagged."""
        migration_dir = Path(__file__).resolve().parent.parent / 'migrations'
        with self.app.app_context():
            upgrade(directory=str(migration_dir), revision='e2f5a8c3b7d1')
            tables = set(inspect(db.engine).get_table_names())
            self.assertIn('telegram_link_tokens', tables)
            self.assertIn('discord_link_tokens', tables)

            # The ORM model knows about users.root_user_id, which does not exist at
            # this revision, so the fixture row is written in raw SQL.
            db.session.execute(text(
                "INSERT INTO users (username, email, password_hash, is_admin, is_active,"
                " receive_group_test_notifications, notification_channel, digest_frequency,"
                " digest_hourly_minute_utc, digest_daily_hour_utc, session_epoch, created_at)"
                " VALUES ('linker', 'linker@example.test', 'hash', 1, 1, 1, 'email',"
                " 'off', 0, 9, 0, '2026-01-01 00:00:00')"
            ))
            db.session.commit()
            user_id = db.session.execute(text(
                "SELECT id FROM users WHERE username = 'linker'"
            )).scalar_one()

            db.session.execute(text(
                "INSERT INTO telegram_link_tokens (user_id, token, expires_at, used_at, created_at)"
                " VALUES (:uid, 'tg-token', '2099-01-01 00:00:00', NULL, '2026-01-01 00:00:00')"
            ), {'uid': user_id})
            db.session.execute(text(
                "INSERT INTO discord_link_tokens (user_id, token, expires_at, used_at, created_at)"
                " VALUES (:uid, 'dc-token', '2099-01-01 00:00:00', '2026-01-02 00:00:00', '2026-01-01 00:00:00')"
            ), {'uid': user_id})
            db.session.commit()

            upgrade(directory=str(migration_dir))

            tables = set(inspect(db.engine).get_table_names())
            self.assertNotIn('telegram_link_tokens', tables)
            self.assertNotIn('discord_link_tokens', tables)

            rows = db.session.execute(text(
                "SELECT provider, token, used_at FROM bot_link_tokens ORDER BY provider"
            )).fetchall()
            self.assertEqual([(row[0], row[1]) for row in rows], [('discord', 'dc-token'), ('telegram', 'tg-token')])
            used_at = {row[0]: row[2] for row in rows}
            self.assertIsNone(used_at['telegram'], 'unconsumed token must stay usable')
            self.assertIsNotNone(used_at['discord'], 'consumed token must stay consumed')
            db.session.rollback()

    def test_alembic_upgrade_survives_the_same_token_in_both_legacy_tables(self):
        """The legacy tables were each UNIQUE(token) but never jointly so.

        A global UNIQUE(token) on the merge target made the second INSERT abort the
        upgrade, and because SQLite/MySQL do not roll back DDL the orphan table then
        made every retry die on "table already exists".
        """
        migration_dir = Path(__file__).resolve().parent.parent / 'migrations'
        with self.app.app_context():
            upgrade(directory=str(migration_dir), revision='e2f5a8c3b7d1')
            db.session.execute(text(
                "INSERT INTO users (username, email, password_hash, is_admin, is_active,"
                " receive_group_test_notifications, notification_channel, digest_frequency,"
                " digest_hourly_minute_utc, digest_daily_hour_utc, session_epoch, created_at)"
                " VALUES ('shared', 'shared@example.test', 'hash', 1, 1, 1, 'email',"
                " 'off', 0, 9, 0, '2026-01-01 00:00:00')"
            ))
            db.session.commit()
            user_id = db.session.execute(text(
                "SELECT id FROM users WHERE username = 'shared'"
            )).scalar_one()
            for table in ('telegram_link_tokens', 'discord_link_tokens'):
                db.session.execute(text(
                    f"INSERT INTO {table} (user_id, token, expires_at, used_at, created_at)"
                    " VALUES (:uid, 'SAME-TOKEN', '2099-01-01 00:00:00', NULL, '2026-01-01 00:00:00')"
                ), {'uid': user_id})
            db.session.commit()

            upgrade(directory=str(migration_dir))

            rows = db.session.execute(text(
                "SELECT provider, token FROM bot_link_tokens ORDER BY provider"
            )).fetchall()
            self.assertEqual(
                [(row[0], row[1]) for row in rows],
                [('discord', 'SAME-TOKEN'), ('telegram', 'SAME-TOKEN')],
            )
            db.session.rollback()

    def test_alembic_upgrade_adds_provider_notification_bodies(self):
        migration_dir = Path(__file__).resolve().parent.parent / 'migrations'
        with self.app.app_context():
            upgrade(directory=str(migration_dir))
            inspector = inspect(db.engine)
            template_columns = {item['name'] for item in inspector.get_columns('notification_templates')}
            self.assertIn('discord_body', template_columns)
            self.assertIn('root_body', template_columns)


if __name__ == "__main__":
    unittest.main()
