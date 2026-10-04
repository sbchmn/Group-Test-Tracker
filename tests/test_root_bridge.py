"""Tests for the Root bridge transport: signature auth, replay defence, outbox lifecycle."""

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import create_app, db
from app.bot_identity import issue_link_token
from app.models import (
    BotLinkToken,
    NotificationConfig,
    RootBridgeNonce,
    RootInboundEvent,
    RootOutbox,
    User,
)
from app.root_bridge import (
    ROOT_SIGNATURE_WINDOW_SECONDS,
    request_headers,
)

COMMUNITY = "0198ac00-0000-7000-8000-00000000aaaa"
STATUS_CHANNEL = "0198ac00-0000-7000-8000-00000000bbbb"
OTHER_CHANNEL = "0198ac00-0000-7000-8000-00000000cccc"
KEY_ID = "root-testkey"
SECRET = "a" * 64
MAX_ATTEMPTS = 5


def _now():
    return int(datetime.now(timezone.utc).timestamp())


class RootBridgeTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path}",
            "NOTIFICATION_LOG_PATH": str(Path(self.temp_dir.name) / "notification.log"),
        })
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add_all([
                NotificationConfig(key="root_bridge_key_id", value=KEY_ID),
                NotificationConfig(key="root_bridge_secret", value=SECRET),
                NotificationConfig(key="root_community_id", value=COMMUNITY),
                NotificationConfig(key="root_status_channel_id", value=STATUS_CHANNEL),
            ])
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def _post(self, path, payload, *, key_id=KEY_ID, secret=SECRET, timestamp=None, nonce=None):
        body = json.dumps(payload).encode("utf-8")
        headers = request_headers(
            secret, key_id=key_id, method="POST", path=path, body=body,
            timestamp=timestamp, nonce=nonce,
        )
        headers["Content-Type"] = "application/json"
        return self.client.post(path, data=body, headers=headers)

    def _event(self, **overrides):
        payload = {
            "event": "channelMessage.created",
            "communityId": COMMUNITY,
            "channelId": STATUS_CHANNEL,
            "messageId": "msg-default",
            "userId": "0198beef-0000-7000-8000-000000000001",
            "content": "/help",
        }
        payload.update(overrides)
        return payload

    def _admin(self, username):
        with self.app.app_context():
            admin = User(username=username, email=f"{username}@example.test", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.commit()
        self.client.post(
            "/login", data={"username": username, "password": "secret"}, follow_redirects=True,
        )

    def _outbox_rows(self):
        with self.app.app_context():
            return list(RootOutbox.query.all())


class RootBridgeAuthTests(RootBridgeTestCase):
    def test_signed_request_is_accepted(self):
        response = self._post("/root/webhook", self._event())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_unsigned_request_is_rejected(self):
        response = self.client.post(
            "/root/webhook",
            data=json.dumps(self._event()),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 403)

    def test_tampered_body_is_rejected(self):
        payload = self._event()
        body = json.dumps(payload).encode("utf-8")
        headers = request_headers(SECRET, key_id=KEY_ID, method="POST", path="/root/webhook", body=body)
        tampered = json.dumps({**payload, "content": "/start someone-elses-token"}).encode("utf-8")

        response = self.client.post("/root/webhook", data=tampered, headers=headers)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._outbox_rows(), [])

    def test_wrong_secret_is_rejected(self):
        response = self._post("/root/webhook", self._event(), secret="b" * 64)
        self.assertEqual(response.status_code, 403)

    def test_unknown_key_id_is_rejected(self):
        response = self._post("/root/webhook", self._event(), key_id="root-other-tenant")
        self.assertEqual(response.status_code, 403)

    def test_stale_timestamp_is_rejected(self):
        stale = _now() - (ROOT_SIGNATURE_WINDOW_SECONDS + 60)
        response = self._post("/root/webhook", self._event(), timestamp=str(stale))
        self.assertEqual(response.status_code, 403)

    def test_far_future_timestamp_is_rejected(self):
        future = _now() + (ROOT_SIGNATURE_WINDOW_SECONDS + 60)
        response = self._post("/root/webhook", self._event(), timestamp=str(future))
        self.assertEqual(response.status_code, 403)

    def test_a_replayed_nonce_is_rejected_even_when_otherwise_valid(self):
        payload = self._event()

        first = self._post("/root/webhook", payload, nonce="fixed-nonce-value-1234")
        replay = self._post("/root/webhook", payload, nonce="fixed-nonce-value-1234")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 403)
        with self.app.app_context():
            self.assertEqual(RootInboundEvent.query.count(), 1)

    def test_malformed_timestamp_is_rejected(self):
        response = self._post("/root/webhook", self._event(), timestamp="tomorrow")
        self.assertEqual(response.status_code, 403)

    def test_non_object_json_body_is_rejected(self):
        body = json.dumps(["not", "an", "object"]).encode("utf-8")
        headers = request_headers(SECRET, key_id=KEY_ID, method="POST", path="/root/webhook", body=body)
        response = self.client.post("/root/webhook", data=body, headers=headers)
        self.assertEqual(response.status_code, 403)

    def test_unconfigured_instance_rejects_everything(self):
        with self.app.app_context():
            NotificationConfig.query.filter_by(key="root_bridge_secret").delete()
            db.session.commit()

        self.assertEqual(self._post("/root/webhook", self._event()).status_code, 403)

    def test_rejection_does_not_leak_the_failure_reason(self):
        response = self._post("/root/webhook", self._event(), secret="b" * 64)
        self.assertNotIn("signature", response.get_data(as_text=True).lower())
        self.assertEqual(response.get_json()["error"], "request rejected")

    def test_signature_is_bound_to_the_path_it_covered(self):
        payload = self._event()
        body = json.dumps(payload).encode("utf-8")
        headers = request_headers(SECRET, key_id=KEY_ID, method="POST", path="/root/webhook", body=body)

        response = self.client.post("/root/outbox/claim", data=body, headers=headers)

        self.assertEqual(response.status_code, 403)

    def test_a_rejected_request_does_not_consume_its_nonce(self):
        body = json.dumps(self._event()).encode("utf-8")
        headers = request_headers(
            "b" * 64, key_id=KEY_ID, method="POST", path="/root/webhook",
            body=body, nonce="nonce-audit-1",
        )
        self.client.post("/root/webhook", data=body, headers=headers)

        digest = hashlib.sha256(f"{KEY_ID}:nonce-audit-1".encode("utf-8")).hexdigest()
        with self.app.app_context():
            self.assertIsNone(RootBridgeNonce.query.filter_by(nonce_digest=digest).first())


