import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

from app import create_app, db
from app.models import GroupTest, NotificationConfig, Participation, PaymentOption, PublicResult, TelegramLinkToken, TelegramWebhookUpdate, User


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

    def test_group_test_result_image_requires_paid_participant(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            viewer = User(username="viewer", email="viewer@example.com", is_admin=False)
            viewer.set_password("secret")
            db.session.add_all([admin, viewer])
            db.session.flush()

            test = GroupTest(
                title="Secure Result Test",
                status="closed",
                results_link="https://example.com/result",
                results_image_key="result-images/group-tests/secure.jpg",
                created_by=admin.id,
            )
            db.session.add(test)
            db.session.flush()

            part = Participation(
                group_test_id=test.id,
                user_id=viewer.id,
                approved=True,
                paid_lab=False,
                denied=False,
                name="Viewer",
            )
            db.session.add(part)
            db.session.commit()

            test_id = test.id
            part_id = part.id

        self.client.post("/login", data={"username": "viewer", "password": "secret"}, follow_redirects=True)

        response = self.client.get(f"/result-image/group-test/{test_id}", follow_redirects=False)
        self.assertEqual(response.status_code, 403)

        with self.app.app_context():
            part = Participation.query.get(part_id)
            part.paid_lab = True
            db.session.commit()

        with patch("app.routes.generate_result_image_presigned_url", return_value="https://signed.example.com/image"):
            response = self.client.get(f"/result-image/group-test/{test_id}", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "https://signed.example.com/image")

    def test_public_result_image_requires_login(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.flush()

            public_result = PublicResult(
                title="Public Result",
                summary="Summary",
                results_link="https://example.com/result",
                results_image_key="result-images/public-results/secure.jpg",
                created_by=admin.id,
            )
            db.session.add(public_result)
            db.session.commit()
            public_result_id = public_result.id

        anonymous_response = self.client.get(f"/result-image/public/{public_result_id}", follow_redirects=False)
        self.assertEqual(anonymous_response.status_code, 302)
        self.assertIn("/login", anonymous_response.headers.get("Location", ""))

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)
        with patch("app.routes.generate_result_image_presigned_url", return_value="https://signed.example.com/public-image"):
            authed_response = self.client.get(f"/result-image/public/{public_result_id}", follow_redirects=False)

        self.assertEqual(authed_response.status_code, 302)
        self.assertEqual(authed_response.headers.get("Location"), "https://signed.example.com/public-image")

    def test_unpaid_member_cannot_see_group_test_results_until_paid(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            member = User(username="member", email="member@example.com", is_admin=False)
            member.set_password("secret")
            db.session.add_all([admin, member])
            db.session.flush()

            test = GroupTest(
                title="Paid Gate Test",
                status="closed",
                results_link="https://example.com/result",
                created_by=admin.id,
            )
            db.session.add(test)
            db.session.flush()

            part = Participation(
                group_test_id=test.id,
                user_id=member.id,
                approved=True,
                denied=False,
                paid_lab=False,
                name="Member",
            )
            db.session.add(part)
            db.session.commit()

            test_id = test.id
            part_id = part.id

        self.client.post("/login", data={"username": "member", "password": "secret"}, follow_redirects=True)

        detail_before = self.client.get(f"/test/{test_id}")
        self.assertEqual(detail_before.status_code, 200)
        self.assertNotIn("Test Results Available", detail_before.get_data(as_text=True))

        my_results_before = self.client.get("/my-results")
        self.assertEqual(my_results_before.status_code, 200)
        self.assertNotIn("Paid Gate Test", my_results_before.get_data(as_text=True))

        with self.app.app_context():
            part = Participation.query.get(part_id)
            part.paid_lab = True
            db.session.commit()

        detail_after = self.client.get(f"/test/{test_id}")
        self.assertIn("Test Results Available", detail_after.get_data(as_text=True))

        my_results_after = self.client.get("/my-results")
        self.assertIn("Paid Gate Test", my_results_after.get_data(as_text=True))

    def test_group_test_pdf_result_renders_pdf_modal_trigger_and_download_button(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            member = User(username="member", email="member@example.com", is_admin=False)
            member.set_password("secret")
            db.session.add_all([admin, member])
            db.session.flush()

            test = GroupTest(
                title="PDF Result Test",
                status="closed",
                results_link="https://example.com/coa",
                results_image_key="result-images/group-tests/coa.pdf",
                created_by=admin.id,
            )
            db.session.add(test)
            db.session.flush()

            part = Participation(
                group_test_id=test.id,
                user_id=member.id,
                approved=True,
                denied=False,
                paid_lab=True,
                name="Member",
            )
            db.session.add(part)
            db.session.commit()
            test_id = test.id

        self.client.post("/login", data={"username": "member", "password": "secret"}, follow_redirects=True)
        response = self.client.get(f"/test/{test_id}")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('data-file-kind="pdf"', body)
        self.assertIn('id="resultFileModalDownload"', body)

    def test_admin_public_results_page_renders_pdf_result_without_template_error(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.flush()

            db.session.add(
                PublicResult(
                    title="PDF Public Result",
                    summary="PDF summary",
                    results_link="https://example.com/public-pdf",
                    results_image_key="result-images/public-results/coa.pdf",
                    created_by=admin.id,
                )
            )
            db.session.commit()

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)
        response = self.client.get("/admin/public-results")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('data-file-kind="pdf"', body)

    def test_admin_my_results_shows_closed_results_without_membership(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            owner = User(username="owner", email="owner@example.com", is_admin=False)
            owner.set_password("secret")
            db.session.add_all([admin, owner])
            db.session.flush()

            test = GroupTest(
                title="Admin Bypass Results",
                status="closed",
                results_link="https://example.com/admin-bypass",
                created_by=owner.id,
            )
            db.session.add(test)
            db.session.commit()

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)
        my_results = self.client.get("/my-results")
        self.assertEqual(my_results.status_code, 200)
        self.assertIn("Admin Bypass Results", my_results.get_data(as_text=True))

    def test_telegram_webhook_requires_valid_secret(self):
        with self.app.app_context():
            db.create_all()
            db.session.add(NotificationConfig(key="telegram_webhook_secret", value="secret123"))
            db.session.commit()

        response = self.client.post(
            "/telegram/webhook",
            json={"message": {"chat": {"id": 1001}, "text": "/help"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        self.assertEqual(response.status_code, 403)

    def test_telegram_webhook_start_links_chat_id(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="tguser", email="tguser@example.com")
            user.set_password("secret")
            db.session.add(user)
            db.session.flush()
            token = TelegramLinkToken(
                user_id=user.id,
                token="token-abc",
                expires_at=datetime.utcnow() + timedelta(hours=1),
            )
            db.session.add(token)
            db.session.add(NotificationConfig(key="telegram_webhook_secret", value="secret123"))
            db.session.commit()
            user_id = user.id

        response = self.client.post(
            "/telegram/webhook",
            json={"message": {"chat": {"id": 777888}, "text": "/start token-abc"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret123"},
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            refreshed = User.query.get(user_id)
            self.assertEqual(refreshed.telegram_chat_id, "777888")

    def test_telegram_webhook_rejects_disallowed_source_ip(self):
        with self.app.app_context():
            db.create_all()
            db.session.add(NotificationConfig(key="telegram_webhook_allowed_ips", value="149.154.160.0/20"))
            db.session.commit()

        response = self.client.post(
            "/telegram/webhook",
            json={"update_id": 41, "message": {"chat": {"id": 1001}, "text": "/help"}},
            environ_base={"REMOTE_ADDR": "8.8.8.8"},
        )
        self.assertEqual(response.status_code, 403)

    def test_telegram_webhook_allows_configured_source_ip(self):
        with self.app.app_context():
            db.create_all()
            db.session.add(NotificationConfig(key="telegram_webhook_allowed_ips", value="149.154.160.0/20"))
            db.session.commit()

        response = self.client.post(
            "/telegram/webhook",
            json={"update_id": 42, "message": {"chat": {"id": 1001}, "text": "/help"}},
            environ_base={"REMOTE_ADDR": "149.154.167.220"},
        )
        self.assertEqual(response.status_code, 200)

    def test_telegram_webhook_ignores_group_messages_without_reply(self):
        with self.app.app_context():
            db.create_all()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": -10012345, "type": "supergroup"},
                        "from": {"id": 1001, "username": "groupuser"},
                        "text": "/help",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_send.assert_not_called()

    def test_telegram_webhook_group_message_does_not_overwrite_private_chat_link(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="tgprivate", email="tgprivate@example.com", telegram_chat_id="777888", telegram_user_id="123456")
            user.set_password("secret")
            db.session.add(user)
            db.session.commit()
            user_id = user.id

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": -1009000, "type": "group"},
                        "from": {"id": 123456, "username": "tgprivate"},
                        "text": "/mytests",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_send.assert_not_called()
        with self.app.app_context():
            refreshed = User.query.get(user_id)
            self.assertEqual(refreshed.telegram_chat_id, "777888")

    def test_telegram_webhook_testing_command_replies_in_group_with_signup_and_login_urls(self):
        with self.app.app_context():
            db.create_all()
            db.session.add(NotificationConfig(key="service_base_url", value="https://group-tests.example"))
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": -100333, "type": "supergroup"},
                        "text": "/testing",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once()
        sent_body = mock_send.call_args.args[1]
        self.assertIn("https://group-tests.example/register", sent_body)
        self.assertIn("https://group-tests.example/login", sent_body)

    def test_telegram_webhook_testing_command_replies_in_originating_message_thread(self):
        with self.app.app_context():
            db.create_all()
            db.session.add(NotificationConfig(key="service_base_url", value="https://group-tests.example"))
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": -100333, "type": "supergroup"},
                        "message_thread_id": 42,
                        "text": "/testing",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.kwargs.get("message_thread_id"), 42)

    def test_telegram_webhook_testing_command_replies_in_channel_post(self):
        with self.app.app_context():
            db.create_all()
            db.session.add(NotificationConfig(key="service_base_url", value="https://group-tests.example"))
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "channel_post": {
                        "chat": {"id": -100444, "type": "channel"},
                        "text": "/testing",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once()
        sent_body = mock_send.call_args.args[1]
        self.assertIn("Sign up:", sent_body)
        self.assertIn("Log in:", sent_body)

    def test_telegram_webhook_ignores_duplicate_update_id(self):
        with self.app.app_context():
            db.create_all()

        payload = {"update_id": 99, "message": {"chat": {"id": 1001}, "text": "/help"}}
        first = self.client.post("/telegram/webhook", json=payload)
        second = self.client.post("/telegram/webhook", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        with self.app.app_context():
            rows = TelegramWebhookUpdate.query.filter_by(update_id=99).all()
            self.assertEqual(len(rows), 1)

    def test_telegram_start_rejects_user_id_already_linked_elsewhere(self):
        with self.app.app_context():
            db.create_all()
            owner = User(username="owner", email="owner@example.com", telegram_user_id="123456")
            owner.set_password("secret")
            target = User(username="target", email="target@example.com")
            target.set_password("secret")
            db.session.add_all([owner, target])
            db.session.flush()

            token = TelegramLinkToken(
                user_id=target.id,
                token="token-owner-clash",
                expires_at=datetime.utcnow() + timedelta(hours=1),
            )
            db.session.add(token)
            db.session.commit()
            target_id = target.id
            token_id = token.id

        response = self.client.post(
            "/telegram/webhook",
            json={
                "message": {
                    "chat": {"id": 555999},
                    "from": {"id": 123456, "username": "clashing_user"},
                    "text": "/start token-owner-clash",
                }
            },
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            refreshed_target = User.query.get(target_id)
            refreshed_token = TelegramLinkToken.query.get(token_id)
            self.assertIsNone(refreshed_target.telegram_chat_id)
            self.assertIsNone(refreshed_target.telegram_user_id)
            self.assertIsNone(refreshed_token.used_at)

    def test_telegram_tests_command_lists_visible_tests_in_ascending_test_number_order(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="tgviewer", email="tgviewer@example.com", telegram_chat_id="1001", telegram_user_id="555")
            user.set_password("secret")
            owner = User(username="owner", email="owner@example.com", is_admin=True)
            owner.set_password("secret")
            db.session.add_all([user, owner])
            db.session.flush()

            test_three = GroupTest(title="Third Test", status="recruiting", created_by=owner.id)
            test_one = GroupTest(title="First Test", status="recruiting", created_by=owner.id)
            test_two = GroupTest(title="Second Test", status="ready_for_payment", created_by=owner.id)
            db.session.add_all([test_three, test_one, test_two])
            db.session.flush()
            db.session.add(Participation(group_test_id=test_two.id, user_id=user.id, approved=True, denied=False, name="Viewer"))
            db.session.commit()
            expected_lines = [
                f"#{test.id} {test.title}" for test in sorted([test_three, test_one, test_two], key=lambda item: item.id)
            ]

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": 1001},
                        "from": {"id": 555, "username": "tgviewer"},
                        "text": "/tests",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        sent_body = mock_send.call_args.args[1]
        self.assertIn("Eligible tests:\n", sent_body)
        positions = [sent_body.find(line) for line in expected_lines]
        self.assertTrue(all(position >= 0 for position in positions))
        self.assertEqual(positions, sorted(positions))

    def test_telegram_mytests_command_lists_only_user_interactions_with_states(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="tgmember", email="tgmember@example.com", telegram_chat_id="2002", telegram_user_id="777")
            user.set_password("secret")
            owner = User(username="owner", email="owner@example.com", is_admin=True)
            owner.set_password("secret")
            db.session.add_all([user, owner])
            db.session.flush()

            test_pending = GroupTest(title="Pending Test", status="recruiting", created_by=owner.id)
            test_denied = GroupTest(title="Denied Test", status="testing", created_by=owner.id)
            test_approved = GroupTest(title="Approved Test", status="closed", created_by=owner.id)
            test_unrelated = GroupTest(title="Unrelated Test", status="recruiting", created_by=owner.id)
            db.session.add_all([test_pending, test_denied, test_approved, test_unrelated])
            db.session.flush()

            db.session.add_all([
                Participation(group_test_id=test_pending.id, user_id=user.id, approved=False, denied=False, name="Member"),
                Participation(group_test_id=test_denied.id, user_id=user.id, approved=False, denied=True, denied_reason="Nope", name="Member"),
                Participation(group_test_id=test_approved.id, user_id=user.id, approved=True, denied=False, name="Member"),
            ])
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": 2002},
                        "from": {"id": 777, "username": "tgmember"},
                        "text": "/mytests",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        sent_body = mock_send.call_args.args[1]
        self.assertIn("Your group tests:\n", sent_body)
        self.assertIn("#1 Pending Test [Recruiting] - Pending", sent_body)
        self.assertIn("#2 Denied Test [Testing] - Denied", sent_body)
        self.assertIn("#3 Approved Test [Closed] - Approved", sent_body)
        self.assertNotIn("Unrelated Test", sent_body)

    def test_telegram_status_command_allows_user_participation_even_if_test_not_visible(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="tgdenied", email="tgdenied@example.com", telegram_chat_id="3003", telegram_user_id="888")
            user.set_password("secret")
            owner = User(username="owner", email="owner@example.com", is_admin=True)
            owner.set_password("secret")
            db.session.add_all([user, owner])
            db.session.flush()

            test = GroupTest(title="Denied Status Test", status="testing", created_by=owner.id)
            db.session.add(test)
            db.session.flush()
            db.session.add(Participation(
                group_test_id=test.id,
                user_id=user.id,
                approved=False,
                denied=True,
                denied_reason="Need more verification",
                name="Member",
            ))
            db.session.commit()
            test_id = test.id

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": 3003},
                        "from": {"id": 888, "username": "tgdenied"},
                        "text": f"/status {test_id}",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        sent_body = mock_send.call_args.args[1]
        self.assertIn(f"#{test_id} Denied Status Test: Denied.", sent_body)
        self.assertIn("Need more verification", sent_body)

    def test_delete_payment_option_in_use_sets_inactive(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            user = User(username="payer", email="payer@example.com")
            user.set_password("secret")
            option = PaymentOption(label="CashApp Main", method_type="cashapp", account_handle="$collector", is_active=True)
            db.session.add_all([admin, user, option])
            db.session.flush()

            test = GroupTest(title="Delete Guard Test", status="testing", created_by=admin.id)
            test.payment_options = [option]
            db.session.add(test)
            db.session.flush()

            part = Participation(
                group_test_id=test.id,
                user_id=user.id,
                approved=True,
                denied=False,
                name="Payer",
                preferred_payment_option_id=option.id,
            )
            db.session.add(part)
            db.session.commit()
            option_id = option.id

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)
        response = self.client.post(f"/admin/payment-options/{option_id}/delete", follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            persisted = PaymentOption.query.get(option_id)
            self.assertIsNotNone(persisted)
            self.assertFalse(persisted.is_active)

    def test_payment_option_form_requires_handle_for_venmo_without_override(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin-pay-validate", email="admin-pay-validate@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"username": "admin-pay-validate", "password": "secret"}, follow_redirects=True)
        response = self.client.post(
            "/admin/payment-options",
            data={
                "label": "Venmo Missing Handle",
                "method_type": "venmo",
                "recipient_name": "Recipient",
                "account_handle": "",
                "wallet_address": "",
                "network": "",
                "details": "",
                "qr_payload_override": "",
                "is_active": "y",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("requires an app handle/username", response.get_data(as_text=True))

    def test_delete_payment_option_unused_removes_row(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            option = PaymentOption(label="Temp Option", method_type="other", account_handle="temp", is_active=True)
            db.session.add_all([admin, option])
            db.session.commit()
            option_id = option.id

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)
        response = self.client.post(f"/admin/payment-options/{option_id}/delete", follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            self.assertIsNone(PaymentOption.query.get(option_id))

    def test_testing_status_page_shows_payment_option_selector_for_approved_participant(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            user = User(username="member", email="member@example.com", is_admin=False)
            user.set_password("secret")
            option = PaymentOption(label="Venmo Main", method_type="venmo", account_handle="@collector", is_active=True)
            db.session.add_all([admin, user, option])
            db.session.flush()

            test = GroupTest(title="Payment Selector Test", status="testing", created_by=admin.id)
            test.payment_options = [option]
            db.session.add(test)
            db.session.flush()

            part = Participation(group_test_id=test.id, user_id=user.id, approved=True, denied=False, name="Member")
            db.session.add(part)
            db.session.commit()
            test_id = test.id

        self.client.post("/login", data={"username": "member", "password": "secret"}, follow_redirects=True)
        response = self.client.get(f"/test/{test_id}/my-status")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Preferred Payment Method", body)
        self.assertIn("Venmo Main", body)

    def test_ready_for_payment_shows_payment_methods_at_top_of_right_column(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            option = PaymentOption(label="Cash App Main", method_type="cashapp", account_handle="$collector", is_active=True)
            db.session.add_all([admin, option])
            db.session.flush()

            test = GroupTest(title="Ready Status Test", status="ready_for_payment", created_by=admin.id)
            test.payment_options = [option]
            db.session.add(test)
            db.session.commit()
            test_id = test.id

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)
        response = self.client.get(f"/test/{test_id}")
        self.assertEqual(response.status_code, 200)

        body = response.get_data(as_text=True)
        self.assertIn("Available Payment Methods", body)
        self.assertIn("Cash App Main", body)
        self.assertLess(body.find("Available Payment Methods"), body.find("Quick Admin Actions"))

    def test_payment_profile_generates_venmo_link_destination_and_qr(self):
        option = PaymentOption(
            label="Venmo Main",
            method_type="venmo",
            account_handle="@collector.user",
            is_active=True,
        )

        profile = option.to_payment_profile()
        expected_link = f"https://venmo.com/{quote('collector.user', safe='._-')}"

        self.assertEqual(profile["provider_name"], "Venmo")
        self.assertEqual(profile["destination_label"], "Venmo Handle")
        self.assertEqual(profile["destination_value"], "@collector.user")
        self.assertEqual(profile["payment_link"], expected_link)
        self.assertEqual(profile["qr_payload"], expected_link)

    def test_payment_profile_generates_crypto_link_destination_and_qr(self):
        option = PaymentOption(
            label="ETH Wallet",
            method_type="crypto",
            wallet_address="0xabc123",
            network="ETH",
            is_active=True,
        )

        profile = option.to_payment_profile()

        self.assertEqual(profile["provider_name"], "Crypto Wallet")
        self.assertEqual(profile["destination_label"], "Wallet Address")
        self.assertEqual(profile["destination_value"], "0xabc123")
        self.assertEqual(profile["payment_link"], "ethereum:0xabc123")
        self.assertEqual(profile["qr_payload"], "ethereum:0xabc123")

    def test_ready_for_payment_renders_venmo_link_and_qr(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin-preview", email="admin-preview@example.com", is_admin=True)
            admin.set_password("secret")
            option = PaymentOption(label="Venmo Main", method_type="venmo", account_handle="@collector", is_active=True)
            db.session.add_all([admin, option])
            db.session.flush()

            test = GroupTest(title="Ready Render Test", status="ready_for_payment", created_by=admin.id)
            test.payment_options = [option]
            db.session.add(test)
            db.session.commit()
            test_id = test.id

        self.client.post("/login", data={"username": "admin-preview", "password": "secret"}, follow_redirects=True)
        response = self.client.get(f"/test/{test_id}")
        self.assertEqual(response.status_code, 200)

        body = response.get_data(as_text=True)
        self.assertIn("Open Payment Link", body)
        self.assertIn("https://venmo.com/collector", body)
        self.assertIn("Venmo Handle", body)
        self.assertIn("api.qrserver.com", body)

    def test_admin_can_register_telegram_webhook_from_config_page(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.add_all([
                NotificationConfig(key="telegram_bot_token", value="123456:ABC"),
                NotificationConfig(key="service_base_url", value="https://group-tests.example"),
                NotificationConfig(key="telegram_webhook_secret", value="secret123"),
            ])
            db.session.commit()

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)
        with patch("app.routes.register_telegram_webhook", return_value=(True, {"description": "Webhook was set"})) as mock_register:
            response = self.client.post("/admin/notification-config/telegram-webhook/register", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Telegram webhook registered successfully.", body)
        self.assertTrue(mock_register.called)
        self.assertEqual(mock_register.call_args.args[0], "https://group-tests.example/telegram/webhook")

    def test_register_telegram_webhook_requires_bot_token(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)
        response = self.client.post("/admin/notification-config/telegram-webhook/register", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Telegram bot token is required before webhook registration.", response.get_data(as_text=True))

    def test_admin_can_unregister_telegram_webhook_from_config_page(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.add(NotificationConfig(key="telegram_bot_token", value="123456:ABC"))
            db.session.commit()

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)
        with patch("app.routes.unregister_telegram_webhook", return_value=(True, {"description": "Webhook was deleted"})) as mock_unregister:
            response = self.client.post("/admin/notification-config/telegram-webhook/unregister", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Telegram webhook unregistered successfully.", body)
        self.assertTrue(mock_unregister.called)

    def test_notification_config_preserves_telegram_token_when_masked_value_submitted(self):
        from app.routes import mask_secret

        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.add(NotificationConfig(key="telegram_bot_token", value="123456:REALTOKEN"))
            db.session.commit()

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)

        response_get = self.client.get("/admin/notification-config")
        self.assertEqual(response_get.status_code, 200)
        body = response_get.get_data(as_text=True)
        self.assertIn("1234", body)
        self.assertIn("REALTOKEN"[-6:], body)

        response_post = self.client.post(
            "/admin/notification-config",
            data={
                "mailjet_api_key": "",
                "mailjet_secret_key": "",
                "mailjet_sender_email": "",
                "telegram_bot_token": mask_secret("123456:REALTOKEN"),
                "telegram_bot_username": "",
                "telegram_webhook_url": "",
                "telegram_webhook_secret": "",
                "telegram_webhook_allowed_ips": "",
                "telegram_status_chat_id": "",
                "telegram_digest_enabled": "",
                "telegram_digest_window_minutes": "10",
                "service_base_url": "",
                "notification_debug_enabled": "",
            },
            follow_redirects=True,
        )
        self.assertEqual(response_post.status_code, 200)

        with self.app.app_context():
            cfg = NotificationConfig.query.filter_by(key="telegram_bot_token").first()
            self.assertIsNotNone(cfg)
            self.assertEqual(cfg.value, "123456:REALTOKEN")

    def test_notification_config_persists_telegram_status_templates(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)

        response_post = self.client.post(
            "/admin/notification-config",
            data={
                "mailjet_api_key": "",
                "mailjet_secret_key": "",
                "mailjet_sender_email": "",
                "telegram_bot_token": "",
                "telegram_bot_username": "",
                "telegram_webhook_url": "",
                "telegram_webhook_secret": "",
                "telegram_webhook_allowed_ips": "",
                "telegram_status_chat_id": "-10012345",
                "telegram_digest_enabled": "y",
                "telegram_digest_window_minutes": "15",
                "telegram_status_digest_header_template": "Header {{ new_status_label }}",
                "telegram_status_digest_line_template": "Line {{ test_title }}",
                "telegram_status_digest_participants_template": "P {{ mentions }}",
                "telegram_status_new_test_template": "New {{ test_id }} {{ test_url }}",
                "telegram_status_user_no_request_template": "None {{ test_title }}",
                "telegram_status_user_denied_template": "Denied {{ denied_reason }}",
                "telegram_status_user_results_template": "Results {{ results_url }}",
                "telegram_status_user_approved_template": "Approved {{ amount_owed }}",
                "telegram_status_user_pending_template": "Pending {{ test_id }}",
                "service_base_url": "",
                "notification_debug_enabled": "",
            },
            follow_redirects=True,
        )
        self.assertEqual(response_post.status_code, 200)

        with self.app.app_context():
            self.assertEqual(NotificationConfig.query.filter_by(key="telegram_status_digest_header_template").first().value, "Header {{ new_status_label }}")
            self.assertEqual(NotificationConfig.query.filter_by(key="telegram_status_digest_line_template").first().value, "Line {{ test_title }}")
            self.assertEqual(NotificationConfig.query.filter_by(key="telegram_status_digest_participants_template").first().value, "P {{ mentions }}")
            self.assertEqual(NotificationConfig.query.filter_by(key="telegram_status_new_test_template").first().value, "New {{ test_id }} {{ test_url }}")
            self.assertEqual(NotificationConfig.query.filter_by(key="telegram_status_user_no_request_template").first().value, "None {{ test_title }}")
            self.assertEqual(NotificationConfig.query.filter_by(key="telegram_status_user_denied_template").first().value, "Denied {{ denied_reason }}")
            self.assertEqual(NotificationConfig.query.filter_by(key="telegram_status_user_results_template").first().value, "Results {{ results_url }}")
            self.assertEqual(NotificationConfig.query.filter_by(key="telegram_status_user_approved_template").first().value, "Approved {{ amount_owed }}")
            self.assertEqual(NotificationConfig.query.filter_by(key="telegram_status_user_pending_template").first().value, "Pending {{ test_id }}")

    def test_profile_shows_generated_telegram_link_and_qr_when_bot_username_configured(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="profiletg", email="profiletg@example.com")
            user.set_password("secret")
            db.session.add(user)
            db.session.add(NotificationConfig(key="telegram_bot_username", value="group_test_tracker_bot"))
            db.session.commit()

        self.client.post("/login", data={"username": "profiletg", "password": "secret"}, follow_redirects=True)
        self.client.post("/profile/telegram-link-token", follow_redirects=True)
        response = self.client.get("/profile")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Generated Bot Link", body)
        self.assertIn("https://t.me/group_test_tracker_bot?start=", body)
        self.assertIn("create-qr-code", body)

    def test_profile_shows_start_command_when_bot_username_missing(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="profiletg2", email="profiletg2@example.com")
            user.set_password("secret")
            db.session.add(user)
            db.session.commit()

        self.client.post("/login", data={"username": "profiletg2", "password": "secret"}, follow_redirects=True)
        self.client.post("/profile/telegram-link-token", follow_redirects=True)
        response = self.client.get("/profile")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Start Command", body)
        self.assertIn("/start", body)
