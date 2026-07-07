import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect, text

from app import create_app, db
from app import ensure_database_schema


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

    def test_ensure_database_schema_adds_missing_columns_for_existing_table(self):
        with self.app.app_context():
            db.session.execute(text("""
                CREATE TABLE users (
                    id INTEGER NOT NULL,
                    username VARCHAR(80) NOT NULL,
                    email VARCHAR(120) NOT NULL,
                    password_hash VARCHAR(256) NOT NULL,
                    PRIMARY KEY (id)
                )
            """))
            db.session.commit()

            ensure_database_schema(self.app)

            inspector = inspect(db.engine)
            columns = [column["name"] for column in inspector.get_columns("users")]

            self.assertIn("tg_username", columns)
            self.assertIn("is_admin", columns)
            self.assertIn("is_active", columns)
            self.assertIn("created_at", columns)


if __name__ == "__main__":
    unittest.main()
