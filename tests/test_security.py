import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app, db
from app.models import User


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path}",
        })
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def test_create_user_does_not_flash_generated_password(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.commit()

        self.client.post(
            "/login",
            data={"username": "admin", "password": "secret"},
            follow_redirects=True,
        )

        response = self.client.post(
            "/admin/users/new",
            data={
                "username": "newuser",
                "email": "new@example.com",
                "password": "",
                "is_admin": False,
                "is_active": True,
                "receive_group_test_notifications": True,
                "notification_channel": "email",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Temporary password generated", response.get_data(as_text=True))

    def test_create_app_requires_secret_key_outside_test_mode(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                create_app()
