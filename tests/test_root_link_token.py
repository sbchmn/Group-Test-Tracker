"""Tests for Root account-link token issuance (M2) and channel selection (M3)."""

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app import create_app, db
from app.bot_channels import (
    available_notification_channel_choices,
    notification_channel_choices,
)
from app.models import BotLinkToken, NotificationConfig, RESERVED_SUPPORT_SYSTEM_KEY, User


class RootLinkTokenTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp_dir.cleanup)
        db_path = Path(self.temp_dir.name) / "test.db"
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "NOTIFICATION_LOG_PATH": str(Path(self.temp_dir.name) / "notification.log"),
        })
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    @contextmanager
    def _managed_without_discord(self):
        with patch.dict(os.environ, {"GTT_DEPLOYMENT_MODE": "managed", "GTT_ENTITLEMENTS": ""}, clear=False):
            yield

    def _member(self, username="member", **columns):
        with self.app.app_context():
            user = User(username=username, email=f"{username}@example.test", **columns)
            user.set_password("secret")
            db.session.add(user)
            db.session.commit()
            return user.id

    def _login(self, username="member"):
        return self.client.post("/login", data={"username": username, "password": "secret"})

    def test_profile_does_not_offer_root_as_a_personal_channel(self):
        """Root is broadcast-only, so it must never be a member's Notify via option."""
        with self.app.app_context():
            db.session.add_all([
                NotificationConfig(key="root_bridge_key_id", value="root-abc123"),
                NotificationConfig(key="root_bridge_secret", value="s" * 64),
                NotificationConfig(key="root_status_channel_id", value="chan-1"),
            ])
            db.session.commit()
        self._member(root_user_id="already-linked")
        self._login()

        page = self.client.get("/profile").get_data(as_text=True)

        self.assertIn("value=\"email\"", page)
        self.assertNotIn('value="root"', page)
        # Linking is still per-user and still offered.
        self.assertIn("Root Link Status", page)

    def test_choices_exclude_broadcast_only_transports(self):
        self.assertEqual(
            notification_channel_choices(),
            [("email", "Email"), ("telegram", "Telegram"), ("discord", "Discord")],
        )

    def test_unconfigured_and_de_entitled_channels_are_hidden(self):
        with self.app.app_context():
            configs = {c.key: c.value for c in NotificationConfig.query.all()}
            choices = available_notification_channel_choices(configs)
        self.assertEqual([name for name, _ in choices], ["email"])

        with self.app.app_context():
            db.session.add_all([
                NotificationConfig(key="telegram_bot_token", value="123:ABC"),
                NotificationConfig(key="discord_bot_token", value="123:ABC"),
            ])
            db.session.commit()
            configs = {c.key: c.value for c in NotificationConfig.query.all()}
            names = [name for name, _ in available_notification_channel_choices(configs)]
        self.assertEqual(names, ["email", "telegram", "discord"])

        with self._managed_without_discord():
            with self.app.app_context():
                configs = {c.key: c.value for c in NotificationConfig.query.all()}
                names = [name for name, _ in available_notification_channel_choices(configs)]
        self.assertEqual(names, ["email", "telegram"])

    def test_a_saved_channel_that_became_unavailable_is_still_listed(self):
        """Otherwise the member could not save their profile at all."""
        with self.app.app_context():
            choices = available_notification_channel_choices(
                {c.key: c.value for c in NotificationConfig.query.all()}, current="sms")
        self.assertIn(("sms", "sms (not available)"), choices)

    def test_root_link_token_is_issued_and_offered_on_the_profile(self):
        self._member()
        self._login()

        response = self.client.post("/profile/root-link-token", follow_redirects=False)
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            token = BotLinkToken.query.filter_by(provider="root").one()
            value = token.token
        self.assertEqual(len(value), 32)
        self.assertIsNone(token.used_at)

        page = self.client.get("/profile").get_data(as_text=True)
        self.assertIn(f"/start {value}", page)
        self.assertIn("Root Link Status", page)

    def test_root_token_is_scoped_to_the_root_provider(self):
        self._member()
        self._login()
        self.client.post("/profile/root-link-token")

        with self.app.app_context():
            rows = [(t.provider, t.user_id) for t in BotLinkToken.query.all()]
        self.assertEqual([p for p, _ in rows], ["root"])

    def test_reserved_support_accounts_cannot_mint_root_tokens(self):
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