class RootInboundEventTests(RootBridgeTestCase):
    def test_mismatched_community_is_rejected_and_stores_nothing(self):
        response = self._post("/root/webhook", self._event(communityId="0198other"))

        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            self.assertEqual(RootInboundEvent.query.count(), 0)
            self.assertEqual(RootOutbox.query.count(), 0)

    def test_duplicate_message_id_is_reported_as_duplicate_not_an_error(self):
        payload = self._event(messageId="dupe-1")

        first = self._post("/root/webhook", payload)
        second = self._post("/root/webhook", payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["duplicate"])
        with self.app.app_context():
            self.assertEqual(RootInboundEvent.query.count(), 1)
            self.assertEqual(RootOutbox.query.count(), 1)

    def test_help_command_queues_a_reply_for_the_originating_channel(self):
        response = self._post("/root/webhook", self._event(content="/help", messageId="help-1"))

        self.assertEqual(response.status_code, 200)
        queued = self._outbox_rows()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0].channel_id, STATUS_CHANNEL)
        self.assertIn("/start <token>", queued[0].body)
        self.assertEqual(queued[0].event_key, "evt:help-1")

    def test_reply_goes_to_the_channel_the_command_came_from_not_the_status_channel(self):
        self._post("/root/webhook", self._event(
            content="/help", messageId="help-route", channelId=OTHER_CHANNEL,
        ))

        queued = self._outbox_rows()
        self.assertEqual([row.channel_id for row in queued], [OTHER_CHANNEL])

    def test_linked_user_does_not_see_the_unlinked_hint(self):
        with self.app.app_context():
            linked = User(username="rooted", email="rooted@example.test", root_user_id="root-user-1")
            linked.set_password("secret")
            db.session.add(linked)
            db.session.commit()

        self._post("/root/webhook", self._event(
            content="/help", messageId="help-linked", userId="root-user-1",
        ))

        body = self._outbox_rows()[0].body
        self.assertNotIn("not linked yet", body)

    def test_unknown_command_gets_the_hint_reply(self):
        self._post("/root/webhook", self._event(content="/nonsense", messageId="unk-1"))
        self.assertIn("not wired to that command", self._outbox_rows()[0].body)

    def test_non_command_message_queues_no_reply(self):
        self._post("/root/webhook", self._event(content="just chatting", messageId="plain-1"))

        with self.app.app_context():
            self.assertEqual(RootOutbox.query.count(), 0)
            self.assertEqual(RootInboundEvent.query.count(), 1)

    def test_start_token_links_the_root_account(self):
        with self.app.app_context():
            user = User(username="claimant", email="claimant@example.test")
            user.set_password("secret")
            db.session.add(user)
            db.session.commit()
            token_value = issue_link_token("root", user).token
            db.session.commit()
            user_id = user.id

        response = self._post("/root/webhook", self._event(
            content=f"/start {token_value}", messageId="start-1", userId="root-user-9",
        ))

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(User, user_id).root_user_id, "root-user-9")
            self.assertIsNotNone(BotLinkToken.query.filter_by(token=token_value).first().used_at)
        self.assertIn("linked", self._outbox_rows()[0].body)

    def test_a_root_token_cannot_relink_away_an_existing_account(self):
        with self.app.app_context():
            user = User(username="twice", email="twice@example.test")
            user.set_password("secret")
            db.session.add(user)
            db.session.commit()
            token_value = issue_link_token("root", user).token
            db.session.commit()

        self._post("/root/webhook", self._event(content=f"/start {token_value}", messageId="s-1", userId="root-user-1"))
        self._post("/root/webhook", self._event(content=f"/start {token_value}", messageId="s-2", userId="root-user-2"))

        with self.app.app_context():
            self.assertEqual(User.query.filter_by(username="twice").first().root_user_id, "root-user-1")

    def test_start_without_a_sender_identity_does_not_burn_the_token(self):
        """An event with no userId has no identity to link, so the claim must not run.

        Claiming anyway consumed the member's single-use token and then replied that
        the account was linked, leaving them unlinked with no token to retry with.
        """
        with self.app.app_context():
            user = User(username="ghost", email="ghost@example.test")
            user.set_password("secret")
            db.session.add(user)
            db.session.commit()
            token_value = issue_link_token("root", user).token
            db.session.commit()

        self._post("/root/webhook", self._event(
            content=f"/start {token_value}", messageId="start-noid", userId="",
        ))

        with self.app.app_context():
            self.assertIsNone(User.query.filter_by(username="ghost").first().root_user_id)
            self.assertIsNone(
                BotLinkToken.query.filter_by(token=token_value).first().used_at,
                "token was consumed even though nothing could be linked",
            )
        body = self._outbox_rows()[0].body
        self.assertIn("could not identify", body)
        self.assertNotIn("linked", body)

    def test_a_link_token_survives_the_refusal_and_works_once_identity_arrives(self):
        with self.app.app_context():
            user = User(username="later", email="later@example.test")
            user.set_password("secret")
            db.session.add(user)
            db.session.commit()
            token_value = issue_link_token("root", user).token
            db.session.commit()

        self._post("/root/webhook", self._event(
            content=f"/start {token_value}", messageId="later-noid", userId="",
        ))
        self._post("/root/webhook", self._event(
            content=f"/start {token_value}", messageId="later-id", userId="root-user-77",
        ))

        with self.app.app_context():
            self.assertEqual(User.query.filter_by(username="later").first().root_user_id, "root-user-77")

    def test_start_without_argument_does_not_link(self):
        with self.app.app_context():
            user = User(username="noarg", email="noarg@example.test")
            user.set_password("secret")
            db.session.add(user)
            db.session.commit()
            issue_link_token("root", user)
            db.session.commit()

        self._post("/root/webhook", self._event(content="/start", messageId="start-blank"))

        with self.app.app_context():
            self.assertIsNone(User.query.filter_by(username="noarg").first().root_user_id)
        self.assertIn("invalid or expired", self._outbox_rows()[0].body)


