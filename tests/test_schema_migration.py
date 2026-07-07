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

            self.assertIn("tg_username", columns)
            self.assertIn("is_admin", columns)
            self.assertIn("is_active", columns)
            self.assertIn("created_at", columns)


if __name__ == "__main__":
    unittest.main()
