import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from sqlalchemy.exc import IntegrityError

from app import create_app, db
from app.models import GroupTest, NotificationConfig, NotificationTemplate, Participation, PublicResult, TelegramStatusDigestEvent, User, UserDigestEvent
from app.notifications import append_notification_log, read_notification_log, render_notification_template, send_mailjet_message, send_notification_message, send_telegram_message, send_telegram_status_channel_message


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.log_path = Path(self.temp_dir.name) / "notification.log"
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path}",
            "NOTIFICATION_LOG_PATH": str(self.log_path),
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

    def test_password_reset_route_requires_linked_chat_for_telegram(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="reset_tg", email="reset_tg@example.com", notification_channel="telegram")
            user.set_password("old-password")
            db.session.add(user)
            db.session.commit()

        response = self.client.post(
            "/password-reset",
            data={"username": "reset_tg", "notification_channel": "telegram"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("open the bot and press Start", response.get_data(as_text=True))

    def test_register_route_sends_welcome_email_with_login_link(self):
        with self.app.app_context():
            db.create_all()
            db.session.add(NotificationConfig(key="service_base_url", value="https://example.test"))
            db.session.commit()

        with patch("app.routes.send_notification_message", return_value=True) as mock_send:
            response = self.client.post(
                "/register",
                data={
                    "username": "newuser",
                    "email": "new@example.com",
                    "password": "secretpass",
                    "confirm_password": "secretpass",
                    "tg_username": "",
                },
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(mock_send.called)
        self.assertEqual(mock_send.call_args.args[1], "email")
        self.assertIn("newuser", mock_send.call_args.args[3])
        self.assertIn("https://example.test/login", mock_send.call_args.args[3])

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

    def test_notification_log_sanitizes_leading_junk(self):
        with self.app.app_context():
            log_path = append_notification_log("clean entry")
            with open(log_path, "w", encoding="utf-8") as handle:
                handle.write("x" * 2000)
                handle.write("\n[2026-01-01 00:00:00] restored entry\n")

            contents = read_notification_log()

            self.assertTrue(contents.startswith("["))
            self.assertIn("restored entry", contents)
            self.assertNotIn("x" * 100, contents)

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

    def test_send_mailjet_message_treats_error_messages_as_failure(self):
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
                response.read.return_value = b'{"Messages":[{"Status":"error","Errors":[{"ErrorMessage":"invalid address"}]}]}'
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                mock_urlopen.return_value = response

                result = send_mailjet_message(user, "Hello", "Body")

        self.assertFalse(result)

    def test_send_mailjet_message_debug_logs_full_response_when_enabled(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="mailer", email="mailer@example.com")
            user.set_password("secret")
            db.session.add(user)
            db.session.add_all([
                NotificationConfig(key="mailjet_api_key", value="api-key"),
                NotificationConfig(key="mailjet_secret_key", value="secret-key"),
                NotificationConfig(key="mailjet_sender_email", value="sender@example.com"),
                NotificationConfig(key="notification_debug_enabled", value="true"),
            ])
            db.session.commit()

            with patch("app.notifications.urlopen") as mock_urlopen:
                response = Mock()
                response.read.return_value = b'{"Messages":[{"Status":"error","Errors":[{"ErrorMessage":"invalid address"}]}]}'
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                mock_urlopen.return_value = response

                send_mailjet_message(user, "Hello", "Body")

        with self.app.app_context():
            log_contents = read_notification_log()

        self.assertIn("mailjet: response", log_contents)
        self.assertIn("invalid address", log_contents)

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
        self.assertEqual(request.data, b'{"chat_id": "@demo", "text": "Body"}')

    def test_send_telegram_message_treats_failed_bot_api_response_as_failure(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="telegramer", email="telegramer@example.com", tg_username="demo")
            user.set_password("secret")
            db.session.add(user)
            db.session.add(NotificationConfig(key="telegram_bot_token", value="123456:ABC"))
            db.session.commit()

            with patch("app.notifications.urlopen") as mock_urlopen:
                response = Mock()
                response.read.return_value = b'{"ok":false,"error_code":400,"description":"Bad Request: chat not found"}'
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                mock_urlopen.return_value = response

                result = send_telegram_message(user, "Body")

        self.assertFalse(result)

    def test_send_telegram_message_debug_logs_request_and_response_details(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="telegramer", email="telegramer@example.com", tg_username="demo")
            user.set_password("secret")
            db.session.add(user)
            db.session.add_all([
                NotificationConfig(key="telegram_bot_token", value="123456:ABC"),
                NotificationConfig(key="notification_debug_enabled", value="true"),
            ])
            db.session.commit()

            with patch("app.notifications.urlopen") as mock_urlopen:
                response = Mock()
                response.read.return_value = b'{"ok":true,"result":{"message_id":1}}'
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                mock_urlopen.return_value = response

                send_telegram_message(user, "Body")

        with self.app.app_context():
            log_contents = read_notification_log()

        self.assertIn("telegram: request", log_contents)
        self.assertIn('"chat_id": "@demo"', log_contents)
        self.assertIn("telegram: response", log_contents)
        self.assertIn("\"ok\": true", log_contents)

    def test_send_telegram_status_channel_message_includes_message_thread_id_suffix(self):
        with self.app.app_context():
            db.create_all()
            db.session.add_all([
                NotificationConfig(key="telegram_bot_token", value="123456:ABC"),
                NotificationConfig(key="telegram_status_chat_id", value="-1003638912415_2 "),
            ])
            db.session.commit()

            with patch("app.notifications.urlopen") as mock_urlopen:
                response = Mock()
                response.read.return_value = b'{"ok":true}'
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                mock_urlopen.return_value = response

                result = send_telegram_status_channel_message("Thread message")

        self.assertTrue(result)
        request = mock_urlopen.call_args.args[0]
        self.assertIn(b'"chat_id": "-1003638912415"', request.data)
        self.assertIn(b'"message_thread_id": 2', request.data)

    def test_send_telegram_status_channel_message_without_thread_suffix_uses_chat_only(self):
        with self.app.app_context():
            db.create_all()
            db.session.add_all([
                NotificationConfig(key="telegram_bot_token", value="123456:ABC"),
                NotificationConfig(key="telegram_status_chat_id", value="-1003638912415"),
            ])
            db.session.commit()

            with patch("app.notifications.urlopen") as mock_urlopen:
                response = Mock()
                response.read.return_value = b'{"ok":true}'
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                mock_urlopen.return_value = response

                result = send_telegram_status_channel_message("No thread")

        self.assertTrue(result)
        request = mock_urlopen.call_args.args[0]
        self.assertIn(b'"chat_id": "-1003638912415"', request.data)
        self.assertNotIn(b'"message_thread_id"', request.data)

    def test_send_notification_message_falls_back_to_email_when_telegram_requires_start(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="fallbacker", email="fallbacker@example.com", notification_channel="telegram")
            user.set_password("secret")
            db.session.add(user)
            db.session.add_all([
                NotificationConfig(key="mailjet_api_key", value="api-key"),
                NotificationConfig(key="mailjet_secret_key", value="secret-key"),
                NotificationConfig(key="mailjet_sender_email", value="sender@example.com"),
            ])
            db.session.commit()

            with patch("app.notifications.send_telegram_message", return_value=False) as mock_telegram, \
                 patch("app.notifications.send_mailjet_message", return_value=True) as mock_mailjet:
                result = send_notification_message(user, "telegram", "Reset", "Body")

        self.assertTrue(result)
        mock_telegram.assert_called_once()
        mock_mailjet.assert_called_once()

    def test_status_digest_event_persists_and_marks_sent(self):
        with self.app.app_context():
            from app.routes import _send_status_update_to_telegram

            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            member = User(username="member", email="member@example.com", tg_username="membername", telegram_user_id="111")
            member.set_password("secret")
            db.session.add_all([admin, member])
            db.session.flush()

            test = GroupTest(title="Digest Test", status="testing", created_by=admin.id)
            db.session.add(test)
            db.session.flush()

            participation = Participation(group_test_id=test.id, user_id=member.id, approved=True, denied=False, name="Member")
            db.session.add(participation)
            db.session.add(NotificationConfig(key="telegram_status_chat_id", value="-10012345"))
            db.session.add(NotificationConfig(key="telegram_digest_enabled", value="true"))
            db.session.add(NotificationConfig(key="telegram_digest_window_minutes", value="10"))
            db.session.commit()

            with patch("app.routes.send_telegram_status_channel_message", return_value=True) as mock_sender:
                _send_status_update_to_telegram(test, "recruiting")
                test.status = "closed"
                _send_status_update_to_telegram(test, "testing")
                db.session.commit()

            self.assertTrue(mock_sender.called)
            events = TelegramStatusDigestEvent.query.all()
            self.assertEqual(len(events), 2)
            self.assertTrue(all(event.sent_at is not None for event in events))

    def test_status_digest_suppresses_duplicate_event_key_in_same_window(self):
        with self.app.app_context():
            from app.routes import _send_status_update_to_telegram

            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.flush()

            test = GroupTest(title="Digest Duplicate Test", status="testing", created_by=admin.id)
            db.session.add(test)
            db.session.add(NotificationConfig(key="telegram_status_chat_id", value="-10012345"))
            db.session.add(NotificationConfig(key="telegram_digest_enabled", value="true"))
            db.session.add(NotificationConfig(key="telegram_digest_window_minutes", value="10"))
            db.session.commit()

            with patch("app.routes.send_telegram_status_channel_message", return_value=True):
                _send_status_update_to_telegram(test, "recruiting")
                _send_status_update_to_telegram(test, "recruiting")
                db.session.commit()

            events = TelegramStatusDigestEvent.query.all()
            self.assertEqual(len(events), 1)

    def test_status_digest_formats_ready_for_payment_label(self):
        with self.app.app_context():
            from app.routes import _send_status_update_to_telegram

            db.create_all()
            admin = User(username="admin-ready", email="admin-ready@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.flush()

            test = GroupTest(title="Ready Label Test", status="ready_for_payment", created_by=admin.id)
            db.session.add(test)
            db.session.add(NotificationConfig(key="telegram_status_chat_id", value="-10012345"))
            db.session.add(NotificationConfig(key="telegram_digest_enabled", value="false"))
            db.session.commit()

            with patch("app.routes.send_telegram_status_channel_message", return_value=True) as mock_sender:
                _send_status_update_to_telegram(test, "testing")

            self.assertTrue(mock_sender.called)
            sent_body = mock_sender.call_args.args[0]
            self.assertIn("Ready Label Test is now ready for payment", sent_body)

    def test_status_digest_uses_custom_config_templates(self):
        with self.app.app_context():
            from app.routes import _send_status_update_to_telegram

            db.create_all()
            admin = User(username="admin-digest-custom", email="admin-digest-custom@example.com", is_admin=True)
            admin.set_password("secret")
            member = User(username="member-digest-custom", email="member-digest-custom@example.com", tg_username="custommember", telegram_user_id="321")
            member.set_password("secret")
            db.session.add_all([admin, member])
            db.session.flush()

            test = GroupTest(title="Custom Digest Test", status="ready_for_payment", created_by=admin.id)
            db.session.add(test)
            db.session.flush()
            db.session.add(Participation(group_test_id=test.id, user_id=member.id, approved=True, denied=False, name="Member"))

            db.session.add_all([
                NotificationConfig(key="telegram_status_chat_id", value="-10012345"),
                NotificationConfig(key="telegram_digest_enabled", value="false"),
                NotificationConfig(key="telegram_status_digest_header_template", value="Digest Header: {{ new_status_label }}"),
                NotificationConfig(key="telegram_status_digest_line_template", value="{{ test_title }} => {{ new_status }}"),
                NotificationConfig(key="telegram_status_digest_participants_template", value="Mentions: {{ mentions }}"),
            ])
            db.session.commit()

            with patch("app.routes.send_telegram_status_channel_message", return_value=True) as mock_sender:
                _send_status_update_to_telegram(test, "testing")

            self.assertTrue(mock_sender.called)
            sent_body = mock_sender.call_args.args[0]
            self.assertIn("Digest Header: Ready For Payment", sent_body)
            self.assertIn("Custom Digest Test => ready_for_payment", sent_body)
            self.assertIn("Mentions:", sent_body)

    def test_status_digest_excludes_denied_participants_from_mentions(self):
        with self.app.app_context():
            from app.routes import _send_status_update_to_telegram

            db.create_all()
            admin = User(username="admin-deny-mention", email="admin-deny-mention@example.com", is_admin=True)
            admin.set_password("secret")
            member = User(
                username="member-deny-mention",
                email="member-deny-mention@example.com",
                tg_username="denyme",
                telegram_user_id="987654",
            )
            member.set_password("secret")
            db.session.add_all([admin, member])
            db.session.flush()

            test = GroupTest(title="Denied Mention Test", status="testing", created_by=admin.id)
            db.session.add(test)
            db.session.flush()

            participation = Participation(
                group_test_id=test.id,
                user_id=member.id,
                approved=True,
                denied=False,
                name="Member",
            )
            db.session.add(participation)
            db.session.add(NotificationConfig(key="telegram_status_chat_id", value="-10012345"))
            db.session.add(NotificationConfig(key="telegram_digest_enabled", value="true"))
            db.session.add(NotificationConfig(key="telegram_digest_window_minutes", value="10"))
            db.session.commit()

            with patch("app.routes.send_telegram_status_channel_message", return_value=True) as mock_sender:
                _send_status_update_to_telegram(test, "recruiting")
                self.assertFalse(mock_sender.called)

                participation.denied = True
                test.status = "closed"
                _send_status_update_to_telegram(test, "testing")

            self.assertTrue(mock_sender.called)
            sent_body = mock_sender.call_args.args[0]
            self.assertNotIn("@denyme", sent_body)
            self.assertNotIn("tg://user?id=987654", sent_body)

    def test_telegram_status_summary_uses_custom_approved_template(self):
        with self.app.app_context():
            from app.routes import _telegram_status_summary_for_user

            db.create_all()
            user = User(username="member-status-template", email="member-status-template@example.com")
            user.set_password("secret")
            admin = User(username="admin-status-template", email="admin-status-template@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add_all([user, admin])
            db.session.flush()

            test = GroupTest(title="Template Status Test", status="testing", created_by=admin.id)
            db.session.add(test)
            db.session.flush()

            db.session.add(Participation(
                group_test_id=test.id,
                user_id=user.id,
                approved=True,
                denied=False,
                order_status="ordered_from_vendor",
                amount_owed=45.5,
                amount_paid=10.0,
                name="Member",
            ))
            db.session.add(NotificationConfig(
                key="telegram_status_user_approved_template",
                value="Status {{ test_title }} | {{ order_status }} | owed={{ amount_owed }} | paid={{ amount_paid }}",
            ))
            db.session.commit()

            text = _telegram_status_summary_for_user(user, test)

        self.assertIn("Status Template Status Test | ordered_from_vendor | owed=45.50 | paid=10.00", text)

    def test_status_digest_duplicate_insert_race_is_ignored(self):
        with self.app.app_context():
            from app.routes import _send_status_update_to_telegram

            db.create_all()
            admin = User(username="admin-race", email="admin-race@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.flush()

            test = GroupTest(title="Digest Race Test", status="testing", created_by=admin.id)
            db.session.add(test)
            db.session.add(NotificationConfig(key="telegram_status_chat_id", value="-10012345"))
            db.session.add(NotificationConfig(key="telegram_digest_enabled", value="true"))
            db.session.add(NotificationConfig(key="telegram_digest_window_minutes", value="10"))
            db.session.commit()

            with patch(
                "app.routes.db.session.flush",
                side_effect=IntegrityError("INSERT", {"event_key": "x"}, Exception("duplicate")),
            ):
                _send_status_update_to_telegram(test, "recruiting")

            db.session.commit()
            events = TelegramStatusDigestEvent.query.all()
            self.assertEqual(len(events), 0)

    def test_send_due_user_digests_hourly_dispatches_and_marks_events_sent(self):
        with self.app.app_context():
            from app.notifications import send_due_user_digests

            db.create_all()
            user = User(
                username="digest_hourly",
                email="digest_hourly@example.com",
                digest_frequency="hourly",
                digest_hourly_minute_utc=0,
                receive_group_test_notifications=True,
                is_active=True,
            )
            user.set_password("secret")
            db.session.add(user)
            db.session.flush()

            db.session.add_all([
                UserDigestEvent(user_id=user.id, test_id=1, test_title="One", old_status="recruiting", new_status="testing"),
                UserDigestEvent(user_id=user.id, test_id=2, test_title="Two", old_status="testing", new_status="closed"),
            ])
            db.session.commit()

            now = datetime(2026, 8, 31, 12, 5, 0)
            with patch("app.notifications.send_mailjet_message", return_value=True) as mock_mail:
                result = send_due_user_digests(now=now)

            self.assertEqual(result["users"], 1)
            self.assertEqual(result["events"], 2)
            self.assertTrue(mock_mail.called)

            pending = UserDigestEvent.query.filter_by(user_id=user.id, sent_at=None).count()
            self.assertEqual(pending, 0)
            refreshed = User.query.get(user.id)
            self.assertEqual(refreshed.digest_last_sent_at, now)

    def test_send_due_user_digests_daily_not_due_skips_user(self):
        with self.app.app_context():
            from app.notifications import send_due_user_digests

            db.create_all()
            user = User(
                username="digest_daily",
                email="digest_daily@example.com",
                digest_frequency="daily",
                digest_daily_hour_utc=22,
                digest_last_sent_at=datetime(2026, 8, 31, 22, 0, 0),
                receive_group_test_notifications=True,
                is_active=True,
            )
            user.set_password("secret")
            db.session.add(user)
            db.session.flush()

            db.session.add(UserDigestEvent(user_id=user.id, test_id=3, test_title="Three", old_status="recruiting", new_status="testing"))
            db.session.commit()

            now = datetime(2026, 8, 31, 22, 30, 0)
            with patch("app.notifications.send_mailjet_message", return_value=True) as mock_mail:
                result = send_due_user_digests(now=now)

            self.assertEqual(result["users"], 0)
            self.assertEqual(result["events"], 0)
            self.assertFalse(mock_mail.called)

            pending = UserDigestEvent.query.filter_by(user_id=user.id, sent_at=None).count()
            self.assertEqual(pending, 1)

    def test_group_test_notifications_use_each_participants_amount(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            member_one = User(username="member1", email="member1@example.com")
            member_one.set_password("secret")
            member_two = User(username="member2", email="member2@example.com")
            member_two.set_password("secret")
            test = GroupTest(title="Notify Test", status="closed", created_by=1, results_link="https://example.test/results")
            template = NotificationTemplate(name="Notify Template", email_subject="Hi {{ username }}", email_body="Owed {{ amount_owed }} on {{ test_title }}")
            db.session.add_all([admin, member_one, member_two, test, template])
            db.session.flush()
            db.session.add_all([
                Participation(group_test_id=test.id, user_id=member_one.id, approved=True, amount_owed=12.5),
                Participation(group_test_id=test.id, user_id=member_two.id, approved=True, amount_owed=15.0),
            ])
            db.session.commit()
            test_id = test.id
            template_id = template.id

        self.client.post(
            "/login",
            data={"username": "admin", "password": "secret"},
            follow_redirects=True,
        )

        with patch("app.routes.send_group_test_notification") as mock_send:
            response = self.client.post(
                f"/test/{test_id}",
                data={"template_id": template_id},
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_send.call_count, 2)
        self.assertEqual(mock_send.call_args_list[0].kwargs["amount_owed"], 12.5)
        self.assertEqual(mock_send.call_args_list[1].kwargs["amount_owed"], 15.0)

    def test_admin_can_edit_public_result_and_tags(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin-public", email="admin-public@example.com", is_admin=True)
            admin.set_password("secret")
            result = PublicResult(
                title="Original Title",
                summary="Original summary",
                results_link="https://example.test/original",
                created_by=1,
            )
            db.session.add_all([admin, result])
            db.session.commit()
            result_id = result.id

        self.client.post(
            "/login",
            data={"username": "admin-public", "password": "secret"},
            follow_redirects=True,
        )

        response = self.client.post(
            f"/admin/public-results/{result_id}/edit",
            data={
                "title": "Updated Title",
                "summary": "Updated summary",
                "results_link": "https://example.test/updated",
                "tag_names": "tirz, Shed GB#3",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            refreshed = PublicResult.query.get(result_id)
            self.assertEqual(refreshed.title, "Updated Title")
            self.assertEqual(refreshed.summary, "Updated summary")
            self.assertEqual(refreshed.results_link, "https://example.test/updated")
            self.assertEqual([tag.name for tag in refreshed.tags], ["Shed GB#3", "tirz"])

    def test_admin_can_store_itemized_public_result_rows(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin-public-items", email="admin-public-items@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.commit()

        self.client.post(
            "/login",
            data={"username": "admin-public-items", "password": "secret"},
            follow_redirects=True,
        )

        response = self.client.post(
            "/admin/public-results",
            data={
                "title": "Public Result With Items",
                "summary": "Summary",
                "results_link": "https://example.test/public-result",
                "tag_names": "tirz",
                "result_item_name": ["MASS", "STERILITY"],
                "result_item_value": ["98.7% purity", "Pass"],
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            result = PublicResult.query.filter_by(title="Public Result With Items").first()
            self.assertIsNotNone(result)
            self.assertEqual(result.item_results, [
                {"name": "MASS", "result": "98.7% purity"},
                {"name": "STERILITY", "result": "Pass"},
            ])


if __name__ == "__main__":
    unittest.main()