class RootOutboxLifecycleTests(RootBridgeTestCase):
    def _seed(self, count=2):
        with self.app.app_context():
            for index in range(count):
                db.session.add(RootOutbox(channel_id=STATUS_CHANNEL, body=f"message {index}"))
            db.session.commit()

    def test_claim_returns_messages_and_marks_them_claimed(self):
        self._seed(2)

        payload = self._post("/root/outbox/claim", {"communityId": COMMUNITY, "limit": 5}).get_json()

        self.assertEqual(len(payload["messages"]), 2)
        self.assertEqual(payload["messages"][0]["channelId"], STATUS_CHANNEL)
        self.assertIn("leaseToken", payload)
        with self.app.app_context():
            self.assertEqual(RootOutbox.query.filter_by(status=RootOutbox.CLAIMED).count(), 2)
            self.assertEqual(RootOutbox.query.first().attempt_count, 1)

    def test_a_claimed_row_is_not_re_leased_before_its_lease_expires(self):
        self._seed(1)

        first = self._post("/root/outbox/claim", {"communityId": COMMUNITY}).get_json()
        second = self._post("/root/outbox/claim", {"communityId": COMMUNITY}).get_json()

        self.assertEqual(len(first["messages"]), 1)
        self.assertEqual(second["messages"], [])

    def test_an_expired_lease_makes_the_row_claimable_again(self):
        self._seed(1)
        self._post("/root/outbox/claim", {"communityId": COMMUNITY})
        with self.app.app_context():
            row = RootOutbox.query.one()
            row.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.session.commit()

        payload = self._post("/root/outbox/claim", {"communityId": COMMUNITY}).get_json()

        self.assertEqual(len(payload["messages"]), 1)
        with self.app.app_context():
            self.assertEqual(RootOutbox.query.one().attempt_count, 2)

    def test_ack_marks_delivered_messages_sent(self):
        self._seed(2)
        claim = self._post("/root/outbox/claim", {"communityId": COMMUNITY}).get_json()
        results = [{"id": message["id"], "delivered": True} for message in claim["messages"]]

        response = self._post("/root/outbox/ack", {"leaseToken": claim["leaseToken"], "results": results})

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(RootOutbox.query.filter_by(status=RootOutbox.SENT).count(), 2)
            self.assertIsNotNone(RootOutbox.query.first().sent_at)

    def test_failed_ack_returns_a_row_to_pending_with_backoff(self):
        self._seed(1)
        claim = self._post("/root/outbox/claim", {"communityId": COMMUNITY}).get_json()
        message_id = claim["messages"][0]["id"]

        self._post("/root/outbox/ack", {
            "leaseToken": claim["leaseToken"],
            "results": [{"id": message_id, "delivered": False, "error": "channel archived"}],
        })

        with self.app.app_context():
            row = db.session.get(RootOutbox, message_id)
            self.assertEqual(row.status, RootOutbox.PENDING)
            self.assertEqual(row.last_error, "channel archived")
            self.assertGreater(row.next_attempt_at, datetime.utcnow())
            self.assertIsNone(row.lease_token)

    def test_rows_are_parked_as_failed_once_attempts_are_exhausted(self):
        self._seed(1)
        for _ in range(MAX_ATTEMPTS):
            with self.app.app_context():
                row = RootOutbox.query.first()
                row.status = RootOutbox.PENDING
                row.next_attempt_at = None
                db.session.commit()
            claim = self._post("/root/outbox/claim", {"communityId": COMMUNITY}).get_json()
            self._post("/root/outbox/ack", {
                "leaseToken": claim["leaseToken"],
                "results": [{"id": claim["messages"][0]["id"], "delivered": False, "error": "nope"}],
            })

        with self.app.app_context():
            self.assertEqual(RootOutbox.query.one().status, RootOutbox.FAILED)

    def test_ack_from_a_stale_lease_cannot_touch_the_rows(self):
        self._seed(1)
        claim = self._post("/root/outbox/claim", {"communityId": COMMUNITY}).get_json()
        message_id = claim["messages"][0]["id"]

        response = self._post("/root/outbox/ack", {
            "leaseToken": "someone-elses-lease",
            "results": [{"id": message_id, "delivered": True}],
        })

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(RootOutbox, message_id).status, RootOutbox.CLAIMED)

    def test_claim_requires_the_community_to_match(self):
        self._seed(1)
        self.assertEqual(self._post("/root/outbox/claim", {"communityId": "0198wrong"}).status_code, 403)

    def test_an_oversized_limit_is_clamped_not_rejected(self):
        self._seed(3)
        payload = self._post("/root/outbox/claim", {"communityId": COMMUNITY, "limit": 10000}).get_json()
        self.assertEqual(len(payload["messages"]), 3)

    def test_stats_reports_queue_depth(self):
        self._seed(1)

        payload = self._post("/root/outbox/stats", {"communityId": COMMUNITY}).get_json()

        self.assertEqual(payload["pending"], 1)
        self.assertIn("serverTime", payload)


