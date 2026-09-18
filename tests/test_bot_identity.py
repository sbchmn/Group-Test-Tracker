"""Tests for the shared bot identity layer (bot architecture Phase 1, increment 2)."""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app import create_app, db
from app.bot_identity import (
    CLAIM_EXTERNAL_OWNED,
    CLAIM_INVALID,
    CLAIM_OK,
    CLAIM_UNKNOWN_PROVIDER,
    CLAIM_USER_OWNED,
    active_link_token,
    claim_link_token,
    issue_link_token,
    supports_provider,
)
from app.models import BotLinkToken, User


class BotIdentityTests(unittest.TestCase):
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

    def _user(self, username, **fields):
        user = User(username=username, email=f"{username}@example.com", **fields)
        user.set_password("secret")
        db.session.add(user)
        db.session.commit()
        return user

    def test_unsupported_provider_cannot_issue_or_claim(self):
        with self.app.app_context():
            db.create_all()
            user = self._user("issuer")
            self.assertFalse(supports_provider("carrier-pigeon"))
            with self.assertRaises(ValueError):
                issue_link_token("carrier-pigeon", user)
            self.assertEqual(
                claim_link_token("carrier-pigeon", "anything"),
                (None, CLAIM_UNKNOWN_PROVIDER),
            )

    def test_root_is_a_supported_link_provider(self):
        with self.app.app_context():
            db.create_all()
            user = self._user("rooter")
            self.assertTrue(supports_provider("root"))
            token = issue_link_token("root", user)
            db.session.commit()

            claimed, reason = claim_link_token("root", token.token, external_id="0198beef-0000")
            db.session.commit()

            self.assertEqual(reason, CLAIM_OK)
            self.assertEqual(db.session.get(User, user.id).root_user_id, "0198beef-0000")

    def test_issued_token_is_returned_by_active_lookup_for_its_provider(self):
        with self.app.app_context():
            db.create_all()
            user = self._user("active")
            token = issue_link_token("telegram", user)
            db.session.commit()

            self.assertIsNotNone(token.id)
            self.assertEqual(active_link_token("telegram", user).token, token.token)
            self.assertIsNone(active_link_token("discord", user))

    def test_claim_writes_the_provider_columns_for_that_provider_only(self):
        with self.app.app_context():
            db.create_all()
            user = self._user("tglink")
            token = issue_link_token("telegram", user)
            db.session.commit()

            claimed, reason = claim_link_token(
                "telegram", token.token, external_id="111", chat_id="222", username="handle",
            )
            db.session.commit()

            self.assertEqual(reason, CLAIM_OK)
            refreshed = db.session.get(User, user.id)
            self.assertEqual(refreshed.telegram_user_id, "111")
            self.assertEqual(refreshed.telegram_chat_id, "222")
            self.assertEqual(refreshed.tg_username, "handle")
            self.assertIsNone(refreshed.discord_user_id)
            self.assertIsNotNone(db.session.get(BotLinkToken, token.id).used_at)

    def test_discord_claim_does_not_touch_telegram_columns(self):
        with self.app.app_context():
            db.create_all()
            user = self._user("dclink")
            token = issue_link_token("discord", user)
            db.session.commit()

            _, reason = claim_link_token("discord", token.token, external_id="999", username="dc-handle")
            db.session.commit()

            self.assertEqual(reason, CLAIM_OK)
            refreshed = db.session.get(User, user.id)
            self.assertEqual(refreshed.discord_user_id, "999")
            self.assertEqual(refreshed.discord_username, "dc-handle")
            self.assertIsNone(refreshed.telegram_user_id)
            self.assertIsNone(refreshed.telegram_chat_id)

    def test_a_token_cannot_be_claimed_on_another_provider(self):
        with self.app.app_context():
            db.create_all()
            user = self._user("cross")
            token = issue_link_token("discord", user)
            db.session.commit()

            claimed, reason = claim_link_token("telegram", token.token, external_id="111", chat_id="222")

            self.assertIsNone(claimed)
            self.assertEqual(reason, CLAIM_INVALID)
            self.assertIsNone(db.session.get(User, user.id).telegram_chat_id)
            self.assertIsNone(db.session.get(BotLinkToken, token.id).used_at)

    def test_a_token_is_single_use(self):
        with self.app.app_context():
            db.create_all()
            user = self._user("once")
            token = issue_link_token("telegram", user)
            db.session.commit()

            first, first_reason = claim_link_token("telegram", token.token, external_id="111", chat_id="222")
            db.session.commit()
            second, second_reason = claim_link_token("telegram", token.token, external_id="111", chat_id="333")

            self.assertEqual(first_reason, CLAIM_OK)
            self.assertIsNone(second)
            self.assertEqual(second_reason, CLAIM_INVALID)
            self.assertEqual(db.session.get(User, user.id).telegram_chat_id, "222")

    def test_expired_token_is_refused(self):
        with self.app.app_context():
            db.create_all()
            user = self._user("expired")
            token = BotLinkToken(
                provider="telegram", user_id=user.id, token="stale",
                expires_at=datetime.utcnow() - timedelta(minutes=1),
            )
            db.session.add(token)
            db.session.commit()

            self.assertIsNone(active_link_token("telegram", user))
            claimed, reason = claim_link_token("telegram", "stale", external_id="111", chat_id="222")
            self.assertIsNone(claimed)
            self.assertEqual(reason, CLAIM_INVALID)

    def test_deactivated_account_cannot_claim(self):
        with self.app.app_context():
            db.create_all()
            user = self._user("off", is_active=False)
            token = issue_link_token("telegram", user)
            db.session.commit()

            claimed, reason = claim_link_token("telegram", token.token, external_id="111", chat_id="222")

            self.assertIsNone(claimed)
            self.assertEqual(reason, "inactive-user")
            self.assertIsNone(db.session.get(User, user.id).telegram_chat_id)

    def test_external_id_already_owned_by_another_user_is_refused(self):
        with self.app.app_context():
            db.create_all()
            owner = self._user("owner", telegram_user_id="777")
            claimer = self._user("claimer")
            token = issue_link_token("telegram", claimer)
            db.session.commit()

            claimed, reason = claim_link_token("telegram", token.token, external_id="777", chat_id="222")

            self.assertIsNone(claimed)
            self.assertEqual(reason, CLAIM_EXTERNAL_OWNED)
            self.assertEqual(db.session.get(User, owner.id).telegram_user_id, "777")
            self.assertIsNone(db.session.get(User, claimer.id).telegram_chat_id)

    def test_claim_cannot_move_a_user_onto_a_different_external_account(self):
        with self.app.app_context():
            db.create_all()
            user = self._user("already", telegram_user_id="111")
            token = issue_link_token("telegram", user)
            db.session.commit()

            claimed, reason = claim_link_token("telegram", token.token, external_id="999", chat_id="222")

            self.assertIsNone(claimed)
            self.assertEqual(reason, CLAIM_USER_OWNED)
            self.assertEqual(db.session.get(User, user.id).telegram_user_id, "111")
            self.assertIsNone(db.session.get(User, user.id).telegram_chat_id)

    def test_same_external_id_can_be_reclaimed_by_its_owner(self):
        with self.app.app_context():
            db.create_all()
            user = self._user("relink", telegram_user_id="111", telegram_chat_id="old")
            token = issue_link_token("telegram", user)
            db.session.commit()

            claimed, reason = claim_link_token("telegram", token.token, external_id="111", chat_id="new")
            db.session.commit()

            self.assertEqual(reason, CLAIM_OK)
            self.assertEqual(db.session.get(User, user.id).telegram_chat_id, "new")

    def test_blank_token_is_refused_without_a_query(self):
        with self.app.app_context():
            db.create_all()
            self.assertEqual(claim_link_token("telegram", "   "), (None, CLAIM_INVALID))
            self.assertEqual(claim_link_token("telegram", None), (None, CLAIM_INVALID))

    def test_active_lookup_prefers_the_newest_unconsumed_token(self):
        with self.app.app_context():
            db.create_all()
            user = self._user("newest")
            older = issue_link_token("telegram", user)
            db.session.commit()
            db.session.execute(
                BotLinkToken.__table__.update()
                .where(BotLinkToken.id == older.id)
                .values(created_at=datetime.utcnow() - timedelta(hours=5))
            )
            db.session.commit()
            newer = issue_link_token("telegram", user)
            db.session.commit()

            self.assertEqual(active_link_token("telegram", user).token, newer.token)


if __name__ == "__main__":
    unittest.main()
