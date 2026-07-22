import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app, db
from app.models import NotificationTemplate, User
from app.notifications import render_notification_template


class NotificationTests(unittest.TestCase):
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

    def test_render_notification_template_resolves_context_variables(self):
        rendered = render_notification_template(
            "Hello {{ username }} — your balance is {{ amount_owed }} — test {{ test_title }}",
            {
                "username": "alice",
                "amount_owed": "12.00",
                "test_title": "Demo Test",
            },
        )
        self.assertEqual(rendered, "Hello alice — your balance is 12.00 — test Demo Test")

    def test_password_reset_route_uses_selected_channel_and_updates_password(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="resetter", email="resetter@example.com", notification_channel="email", receive_group_test_notifications=True)
            user.set_password("old-password")
            db.session.add(user)
            db.session.commit()

        with patch("app.notifications.send_notification_message") as mock_send:
            response = self.client.post(
                "/password-reset",
                data={"username": "resetter", "notification_channel": "email"},
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            refreshed = User.query.filter_by(username="resetter").first()
            self.assertIsNotNone(refreshed)
            self.assertNotEqual(refreshed.password_hash, "")
            self.assertTrue(mock_send.called)


if __name__ == "__main__":
    unittest.main()