class RootAdminTests(RootBridgeTestCase):
    def test_root_config_page_renders_the_bridge_fields(self):
        self._admin("root-admin")

        page = self.client.get("/admin/settings/bots").get_data(as_text=True)

        self.assertIn("Root Community ID", page)
        self.assertIn("/admin/settings/bots/root/bridge-credentials", page)

    def test_credentials_page_shows_a_fresh_secret_once(self):
        self._admin("root-admin2")

        response = self.client.post("/admin/settings/bots/root/bridge-credentials")

        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Root-Bridge-Key-Id", response.get_data(as_text=True))
        with self.app.app_context():
            stored = {item.key: item.value for item in NotificationConfig.query.all()}
        self.assertEqual(len(stored["root_bridge_secret"]), 64)
        self.assertNotEqual(stored["root_bridge_secret"], SECRET)

    def test_test_message_queues_through_the_same_path_as_notifications(self):
        self._admin("root-admin3")

        response = self.client.post("/admin/settings/bots/root/test-message", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        queued = self._outbox_rows()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0].channel_id, STATUS_CHANNEL)

    def _config_map(self):
        with self.app.app_context():
            return {item.key: item.value for item in NotificationConfig.query.all()}

    def test_saving_a_stale_form_preserves_the_generated_bridge_pair(self):
        """A form rendered before a generation posts the pair back blank.

        Blanking it on save killed a working credential with no error while flashing
        success, leaving the bridge signing with a secret that no longer existed.
        """
        self._admin("root-admin4")
        self.assertEqual(
            self.client.post("/admin/settings/bots/root/bridge-credentials").status_code, 200)
        before = self._config_map()
        self.assertTrue(before["root_bridge_secret"])
        self.assertTrue(before["root_bridge_key_id"])

        response = self.client.post("/admin/settings/bots", data={
            "telegram_bot_username": "saved-something-else",
            "telegram_digest_enabled": "false",
            "telegram_digest_window_minutes": "10",
            "service_base_url": "http://app.example.test",
        }, follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        after = self._config_map()
        # Proves the save actually ran rather than failing validation into a no-op.
        self.assertEqual(after["telegram_bot_username"], "saved-something-else")
        self.assertEqual(after["root_bridge_secret"], before["root_bridge_secret"])
        self.assertEqual(after["root_bridge_key_id"], before["root_bridge_key_id"])

    def test_a_deliberately_typed_bridge_secret_is_still_stored(self):
        self._admin("root-admin5")

        self.client.post("/admin/settings/bots", data={
            "root_bridge_secret": "b" * 64,
            "root_bridge_key_id": "root-manual",
            "telegram_digest_enabled": "false",
            "telegram_digest_window_minutes": "10",
        }, follow_redirects=False)

        after = self._config_map()
        self.assertEqual(after["root_bridge_secret"], "b" * 64)
        self.assertEqual(after["root_bridge_key_id"], "root-manual")

    def test_anonymous_cannot_reach_the_admin_actions(self):
        for path in ("/admin/settings/bots/root/test-message", "/admin/settings/bots/root/bridge-credentials"):
            with self.subTest(path=path):
                response = self.client.post(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login", response.headers.get("Location", ""))


if __name__ == "__main__":
    unittest.main()
