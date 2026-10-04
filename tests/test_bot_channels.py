"""Tests for the provider-neutral channel registry (bot architecture Phase 1)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app, db
from app.bot_channels import (
    CHANNEL_NAMES,
    chat_channels,
    configured_status,
    entitlement_for,
    is_configured,
)
from app.models import NotificationConfig, User
from app.notifications import send_notification_message


class ChannelRegistryTests(unittest.TestCase):
    def test_channel_names_are_the_known_set(self):
        self.assertEqual(CHANNEL_NAMES, ("email", "telegram", "discord", "root"))

    def test_chat_channels_excludes_email_and_keeps_order(self):
        self.assertEqual(chat_channels(), ("telegram", "discord", "root"))

    def test_email_requires_every_mailjet_credential(self):
        complete = {
            "mailjet_api_key": "key",
            "mailjet_secret_key": "secret",
            "mailjet_sender_email": "sender@example.com",
        }
        self.assertTrue(is_configured("email", complete))
        for missing in complete:
            partial = {k: v for k, v in complete.items() if k != missing}
            self.assertFalse(is_configured("email", partial), missing)

    def test_telegram_requires_only_its_bot_token(self):
        self.assertTrue(is_configured("telegram", {"telegram_bot_token": "123:ABC"}))
        self.assertFalse(is_configured("telegram", {}))

    def test_discord_is_configured_by_token_or_webhook(self):
        self.assertTrue(is_configured("discord", {"discord_bot_token": "123:ABC"}))
        self.assertTrue(is_configured("discord", {"discord_webhook_url": "https://discord.example/hook"}))
        self.assertFalse(is_configured("discord", {}))

    def test_blank_values_do_not_count_as_configured(self):
        self.assertFalse(is_configured("discord", {"discord_bot_token": "   "}))
        self.assertFalse(is_configured("root", {"root_webhook_url": ""}))

    def test_root_requires_its_bridge_credentials_and_a_status_channel(self):
        configured = {
            "root_bridge_key_id": "root-abc123",
            "root_bridge_secret": "s" * 64,
            "root_status_channel_id": "0198ac00-0000-7000-8000-000000000000",
        }
        self.assertTrue(is_configured("root", configured))
        for missing in configured:
            partial = {k: v for k, v in configured.items() if k != missing}
            self.assertFalse(is_configured("root", partial), missing)

    def test_root_is_not_configured_by_the_retired_webhook_key(self):
        self.assertFalse(is_configured("root", {"root_webhook_url": "https://root.example/webhook"}))

    def test_unknown_channel_is_never_configured(self):
        self.assertFalse(is_configured("carrier-pigeon", {"carrier_pigeon_token": "x"}))

    def test_configured_status_preserves_the_admin_settings_keys(self):
        status = configured_status({"telegram_bot_token": "123:ABC"}, ("email", "telegram", "discord"))
        self.assertEqual(status, {"email": False, "telegram": True, "discord": False})

    def test_configured_status_preserves_the_bots_page_keys(self):
        status = configured_status(
            {
                "root_bridge_key_id": "root-abc123",
                "root_bridge_secret": "s" * 64,
                "root_status_channel_id": "chan-1",
            },
            chat_channels(),
        )
        self.assertEqual(sorted(status), ["discord", "root", "telegram"])
        self.assertTrue(status["root"])
        self.assertFalse(status["telegram"])

    def test_root_and_discord_are_the_entitlement_gated_channels(self):
        self.assertEqual(entitlement_for("discord"), "discord_bot")
        self.assertIsNone(entitlement_for("telegram"))
        self.assertIsNone(entitlement_for("email"))
        self.assertIsNone(entitlement_for("unknown"))

    def test_root_rides_the_discord_entitlement(self):
        """Root is not a separately-sold key, so a Core + Discord tenant can configure it."""
        self.assertEqual(entitlement_for("root"), "discord_bot")
        self.assertEqual(entitlement_for("root"), entitlement_for("discord"))


class NotificationDeliveryRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path}",
            "NOTIFICATION_LOG_PATH": str(Path(self.temp_dir.name) / "notification.log"),
        })

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def _user(self):
        return User(username="member", email="member@example.com", telegram_user_id="11")

    def test_each_channel_routes_to_its_own_transport(self):
        # Root is deliberately absent: it cannot DM a member, so it has no per-user
        # transport. tests.test_notifications pins that refusal instead.
        cases = {
            "telegram": "send_telegram_message",
            "discord": "send_discord_message",
        }
        for channel, transport in cases.items():
            with self.subTest(channel=channel), self.app.app_context():
                db.create_all()
                with patch(f"app.notifications.{transport}", return_value=True) as mock_send, \
                        patch("app.notifications.send_mailjet_message") as mock_mail:
                    self.assertTrue(send_notification_message(self._user(), channel, "Subject", "Body"))

                self.assertEqual(mock_send.call_count, 1)
                mock_mail.assert_not_called()

    def test_email_channel_calls_mailjet_directly_without_a_fallback_log(self):
        with self.app.app_context():
            db.create_all()
            with patch("app.notifications.send_mailjet_message", return_value=True) as mock_mail, \
                    patch("app.notifications.append_notification_log") as mock_log:
                self.assertTrue(send_notification_message(self._user(), "email", "Subject", "Body"))

        self.assertEqual(mock_mail.call_count, 1)
        mock_log.assert_not_called()

    def test_every_chat_channel_falls_back_to_email_once_on_failure(self):
        # Root is absent for the same reason as above: it has no per-user transport,
        # so its email fallback is pinned in tests.test_notifications.
        transports = {
            "telegram": "send_telegram_message",
            "discord": "send_discord_message",
        }
        for channel, transport in transports.items():
            with self.subTest(channel=channel), self.app.app_context():
                db.create_all()
                with patch(f"app.notifications.{transport}", return_value=False) as mock_send, \
                        patch("app.notifications.send_mailjet_message", return_value=True) as mock_mail, \
                        patch("app.notifications.append_notification_log") as mock_log:
                    self.assertTrue(send_notification_message(self._user(), channel, "Subject", "Body"))

                self.assertEqual(mock_send.call_count, 1, "chat transport must not be retried inline")
                self.assertEqual(mock_mail.call_count, 1)
                logged = [call.args[0] for call in mock_log.call_args_list]
                self.assertEqual(
                    [line for line in logged if line.endswith(": falling back to email for member")],
                    [f"{channel}: falling back to email for member"],
                )

    def test_unknown_channel_goes_straight_to_email(self):
        with self.app.app_context():
            db.create_all()
            with patch("app.notifications.send_mailjet_message", return_value=True) as mock_mail, \
                    patch("app.notifications.append_notification_log") as mock_log:
                self.assertTrue(send_notification_message(self._user(), "carrier-pigeon", "Subject", "Body"))

        self.assertEqual(mock_mail.call_count, 1)
        mock_log.assert_not_called()

    def test_delivery_fails_when_both_the_channel_and_email_fail(self):
        with self.app.app_context():
            db.create_all()
            with patch("app.notifications.send_telegram_message", return_value=False), \
                    patch("app.notifications.send_mailjet_message", return_value=False):
                self.assertFalse(
                    send_notification_message(self._user(), "telegram", "Subject", "Body")
                )


if __name__ == "__main__":
    unittest.main()
