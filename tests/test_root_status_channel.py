"""Root status-channel broadcasts are queued into the pull-based outbox."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app, db
from app.models import NotificationConfig, RootOutbox
from app.notifications import read_notification_log, send_root_status_channel_message


class RootStatusChannelTests(unittest.TestCase):
    STATUS_CHANNEL = "3f2b6c1e-0d4a-4a52-9b1f-6f0f7f2f9c11"

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

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def _seed(self, status_channel=STATUS_CHANNEL):
        with self.app.app_context():
            db.create_all()
            if status_channel is not None:
                db.session.add(
                    NotificationConfig(key="root_status_channel_id", value=status_channel)
                )
                db.session.commit()

    def _rows(self):
        with self.app.app_context():
            return [
                {
                    "channel_id": row.channel_id,
                    "body": row.body,
                    "status": row.status,
                    "event_key": row.event_key,
                }
                for row in RootOutbox.query.order_by(RootOutbox.id).all()
            ]

    def _send(self, body, buttons=None):
        with self.app.app_context():
            return send_root_status_channel_message(body, buttons=buttons)

    def _log(self):
        with self.app.app_context():
            return read_notification_log()

    def test_queues_row_in_configured_status_channel_and_returns_true(self):
        self._seed()

        result = self._send("  2 tests are ready for payment.  ")

        self.assertTrue(result)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["channel_id"], self.STATUS_CHANNEL)
        self.assertEqual(rows[0]["body"], "2 tests are ready for payment.")
        self.assertEqual(rows[0]["status"], RootOutbox.PENDING)

    def test_returns_false_and_queues_nothing_when_status_channel_unset(self):
        self._seed(status_channel=None)

        result = self._send("2 tests are ready for payment.", buttons=[
            {"label": "View Test", "url": "https://tracker.example.com/test/7"},
        ])

        self.assertFalse(result)
        self.assertEqual(self._rows(), [])
        self.assertIn("no status channel configured", self._log())

    def test_returns_false_for_empty_or_whitespace_body(self):
        self._seed()

        for body in ("", "   ", "\n\t ", None):
            with self.subTest(body=repr(body)):
                self.assertFalse(self._send(body))
        self.assertEqual(self._rows(), [])
        self.assertIn("empty body", self._log())

    def test_buttons_degrade_to_visible_absolute_urls(self):
        self._seed()
        buttons = [
            {"label": "View Payment Options", "url": "https://tracker.example.com/test/7#payment-options"},
            {"label": "View Test", "url": "https://tracker.example.com/test/8"},
        ]

        result = self._send("2 tests are ready for payment.", buttons=buttons)

        self.assertTrue(result)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        body = rows[0]["body"]
        self.assertTrue(body.startswith("2 tests are ready for payment."))
        for button in buttons:
            self.assertIn(button["url"], body)
            self.assertIn(f"{button['label']}: {button['url']}", body)
        # Plain text only: nothing interactive survives into the queued body.
        self.assertNotIn("inline_keyboard", body)
        self.assertNotIn("\"url\"", body)

    def test_button_missing_label_or_url_is_skipped_and_recorded(self):
        self._seed()
        rendered = {"label": "View Test", "url": "https://tracker.example.com/test/9"}
        buttons = [
            rendered,
            {"label": "Missing a url"},
            {"url": "https://tracker.example.com/test/orphan"},
            {},
        ]

        result = self._send("1 test is ready.", buttons=buttons)

        self.assertTrue(result)
        body = self._rows()[0]["body"]
        self.assertIn(f"{rendered['label']}: {rendered['url']}", body)
        self.assertNotIn("https://tracker.example.com/test/orphan", body)
        log = self._log()
        self.assertIn("root: skipped 3 status channel button(s)", log)

    def test_event_key_stays_null_for_broadcasts(self):
        self._seed()

        self.assertTrue(self._send("Broadcast without buttons."))
        self.assertTrue(self._send("Broadcast with buttons.", buttons=[
            {"label": "View Test", "url": "https://tracker.example.com/test/10"},
        ]))

        rows = self._rows()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIsNone(row["event_key"])

    def test_no_outbound_http_call_is_made(self):
        self._seed()

        with patch("app.notifications.urlopen") as mock_urlopen:
            result = self._send("Broadcast body.")

        self.assertTrue(result)
        mock_urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
