import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import create_app, db
from app.models import NotificationConfig, NotificationTemplate, User
from app.notifications import append_notification_log, read_notification_log, render_notification_template, send_mailjet_message, send_telegram_message


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
            user = User(username="resetter", email="resetter@example.com", notification_channel="telegram", receive_group_test_notifications=True)
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
            self.assertEqual(mock_send.call_args.args[1], "email")

    def test_notification_log_writes_and_prunes(self):
        with self.app.app_context():
            log_path = append_notification_log("initial entry")
            self.assertTrue(Path(log_path).exists())
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write("x" * 300000)

            append_notification_log("post-prune entry")
            contents = read_notification_log()

            self.assertIn("post-prune entry", contents)
            self.assertLess(len(contents), 400000)

    def test_edit_notification_template_updates_existing_template(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            template = NotificationTemplate(name="Old Template", email_subject="Old", email_body="Old body")
            db.session.add(template)
            db.session.commit()
            template_id = template.id

        self.client.post(
            "/login",
            data={"username": "admin", "password": "secret"},
            follow_redirects=True,
        )

        response = self.client.post(
            f"/admin/notification-templates/{template_id}/edit",
            data={
                "name": "Updated Template",
                "description": "Updated description",
                "email_subject": "Updated subject",
                "email_body": "Updated body",
                "telegram_body": "Updated telegram",
                "hide_from_participant_notifications": False,
                "is_default_password_reset": False,
                "is_active": True,
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            refreshed = NotificationTemplate.query.get(template_id)
            self.assertEqual(refreshed.name, "Updated Template")
            self.assertEqual(refreshed.email_subject, "Updated subject")
            self.assertEqual(refreshed.email_body, "Updated body")

    def test_debug_logging_toggle_persists_and_writes_debug_entries(self):
        with self.app.app_context():
            db.create_all()
            db.session.add(NotificationConfig(key="notification_debug_enabled", value="true"))
            db.session.commit()
            append_notification_log("debug-only entry", debug=True)
            contents = read_notification_log()

        self.assertIn("debug-only entry", contents)

    def test_send_mailjet_message_posts_to_mailjet_api(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="mailer", email="mailer@example.com")
            user.set_password("secret")
            db.session.add(user)
            db.session.add_all([
                NotificationConfig(key="mailjet_api_key", value="api-key"),
                NotificationConfig(key="mailjet_secret_key", value="secret-key"),
                NotificationConfig(key="mailjet_sender_email", value="sender@example.com"),
            ])
            db.session.commit()

            with patch("app.notifications.urlopen") as mock_urlopen:
                response = Mock()
                response.read.return_value = b'{"message":"success"}'
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                mock_urlopen.return_value = response

                result = send_mailjet_message(user, "Hello", "Body")

        self.assertTrue(result)
        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.mailjet.com/v3.1/send")

    def test_send_telegram_message_posts_to_telegram_api(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="telegramer", email="telegramer@example.com", tg_username="demo")
            user.set_password("secret")
            db.session.add(user)
            db.session.add(NotificationConfig(key="telegram_bot_token", value="123456:ABC"))
            db.session.commit()

            with patch("app.notifications.urlopen") as mock_urlopen:
                response = Mock()
                response.read.return_value = b'{"ok":true}'
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                mock_urlopen.return_value = response

                result = send_telegram_message(user, "Body")

        self.assertTrue(result)
        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args.args[0]
        self.assertIn("https://api.telegram.org/bot123456%3AABC/sendMessage", request.full_url)
        self.assertIn("chat_id=%40demo", request.full_url)


if __name__ == "__main__":
    unittest.main()
