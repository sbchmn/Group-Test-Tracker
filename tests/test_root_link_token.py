"""Root account-link token issuance (M2) and bot link/notification-channel gating."""

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app import create_app, db
from app.bot_channels import (
    available_notification_channel_choices,
    channel_available,
    channel_link_available,
    notification_channel_choices,
)
from app.models import BotLinkToken, NotificationConfig, RESERVED_SUPPORT_SYSTEM_KEY, User

ROOT_CONFIG = [
    ("root_bridge_key_id", "root-abc123"),
    ("root_bridge_secret", "s" * 64),
    ("root_status_channel_id", "chan-1"),
]


class RootLinkTokenTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp_dir.cleanup)
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{Path(self.temp_dir.name) / 'test.db'}",
            "NOTIFICATION_LOG_PATH": str(Path(self.temp_dir.name) / "notification.log"),
        })
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    @contextmanager
    def _managed_without_discord(self):
        with patch.dict(os.environ, {
            "GTT_DEPLOYMENT_MODE": "managed",
            "GTT_ENTITLEMENTS": "telegram",
        }, clear=False):
            yield

    def _configure(self, *pairs):
        with self.app.app_context():
            for key, value in pairs:
                row = NotificationConfig.query.filter_by(key=key).first()
                if row is None:
                    db.session.add(NotificationConfig(key=key, value=value))
                else:
                    row.value = value
            db.session.commit()

    def _member(self, username="member", **columns):
        with self.app.app_context():
            user = User(username=username, email=f"{username}@example.test", **columns)
            user.set_password("secret")
            db.session.add(user)
            db.session.commit()
            return user.id

    def _login(self, username="member"):
        return self.client.post("/login", data={"username": username, "password": "secret"})

    def _root_config(self):
        self._configure(*ROOT_CONFIG)

    # --- registry predicates -------------------------------------------------

    def test_root_is_available_but_never_a_personal_channel(self):
        self._root_config()
        with self.app.app_context():
            configs = {c.key: c.value for c in NotificationConfig.query.all()}
            self.assertTrue(channel_available("root", configs))
            self.assertTrue(channel_link_available("root", configs))
            self.assertNotIn("root", [name for name, _ in notification_channel_choices()])

    def test_choices_exclude_broadcast_only_transports(self):
        self.assertEqual(
            notification_channel_choices(),
            [("email", "Email"), ("telegram", "Telegram"), ("discord", "Discord")],
        )

    def test_unconfigured_channels_are_hidden_and_configured_ones_shown(self):
        with self.app.app_context():
            configs = {c.key: c.value for c in NotificationConfig.query.all()}
            self.assertEqual([n for n, _ in available_notification_channel_choices(configs)], ["email"])

        self._configure(("telegram_bot_token", "123:ABC"), ("discord_bot_token", "123:ABC"))
        with self.app.app_context():
            configs = {c.key: c.value for c in NotificationConfig.query.all()}
            self.assertEqual(
                [n for n, _ in available_notification_channel_choices(configs)],
                ["email", "telegram", "discord"],
            )

    def test_de_entitled_channels_are_hidden_in_managed_mode(self):
        self._configure(("telegram_bot_token", "123:ABC"), ("discord_bot_token", "123:ABC"))
        with self._managed_without_discord():
            with self.app.app_context():
                configs = {c.key: c.value for c in NotificationConfig.query.all()}
                names = [n for n, _ in available_notification_channel_choices(configs)]
        self.assertEqual(names, ["email", "telegram"])

    def test_a_saved_channel_that_became_unavailable_is_still_listed(self):
        """Otherwise the member could not save their profile at all."""
        with self.app.app_context():
            choices = available_notification_channel_choices(
                {c.key: c.value for c in NotificationConfig.query.all()}, current="sms")
        self.assertIn(("sms", "sms (not available)"), choices)

    def test_webhook_only_discord_can_broadcast_but_not_link(self):
        """Only the bot token runs the gateway worker that receives /start."""
        self._configure(("discord_webhook_url", "https://discord.example/hook"))
        with self.app.app_context():
            configs = {c.key: c.value for c in NotificationConfig.query.all()}
            self.assertTrue(channel_available("discord", configs))
            self.assertFalse(channel_link_available("discord", configs))

    # --- profile display gating ---------------------------------------------

    def test_root_link_section_hidden_when_unconfigured(self):
        self._member()
        self._login()

        page = self.client.get("/profile").get_data(as_text=True)

        self.assertNotIn("Root Link Status", page)
        self.assertNotIn("Generate Root Link", page)
        self.assertNotIn('value="root"', page)

    def test_all_link_sections_hidden_when_nothing_is_configured(self):
        self._member()
        self._login()

        page = self.client.get("/profile").get_data(as_text=True)

        for heading in ("Telegram Link Status", "Discord Link Status", "Root Link Status"):
            self.assertNotIn(heading, page)

    def test_root_link_section_shown_when_configured(self):
        self._root_config()
        self._member()
        self._login()

        page = self.client.get("/profile").get_data(as_text=True)

        self.assertIn("Root Link Status", page)
        self.assertIn("Generate Root Link", page)

    def test_webhook_only_discord_hides_the_link_section(self):
        self._configure(("discord_webhook_url", "https://discord.example/hook"))
        self._member()
        self._login()

        page = self.client.get("/profile").get_data(as_text=True)

        self.assertNotIn("Discord Link Status", page)

    def test_a_stored_root_token_is_not_surfaced_once_root_is_unconfigured(self):
        self._root_config()
        self._member()
        self._login()
        self.client.post("/profile/root-link-token", follow_redirects=True)
        with self.app.app_context():
            token_value = BotLinkToken.query.filter_by(provider="root").one().token
        self._configure(("root_bridge_secret", ""))

        page = self.client.get("/profile").get_data(as_text=True)

        self.assertNotIn("Root Link Status", page)
        self.assertNotIn(token_value, page)
        with self.app.app_context():
            self.assertEqual(
                BotLinkToken.query.filter(BotLinkToken.used_at.is_(None)).count(), 1,
                "hiding the section must not silently consume or destroy the token",
            )

    # --- route enforcement ---------------------------------------------------

    def test_root_link_token_is_issued_when_configured(self):
        self._root_config()
        self._member()
        self._login()

        response = self.client.post("/profile/root-link-token", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            token = BotLinkToken.query.filter_by(provider="root").one()
            self.assertEqual(len(token.token), 32)
            self.assertIsNone(token.used_at)
            value = token.token
        page = self.client.get("/profile").get_data(as_text=True)
        self.assertIn(f"/start {value}", page)

    def test_root_token_route_refuses_when_root_is_unconfigured(self):
        self._member()
        self._login()

        self.client.post("/profile/root-link-token", follow_redirects=True)

        with self.app.app_context():
            self.assertEqual(BotLinkToken.query.filter_by(provider="root").count(), 0)

    def test_telegram_token_route_refuses_when_no_bot_token(self):
        self._member()
        self._login()

        self.client.post("/profile/telegram-link-token", follow_redirects=True)

        with self.app.app_context():
            self.assertEqual(BotLinkToken.query.filter_by(provider="telegram").count(), 0)

    def test_root_token_is_scoped_to_the_root_provider(self):
        self._root_config()
        self._member()
        self._login()
        self.client.post("/profile/root-link-token")

        with self.app.app_context():
            rows = [(t.provider, t.user_id) for t in BotLinkToken.query.all()]
        self.assertEqual([p for p, _ in rows], ["root"])

    def test_reserved_support_accounts_cannot_mint_root_tokens(self):
        self._root_config()
        with self.app.app_context():
            support = User(
                username="svc",
                email="svc@example.test",
                system_account_key=RESERVED_SUPPORT_SYSTEM_KEY,
            )
            support.set_password("secret")
            db.session.add(support)
            db.session.commit()
        self.client.post("/login", data={"username": "svc", "password": "secret"})

        self.assertTrue(self.client.post("/profile/root-link-token", follow_redirects=True))
        with self.app.app_context():
            self.assertEqual(BotLinkToken.query.filter_by(provider="root").count(), 0)

    def test_anonymous_cannot_reach_the_root_token_route(self):
        response = self.client.post("/profile/root-link-token", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))


if __name__ == "__main__":
    unittest.main()
