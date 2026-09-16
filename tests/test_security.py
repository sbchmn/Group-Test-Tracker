import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

from app import create_app, db
from app.models import BotCommandMessage, GroupTest, NotificationConfig, Participation, PaymentOption, PublicResult, Tag, TelegramCommandInvocation, TelegramCommandTemplate, TelegramLinkToken, TelegramWebhookUpdate, User
from app.public_results_bot import public_result_tag_page, public_results_for_tag_page
from app.routes import _process_public_results_telegram


class SecurityTests(unittest.TestCase):
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

        original_post = self.client.post

        def authenticated_post(*args, **kwargs):
            if args and args[0] == "/telegram/webhook":
                with self.app.app_context():
                    db.create_all()
                    if NotificationConfig.query.filter_by(key="telegram_webhook_secret").first() is None:
                        db.session.add(NotificationConfig(key="telegram_webhook_secret", value="test-webhook-secret"))
                        db.session.commit()
                headers = dict(kwargs.get("headers") or {})
                headers.setdefault("X-Telegram-Bot-Api-Secret-Token", "test-webhook-secret")
                kwargs["headers"] = headers
            return original_post(*args, **kwargs)

        self.client.post = authenticated_post

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def test_version_page_and_footer_expose_application_version(self):
        response = self.client.get("/version")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Application Version", body)
        self.assertIn("Version 4.0", body)
        self.assertIn("href=\"/version\"", body)

    def test_readiness_probes_are_public_and_side_effect_free(self):
        response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ready"})
        self.assertEqual(self.client.get("/heath/ready").status_code, 404)

        self.assertEqual(self.client.post("/health/ready").status_code, 405)

    def test_legal_pages_are_public_and_linked_from_footer_and_registration(self):
        terms_response = self.client.get("/terms")
        privacy_response = self.client.get("/privacy")
        register_response = self.client.get("/register")

        self.assertEqual(terms_response.status_code, 200)
        self.assertEqual(privacy_response.status_code, 200)
        self.assertEqual(register_response.status_code, 200)

        terms = terms_response.get_data(as_text=True)
        privacy = privacy_response.get_data(as_text=True)
        register = register_response.get_data(as_text=True)
        for body in (terms, privacy, register):
            self.assertIn('href="/terms"', body)
            self.assertIn('href="/privacy"', body)

        self.assertIn("Telegram, Discord, and webhook integrations", terms)
        self.assertIn("Automated report analysis", terms)
        self.assertIn("Google Analytics and cookies", privacy)
        self.assertIn("Telegram bot processing", privacy)
        self.assertIn("Discord bot processing", privacy)
        self.assertIn("Root and other webhook notifications", privacy)
        self.assertIn("OpenAI", privacy)
        self.assertIn("xAI (Grok)", privacy)
        self.assertIn("Anthropic (Claude)", privacy)

    def test_legal_operator_fields_are_escaped(self):
        self.app.config.update({
            "LEGAL_OPERATOR_NAME": '<script>alert("operator")</script>',
            "LEGAL_CONTACT_EMAIL": 'privacy@example.com',
            "LEGAL_GOVERNING_LAW": '<b>Example law</b>',
        })
        response = self.client.get("/terms")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<script>alert("operator")</script>', body)
        self.assertIn('&lt;script&gt;alert', body)
        self.assertNotIn('<b>Example law</b>', body)
        self.assertIn('privacy@example.com', body)

    def test_admin_settings_hub_requires_admin_and_groups_configuration_links(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="settings-admin", email="settings-admin@example.com", is_admin=True)
            admin.set_password("secret")
            member = User(username="settings-member", email="settings-member@example.com")
            member.set_password("secret")
            db.session.add_all([admin, member])
            db.session.commit()

        anonymous_response = self.client.get("/admin/settings", follow_redirects=False)
        self.assertEqual(anonymous_response.status_code, 302)
        self.assertIn("/login", anonymous_response.headers.get("Location", ""))

        self.client.post("/login", data={"username": "settings-member", "password": "secret"}, follow_redirects=True)
        member_response = self.client.get("/admin/settings", follow_redirects=False)
        self.assertEqual(member_response.status_code, 302)
        self.assertIn("/dashboard", member_response.headers.get("Location", ""))
        member_sync_response = self.client.post(
            "/admin/settings/bots/discord/sync-commands",
            follow_redirects=False,
        )
        self.assertEqual(member_sync_response.status_code, 302)
        self.assertIn("/dashboard", member_sync_response.headers.get("Location", ""))

        self.client.get("/logout", follow_redirects=True)
        self.client.post("/login", data={"username": "settings-admin", "password": "secret"}, follow_redirects=True)
        admin_response = self.client.get("/admin/settings")
        self.assertEqual(admin_response.status_code, 200)
        page = admin_response.get_data(as_text=True)
        self.assertIn("Admin Settings", page)
        self.assertIn("/admin/notification-config", page)
        self.assertIn("/admin/settings/bots", page)
        self.assertIn("/admin/settings/commands", page)
        self.assertIn("/admin/payment-options", page)
        self.assertIn("/admin/storage-config", page)

        bot_response = self.client.get("/admin/settings/bots")
        self.assertEqual(bot_response.status_code, 200)
        bot_page = bot_response.get_data(as_text=True)
        self.assertIn("Bot Integrations", bot_page)
        self.assertIn("/admin/telegram-config", bot_page)
        self.assertIn("Discord Bot Token", bot_page)
        self.assertIn("Synchronize Commands", bot_page)
        self.assertIn("/admin/settings/bots/discord/sync-commands", bot_page)
        self.assertIn("Root Webhook URL", bot_page)

        save_response = self.client.post(
            "/admin/settings/bots",
            data={
                "discord_bot_token": "discord-token",
                "discord_application_id": "app-123",
                "discord_guild_id": "guild-123",
                "discord_status_channel_id": "channel-123",
                "discord_webhook_url": "https://discord.example/webhook",
                "discord_webhook_username": "Tracker Bot",
                "root_webhook_url": "https://root.example/webhook",
                "root_webhook_name": "Root Bot",
                "submit": "Save Bot Integrations",
            },
            follow_redirects=False,
        )
        self.assertEqual(save_response.status_code, 302)
        with self.app.app_context():
            values = {item.key: item.value for item in NotificationConfig.query.all()}
        self.assertEqual(values["discord_bot_token"], "discord-token")
        self.assertEqual(values["discord_status_channel_id"], "channel-123")
        self.assertEqual(values["root_webhook_url"], "https://root.example/webhook")

        sync_response = self.client.post(
            "/admin/settings/bots/discord/sync-commands",
            follow_redirects=False,
        )
        self.assertEqual(sync_response.status_code, 302)
        self.assertIn("/admin/settings/bots", sync_response.headers.get("Location", ""))
        with self.app.app_context():
            request_id = NotificationConfig.query.filter_by(
                key="discord_command_sync_request_id"
            ).first()
            sync_status = NotificationConfig.query.filter_by(
                key="discord_command_sync_status"
            ).first()
        self.assertIsNotNone(request_id)
        self.assertTrue(request_id.value)
        self.assertIn("Waiting for the Discord worker", sync_status.value)

        telegram_save = self.client.post(
            "/admin/settings/bots",
            data={
                "telegram_bot_token": "telegram-token",
                "telegram_bot_username": "tracker_bot",
                "telegram_webhook_url": "https://group-tests.example/telegram/webhook",
                "telegram_webhook_secret": "webhook-secret",
                "telegram_webhook_allowed_ips": "149.154.160.0/20",
                "telegram_status_chat_id": "-100123",
                "telegram_digest_enabled": "y",
                "telegram_digest_window_minutes": "10",
                "service_base_url": "https://group-tests.example",
                "submit": "Save Bot Integrations",
            },
            follow_redirects=False,
        )
        self.assertEqual(telegram_save.status_code, 302)
        with self.app.app_context():
            values = {item.key: item.value for item in NotificationConfig.query.all()}
        self.assertEqual(values["telegram_bot_token"], "telegram-token")
        self.assertEqual(values["telegram_webhook_secret"], "webhook-secret")
        self.assertEqual(values["telegram_status_chat_id"], "-100123")

        command_response = self.client.get("/admin/settings/commands", follow_redirects=False)
        self.assertEqual(command_response.status_code, 302)
        self.assertIn("/admin/telegram-command-templates", command_response.headers.get("Location", ""))

        builtin_response = self.client.get("/admin/settings/commands/builtins")
        self.assertEqual(builtin_response.status_code, 200)
        self.assertIn("Enable /publicresults", builtin_response.get_data(as_text=True))
        disabled_response = self.client.post(
            "/admin/settings/commands/builtins",
            data={
                "tests_enabled": "y",
                "mytests_enabled": "y",
                "status_enabled": "y",
                "join_enabled": "y",
                "publicresults_enabled": "",
                "publicresults_allow_non_private": "",
                "publicresults_allowed_chat_ids": "",
                "publicresults_allowed_thread_ids": "",
                "submit": "Save Built-in Command Settings",
            },
            follow_redirects=False,
        )
        self.assertEqual(disabled_response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(NotificationConfig.query.filter_by(key="builtin_publicresults_enabled").first().value, "false")

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

    def test_admin_user_forms_persist_discord_username_and_show_link_status(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="discord-admin", email="discord-admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"username": "discord-admin", "password": "secret"}, follow_redirects=True)
        response = self.client.post(
            "/admin/users/new",
            data={
                "username": "discord-user",
                "email": "discord-user@example.com",
                "tg_username": "",
                "discord_username": "Discord Display",
                "is_admin": "",
                "is_active": "y",
                "receive_group_test_notifications": "y",
                "notification_channel": "discord",
                "digest_frequency": "off",
                "password": "secret123",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            user = User.query.filter_by(username="discord-user").first()
            self.assertEqual(user.discord_username, "Discord Display")
            user.telegram_chat_id = "tg-chat-1"
            user.telegram_user_id = "tg-user-1"
            user.discord_user_id = "discord-user-1"
            password_hash = user.password_hash
            db.session.commit()
            user_id = user.id

        edit_page = self.client.get(f"/admin/users/{user_id}/edit")
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn("Telegram:", edit_page.get_data(as_text=True))
        self.assertIn("Discord:", edit_page.get_data(as_text=True))

        edit_response = self.client.post(
            f"/admin/users/{user_id}/edit",
            data={
                "username": "discord-user",
                "email": "discord-user@example.com",
                "tg_username": "",
                "discord_username": "Updated Discord Display",
                "is_admin": "",
                "is_active": "y",
                "receive_group_test_notifications": "y",
                "notification_channel": "discord",
                "digest_frequency": "off",
                "password": "",
            },
            follow_redirects=True,
        )
        self.assertEqual(edit_response.status_code, 200)
        self.assertIn("Updated Discord Display", edit_response.get_data(as_text=True))
        with self.app.app_context():
            refreshed = User.query.get(user_id)
            self.assertEqual(refreshed.telegram_chat_id, "tg-chat-1")
            self.assertEqual(refreshed.telegram_user_id, "tg-user-1")
            self.assertEqual(refreshed.discord_user_id, "discord-user-1")
            self.assertEqual(refreshed.password_hash, password_hash)

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

    def test_telegram_webhook_requires_configured_secret(self):
        with self.app.app_context():
            db.create_all()
            NotificationConfig.query.filter_by(key="telegram_webhook_secret").delete()
            db.session.commit()

        # Use a raw client here since self.client.post auto-seeds the webhook
        # secret for convenience in other tests, which would defeat this test.
        raw_client = self.app.test_client()
        response = raw_client.post(
            "/telegram/webhook",
            json={"message": {"chat": {"id": 1001}, "text": "/help"}},
        )
        self.assertEqual(response.status_code, 503)

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

    def test_admin_can_create_telegram_command_template(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)
        response = self.client.post(
            "/admin/telegram-command-templates",
            data={
                "command": "pricecheck",
                "description": "Show quick payment guidance",
                "reply_text": "Hi {{ username }}, use /mytests to check your active tests.",
                "is_active": "y",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Telegram command template created.", response.get_data(as_text=True))
        with self.app.app_context():
            template = TelegramCommandTemplate.query.filter_by(command="/pricecheck").first()
            self.assertIsNotNone(template)
            self.assertTrue(template.is_active)

    def test_admin_cannot_create_reserved_telegram_command_template(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)
        response = self.client.post(
            "/admin/telegram-command-templates",
            data={
                "command": "/help",
                "description": "Attempt to override",
                "reply_text": "Nope",
                "is_active": "y",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("That command is reserved by built-in bot behavior.", response.get_data(as_text=True))
        with self.app.app_context():
            template = TelegramCommandTemplate.query.filter_by(command="/help").first()
            self.assertIsNone(template)

    def test_telegram_webhook_executes_custom_command_template_reply(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="tgcustom", email="tgcustom@example.com", telegram_chat_id="3003", telegram_user_id="999")
            user.set_password("secret")
            db.session.add(user)
            db.session.add(
                TelegramCommandTemplate(
                    command="/pricecheck",
                    description="Custom price response",
                    reply_text="Hi {{ username }} ({{ tg_username }}), args={{ args }}.",
                    is_active=True,
                )
            )
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": 3003, "type": "private"},
                        "from": {"id": 999, "username": "tgcustomname"},
                        "text": "/pricecheck now",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once()
        sent_body = mock_send.call_args.args[1]
        self.assertIn("Hi tgcustom (tgcustomname), args=now.", sent_body)

    def test_telegram_webhook_custom_command_requires_arguments(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="tgargs", email="tgargs@example.com", telegram_chat_id="4040", telegram_user_id="14040")
            user.set_password("secret")
            db.session.add(user)
            db.session.add(
                TelegramCommandTemplate(
                    command="/pricecheck",
                    args_policy="required",
                    args_help_text="Usage: /pricecheck <code>",
                    reply_text="ok",
                    is_active=True,
                )
            )
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": 4040, "type": "private"},
                        "from": {"id": 14040, "username": "tgargs"},
                        "text": "/pricecheck",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once()
        self.assertIn("Usage: /pricecheck <code>", mock_send.call_args.args[1])

    def test_public_results_query_excludes_group_tests_and_orders_results(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="public-admin", email="public-admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.flush()
            public_tag = Tag(name="Alpha", normalized_name="alpha")
            db.session.add(public_tag)
            db.session.flush()
            older = PublicResult(
                title="Older COA",
                results_link="https://coa.example/older",
                created_by=admin.id,
                tags=[public_tag],
            )
            newer = PublicResult(
                title="Newer COA",
                results_link="https://coa.example/newer",
                created_by=admin.id,
                tags=[public_tag],
            )
            group_test = GroupTest(title="Private Group Test", created_by=admin.id)
            db.session.add_all([older, newer, group_test])
            db.session.commit()

            tags, tag_page, tag_pages = public_result_tag_page()
            tag, results, result_page, result_pages = public_results_for_tag_page(public_tag.id)

        self.assertEqual([item.name for item in tags], ["Alpha"])
        self.assertEqual((tag_page, tag_pages), (1, 1))
        self.assertEqual(tag.name, "Alpha")
        self.assertEqual([item.title for item in results], ["Newer COA", "Older COA"])
        self.assertEqual((result_page, result_pages), (1, 1))

    def test_public_results_tag_pagination_has_all_tags_on_final_page(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="pagination-admin", email="pagination-admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.flush()
            for index in range(13):
                tag = Tag(name=f"Tag {index + 1:02d}", normalized_name=f"tag-{index + 1:02d}")
                db.session.add(tag)
                db.session.flush()
                db.session.add(PublicResult(
                    title=f"COA {index + 1}",
                    results_link=f"https://coa.example/{index + 1}",
                    created_by=admin.id,
                    tags=[tag],
                ))
            db.session.commit()

            first_tags, first_page, total_pages = public_result_tag_page(1)
            second_tags, second_page, _ = public_result_tag_page(2)

        self.assertEqual(total_pages, 2)
        self.assertEqual((first_page, second_page), (1, 2))
        self.assertEqual(len(first_tags), 10)
        self.assertEqual(len(second_tags), 3)
        self.assertEqual([tag.name for tag in second_tags], ["Tag 11", "Tag 12", "Tag 13"])

    def test_telegram_public_results_requires_linked_private_user_and_sends_coa_buttons(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="public-tg", email="public-tg@example.com", telegram_chat_id="711", telegram_user_id="811")
            user.set_password("secret")
            admin = User(username="public-tg-admin", email="public-tg-admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add_all([user, admin])
            db.session.flush()
            tag = Tag(name="Alpha", normalized_name="alpha")
            db.session.add(tag)
            db.session.flush()
            db.session.add(PublicResult(title="Alpha COA", results_link="https://coa.example/alpha", created_by=admin.id, tags=[tag]))
            db.session.add(TelegramCommandTemplate(command="/publicresults", allow_non_private=False, is_active=True, reply_text="unused"))
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": 711, "type": "private"},
                        "from": {"id": 811, "username": "public-tg"},
                        "text": "/publicresults",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once()
        body = mock_send.call_args.args[1]
        markup = mock_send.call_args.kwargs["reply_markup"]
        self.assertIn("Public Result Tags", body)
        self.assertEqual(markup["inline_keyboard"][0][0]["text"], "Alpha")
        self.assertNotIn("Private Group Test", body)

        with self.app.app_context():
            unlinked = User(username="unlinked-tg", email="unlinked-tg@example.com")
            unlinked.set_password("secret")
            db.session.add(unlinked)
            db.session.commit()
        with patch("app.routes.send_telegram_chat_message") as unlinked_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": 712, "type": "private"},
                        "from": {"id": 812, "username": "unlinked-tg"},
                        "text": "/publicresults",
                    }
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("not linked", unlinked_send.call_args.args[1].lower())

    @patch("app.routes._queue_uploaded_result_analysis")
    @patch("app.routes.upload_result_image", return_value="result-images/public-results/file-only.pdf")
    def test_public_result_form_allows_file_without_link(self, upload_image, queue_analysis):
        with self.app.app_context():
            db.create_all()
            admin = User(username="file-form-admin", email="file-form-admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"username": "file-form-admin", "password": "secret"})
        response = self.client.post(
            "/admin/public-results",
            data={
                "title": "File-only result",
                "results_link": "",
                "summary": "",
                "tag_names": "",
                "results_image": (io.BytesIO(b"pdf-bytes"), "certificate.pdf"),
                "submit": "Save Public Result",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        upload_image.assert_called_once()
        with self.app.app_context():
            result = PublicResult.query.filter_by(title="File-only result").one()
            self.assertIsNone(result.results_link)
            self.assertEqual(result.results_image_key, "result-images/public-results/file-only.pdf")

    def test_public_result_form_rejects_missing_link_and_file(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="empty-form-admin", email="empty-form-admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"username": "empty-form-admin", "password": "secret"})
        response = self.client.post(
            "/admin/public-results",
            data={"title": "Missing source", "results_link": "", "summary": "", "tag_names": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Provide a results link or upload an image/PDF.", response.get_data(as_text=True))

    def test_telegram_public_results_tag_click_handles_image_only_certificate(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="image-only-tg", email="image-only-tg@example.com", telegram_chat_id="721", telegram_user_id="821")
            user.set_password("secret")
            admin = User(username="image-only-admin", email="image-only-admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add_all([user, admin])
            db.session.flush()
            tag = Tag(name="Image Only", normalized_name="image-only")
            result = PublicResult(
                title="Bot Certificate", results_link=None,
                results_image_key="result-images/public-results/certificate.pdf",
                created_by=admin.id, publication_status="published", tags=[tag],
            )
            db.session.add(result)
            db.session.commit()
            tag_id = tag.id
            result_id = result.id

        with patch("app.routes.edit_telegram_message") as edit_message, \
                patch("app.routes.answer_telegram_callback_query"):
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "callback_query": {
                        "id": "callback-image-only",
                        "from": {"id": 821},
                        "message": {"message_id": 55, "chat": {"id": 721, "type": "private"}},
                        "data": f"pr:results:{tag_id}:1",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        edit_message.assert_called_once()
        markup = edit_message.call_args.kwargs["reply_markup"]
        result_button = markup["inline_keyboard"][0][0]
        self.assertTrue(result_button["url"].endswith(f"/public-results/{result_id}"))
        self.assertTrue(result_button["url"].startswith("https://"))

    def test_telegram_public_results_treats_hash_link_as_missing(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="hash-link-admin", email="hash-link-admin@example.com", is_admin=True)
            admin.set_password("secret")
            user = User(username="hash-link-user", email="hash-link-user@example.com", telegram_chat_id="741", telegram_user_id="841")
            user.set_password("secret")
            tag = Tag(name="Hash Link", normalized_name="hash-link")
            db.session.add_all([admin, user, tag])
            db.session.flush()
            result = PublicResult(title="Hash Link COA", results_link="#", created_by=admin.id, tags=[tag])
            db.session.add(result)
            db.session.commit()
            tag_id = tag.id
            result_id = result.id

        with patch("app.routes.edit_telegram_message") as edit_message, \
                patch("app.routes.answer_telegram_callback_query"):
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "callback_query": {
                        "id": "callback-hash-link",
                        "from": {"id": 841},
                        "message": {"message_id": 56, "chat": {"id": 741, "type": "private"}},
                        "data": f"pr:results:{tag_id}:1",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        result_button = edit_message.call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]
        self.assertTrue(result_button["url"].endswith(f"/public-results/{result_id}"))

    def test_telegram_public_results_sends_new_message_when_edit_fails(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="fallback-admin", email="fallback-admin@example.com", is_admin=True)
            admin.set_password("secret")
            user = User(username="fallback-user", email="fallback-user@example.com", telegram_chat_id="731", telegram_user_id="831")
            user.set_password("secret")
            tag = Tag(name="Fallback Tag", normalized_name="fallback-tag")
            db.session.add_all([admin, user, tag])
            db.session.flush()
            result = PublicResult(title="Fallback COA", results_link=None, created_by=admin.id, tags=[tag])
            db.session.add(result)
            db.session.commit()
            tag_id = tag.id

        with patch("app.routes.edit_telegram_message", return_value=False), \
                patch("app.routes.send_telegram_chat_message", return_value=True) as send_message:
            with self.app.test_request_context('/telegram/webhook'):
                handled = _process_public_results_telegram(
                    User.query.filter_by(telegram_user_id="831").first(),
                    "731", "private", tag_id=tag_id, page=1, message_id=55,
                )
        self.assertTrue(handled)
        send_message.assert_called_once()

    def test_telegram_public_results_allows_scoped_group_user_without_link(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="group-public-admin", email="group-public-admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.flush()
            tag = Tag(name="Group Alpha", normalized_name="group-alpha")
            db.session.add(tag)
            db.session.flush()
            db.session.add(PublicResult(title="Group Channel COA", results_link="https://coa.example/group", created_by=admin.id, tags=[tag]))
            db.session.add_all([
                NotificationConfig(key="builtin_publicresults_allow_non_private", value="true"),
                NotificationConfig(key="builtin_publicresults_allowed_chat_ids", value="-100777"),
            ])
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": -100777, "type": "supergroup"},
                        "from": {"id": 99977, "username": "unlinked-member"},
                        "text": "/publicresults",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["text"], "Group Alpha")

    def test_telegram_unknown_group_command_does_not_open_public_results(self):
        with self.app.app_context():
            db.create_all()
            db.session.add(NotificationConfig(key="builtin_publicresults_allow_non_private", value="true"))
            db.session.add(NotificationConfig(key="builtin_publicresults_allowed_chat_ids", value="-100888"))
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": -100888, "type": "supergroup"},
                        "from": {"id": 99888, "username": "unknown-command-user"},
                        "text": "/testme",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_send.assert_not_called()

    def test_telegram_linked_admin_reply_replaces_command_response_exactly(self):
        with self.app.app_context():
            db.create_all()
            admin = User(
                username="command-admin",
                email="command-admin@example.com",
                is_admin=True,
                telegram_user_id="9001",
                telegram_chat_id="-1009001",
            )
            admin.set_password("secret")
            db.session.add(admin)
            db.session.flush()
            template = TelegramCommandTemplate(
                command="/groupbuy",
                reply_text="Old text",
                response_image_key="bot-commands/old.jpg",
                allow_admin_bot_updates=True,
                is_active=True,
            )
            db.session.add(template)
            db.session.flush()
            db.session.add(BotCommandMessage(
                command_template_id=template.id,
                provider="telegram",
                chat_id="-1009001",
                message_id="77",
            ))
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send, patch("app.routes.delete_result_image") as mock_delete:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": -1009001, "type": "supergroup"},
                        "from": {"id": 9001, "username": "command-admin"},
                        "text": "Updated text only",
                        "reply_to_message": {"message_id": 77, "from": {"is_bot": True}},
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Command response updated", mock_send.call_args.args[1])
        mock_delete.assert_called_once_with("bot-commands/old.jpg")
        with self.app.app_context():
            refreshed = TelegramCommandTemplate.query.filter_by(command="/groupbuy").first()
            self.assertEqual(refreshed.reply_text, "Updated text only")
            self.assertIsNone(refreshed.response_image_key)

    def test_telegram_admin_reply_stays_in_originating_message_thread(self):
        with self.app.app_context():
            db.create_all()
            admin = User(
                username="thread-admin",
                email="thread-admin@example.com",
                is_admin=True,
                telegram_user_id="9002",
                telegram_chat_id="-1009002",
            )
            admin.set_password("secret")
            db.session.add(admin)
            db.session.flush()
            template = TelegramCommandTemplate(
                command="/groupbuy",
                reply_text="Old text",
                allow_admin_bot_updates=True,
                is_active=True,
            )
            db.session.add(template)
            db.session.flush()
            db.session.add(BotCommandMessage(
                command_template_id=template.id,
                provider="telegram",
                chat_id="-1009002",
                message_id="88",
            ))
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": -1009002, "type": "supergroup"},
                        "from": {"id": 9002, "username": "thread-admin"},
                        "text": "Updated in-thread text",
                        "message_thread_id": 42,
                        "reply_to_message": {"message_id": 88, "from": {"is_bot": True}},
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_send.call_args.kwargs.get("message_thread_id"), 42)

    def test_telegram_admin_reply_with_animation_updates_command_image(self):
        with self.app.app_context():
            db.create_all()
            admin = User(
                username="gif-admin",
                email="gif-admin@example.com",
                is_admin=True,
                telegram_user_id="9003",
                telegram_chat_id="-1009003",
            )
            admin.set_password("secret")
            db.session.add(admin)
            db.session.flush()
            template = TelegramCommandTemplate(
                command="/groupbuy",
                reply_text="Old text",
                allow_admin_bot_updates=True,
                is_active=True,
            )
            db.session.add(template)
            db.session.flush()
            db.session.add(BotCommandMessage(
                command_template_id=template.id,
                provider="telegram",
                chat_id="-1009003",
                message_id="99",
            ))
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send, \
                patch("app.routes.download_telegram_photo") as mock_download, \
                patch("app.routes.upload_telegram_animation") as mock_upload:
            mock_download.return_value = object()
            mock_upload.return_value = "bot-commands/new.mp4"
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": -1009003, "type": "supergroup"},
                        "from": {"id": 9003, "username": "gif-admin"},
                        "animation": {"file_id": "anim-file-id"},
                        "reply_to_message": {"message_id": 99, "from": {"is_bot": True}},
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_download.assert_called_once_with("anim-file-id")
        mock_upload.assert_called_once()
        self.assertIn("Command response updated", mock_send.call_args.args[1])
        with self.app.app_context():
            refreshed = TelegramCommandTemplate.query.filter_by(command="/groupbuy").first()
            self.assertEqual(refreshed.response_image_key, "bot-commands/new.mp4")

    def test_telegram_public_results_callback_edits_to_coa_links(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="callback-admin", email="callback-admin@example.com", is_admin=True)
            admin.set_password("secret")
            user = User(username="callback-user", email="callback-user@example.com", telegram_chat_id="733", telegram_user_id="833")
            user.set_password("secret")
            db.session.add_all([admin, user])
            db.session.flush()
            tag = Tag(name="Callback", normalized_name="callback")
            db.session.add(tag)
            db.session.flush()
            result = PublicResult(title="Callback COA", results_link="https://coa.example/callback", created_by=admin.id, tags=[tag])
            db.session.add(result)
            db.session.add(TelegramCommandTemplate(command="/publicresults", is_active=True, reply_text="unused"))
            db.session.commit()
            tag_id = tag.id

        with patch("app.routes.answer_telegram_callback_query") as mock_answer, patch("app.routes.edit_telegram_message") as mock_edit:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "callback_query": {
                        "id": "callback-1",
                        "from": {"id": 833},
                        "data": f"pr:results:{tag_id}:1",
                        "message": {"message_id": 44, "chat": {"id": 733, "type": "private"}},
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_answer.assert_called_once_with("callback-1")
        mock_edit.assert_called_once()
        self.assertIn("Callback COA", mock_edit.call_args.args[2])
        self.assertEqual(mock_edit.call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["url"], "https://coa.example/callback")

    def test_telegram_public_results_close_deletes_message(self):
        with self.app.app_context():
            db.create_all()
            db.session.add(NotificationConfig(key="builtin_publicresults_enabled", value="true"))
            db.session.commit()

        with patch("app.routes.answer_telegram_callback_query") as mock_answer, patch("app.routes.delete_telegram_message", return_value=True) as mock_delete:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "callback_query": {
                        "id": "close-1",
                        "data": "pr:close",
                        "message": {"message_id": 55, "chat": {"id": 755, "type": "private"}},
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_answer.assert_called_once_with("close-1")
        mock_delete.assert_called_once_with("755", 55)

    def test_public_results_empty_state(self):
        with self.app.app_context():
            db.create_all()
            from app.routes import _public_results_telegram_view
            body, keyboard = _public_results_telegram_view()

        self.assertEqual(body, "No Public Results Available.")
        self.assertIsNone(keyboard)

    def test_telegram_webhook_custom_command_regex_arguments(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="tgregex", email="tgregex@example.com", telegram_chat_id="5050", telegram_user_id="15050")
            user.set_password("secret")
            db.session.add(user)
            db.session.add(
                TelegramCommandTemplate(
                    command="/order",
                    args_policy="regex",
                    args_regex=r"^[0-9]{4}$",
                    args_help_text="Usage: /order 4-digit-id",
                    reply_text="Order {{ args }} accepted",
                    is_active=True,
                )
            )
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            bad = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": 5050, "type": "private"},
                        "from": {"id": 15050, "username": "tgregex"},
                        "text": "/order ABCD",
                    }
                },
            )
        self.assertEqual(bad.status_code, 200)
        self.assertIn("Usage: /order 4-digit-id", mock_send.call_args.args[1])

        with patch("app.routes.send_telegram_chat_message") as mock_send_ok:
            good = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": 5050, "type": "private"},
                        "from": {"id": 15050, "username": "tgregex"},
                        "text": "/order 1234",
                    }
                },
            )
        self.assertEqual(good.status_code, 200)
        self.assertIn("Order 1234 accepted", mock_send_ok.call_args.args[1])

    def test_telegram_webhook_custom_command_rate_limit_blocks_excess_calls(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="tglimit", email="tglimit@example.com", telegram_chat_id="6060", telegram_user_id="16060")
            user.set_password("secret")
            db.session.add(user)
            db.session.add(
                TelegramCommandTemplate(
                    command="/quote",
                    rate_limit_window_seconds=60,
                    rate_limit_max_calls=1,
                    rate_limit_message="Slow down on {{ command }}",
                    reply_text="Quote delivered",
                    is_active=True,
                )
            )
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as first_send:
            first = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": 6060, "type": "private"},
                        "from": {"id": 16060, "username": "tglimit"},
                        "text": "/quote",
                    }
                },
            )
        self.assertEqual(first.status_code, 200)
        self.assertIn("Quote delivered", first_send.call_args.args[1])

        with patch("app.routes.send_telegram_chat_message") as second_send:
            second = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": 6060, "type": "private"},
                        "from": {"id": 16060, "username": "tglimit"},
                        "text": "/quote",
                    }
                },
            )
        self.assertEqual(second.status_code, 200)
        self.assertIn("Slow down on /quote", second_send.call_args.args[1])

        with self.app.app_context():
            invocations = TelegramCommandInvocation.query.all()
            self.assertEqual(len(invocations), 1)

    def test_admin_can_persist_custom_command_chat_thread_scope_controls(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="adminscope", email="adminscope@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"username": "adminscope", "password": "secret"}, follow_redirects=True)
        response = self.client.post(
            "/admin/telegram-command-templates",
            data={
                "command": "/groupinfo",
                "category": "ops",
                "description": "Scoped group command",
                "args_policy": "none",
                "args_regex": "",
                "args_help_text": "",
                "rate_limit_window_seconds": "",
                "rate_limit_max_calls": "",
                "rate_limit_message": "",
                "allow_non_private": "y",
                "allowed_chat_ids": "-100123,-100456",
                "allowed_thread_ids": "2,14",
                "reply_text": "Scoped",
                "is_active": "y",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            template = TelegramCommandTemplate.query.filter_by(command="/groupinfo").first()
            self.assertIsNotNone(template)
            self.assertTrue(template.allow_non_private)
            self.assertEqual(template.allowed_chat_ids, "-100123,-100456")
            self.assertEqual(template.allowed_thread_ids, "2,14")

    def test_telegram_webhook_custom_command_allows_configured_group_and_thread(self):
        with self.app.app_context():
            db.create_all()
            db.session.add(
                TelegramCommandTemplate(
                    command="/groupinfo",
                    allow_non_private=True,
                    allowed_chat_ids="-100333",
                    allowed_thread_ids="42",
                    reply_text="Group command OK",
                    is_active=True,
                )
            )
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": -100333, "type": "supergroup"},
                        "message_thread_id": 42,
                        "text": "/groupinfo",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_send.assert_called_once()
        self.assertIn("Group command OK", mock_send.call_args.args[1])
        self.assertEqual(mock_send.call_args.kwargs.get("message_thread_id"), 42)

    def test_telegram_webhook_custom_command_ignores_disallowed_group_thread_scope(self):
        with self.app.app_context():
            db.create_all()
            db.session.add(
                TelegramCommandTemplate(
                    command="/groupinfo",
                    allow_non_private=True,
                    allowed_chat_ids="-100333",
                    allowed_thread_ids="42",
                    reply_text="Group command OK",
                    is_active=True,
                )
            )
            db.session.commit()

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": -100333, "type": "supergroup"},
                        "message_thread_id": 99,
                        "text": "/groupinfo",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        mock_send.assert_not_called()

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
        self.assertIn(f"/status_{test_one.id}", sent_body)
        self.assertIn(f"/join_{test_one.id}", sent_body)
        self.assertIn(f"/status_{test_two.id}", sent_body)
        self.assertNotIn(f"/join_{test_two.id}", sent_body)

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
            pending_id = test_pending.id
            denied_id = test_denied.id
            approved_id = test_approved.id

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
        self.assertIn(f"#{pending_id} Pending Test [Recruiting] - Pending", sent_body)
        self.assertIn(f"#{denied_id} Denied Test [Testing] - Denied", sent_body)
        self.assertIn(f"#{approved_id} Approved Test [Closed] - Approved", sent_body)
        self.assertNotIn("Unrelated Test", sent_body)
        self.assertIn(f"/status_{pending_id}", sent_body)
        self.assertIn(f"/status_{denied_id}", sent_body)
        self.assertIn(f"/status_{approved_id}", sent_body)
        self.assertNotIn(f"/join_{pending_id}", sent_body)

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
                        "text": f"/status_{test_id}",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        sent_body = mock_send.call_args.args[1]
        self.assertIn(f"#{test_id} Denied Status Test: Denied.", sent_body)
        self.assertIn("Need more verification", sent_body)

    def test_telegram_join_command_accepts_underscored_clickable_form(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="tgjoin", email="tgjoin@example.com", telegram_chat_id="4004", telegram_user_id="999")
            user.set_password("secret")
            owner = User(username="owner", email="owner@example.com", is_admin=True)
            owner.set_password("secret")
            db.session.add_all([user, owner])
            db.session.flush()

            test = GroupTest(title="Clickable Join Test", status="recruiting", created_by=owner.id)
            db.session.add(test)
            db.session.commit()
            test_id = test.id

        with patch("app.routes.send_telegram_chat_message") as mock_send:
            response = self.client.post(
                "/telegram/webhook",
                json={
                    "message": {
                        "chat": {"id": 4004},
                        "from": {"id": 999, "username": "tgjoin"},
                        "text": f"/join_{test_id}",
                    }
                },
            )

        self.assertEqual(response.status_code, 200)
        sent_body = mock_send.call_args.args[1]
        self.assertIn(f"Request submitted for #{test_id} Clickable Join Test.", sent_body)

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
        self.assertEqual(profile["link_type"], "web")
        self.assertEqual(profile["copy_value"], expected_link)

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
        self.assertEqual(profile["link_type"], "uri")
        self.assertEqual(profile["mobile_action_label"], "Open wallet")
        self.assertEqual(profile["copy_value"], "ethereum:0xabc123")

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
        self.assertIn("Open payment app", body)
        self.assertIn("data-copy-value=\"https://venmo.com/collector\"", body)
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
            response = self.client.post("/admin/telegram-config/webhook/register", follow_redirects=True)

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
        response = self.client.post("/admin/telegram-config/webhook/register", follow_redirects=True)

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
            response = self.client.post("/admin/telegram-config/webhook/unregister", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Telegram webhook unregistered successfully.", body)
        self.assertTrue(mock_unregister.called)

    def test_legacy_notification_config_webhook_routes_are_not_available(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.add(NotificationConfig(key="telegram_bot_token", value="123456:ABC"))
            db.session.commit()

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)
        register_response = self.client.post("/admin/notification-config/telegram-webhook/register", follow_redirects=False)
        unregister_response = self.client.post("/admin/notification-config/telegram-webhook/unregister", follow_redirects=False)

        self.assertEqual(register_response.status_code, 404)
        self.assertEqual(unregister_response.status_code, 404)

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

        response_get = self.client.get("/admin/telegram-config")
        self.assertEqual(response_get.status_code, 200)
        body = response_get.get_data(as_text=True)
        self.assertIn("1234", body)
        self.assertIn("REALTOKEN"[-6:], body)

        response_post = self.client.post(
            "/admin/telegram-config",
            data={
                "telegram_bot_token": mask_secret("123456:REALTOKEN"),
                "telegram_bot_username": "",
                "telegram_webhook_url": "",
                "telegram_webhook_secret": "",
                "telegram_webhook_allowed_ips": "",
                "telegram_status_chat_id": "",
                "telegram_digest_enabled": "",
                "telegram_digest_window_minutes": "10",
                "service_base_url": "",
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
            "/admin/telegram-config",
            data={
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
