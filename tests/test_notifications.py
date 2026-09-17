import asyncio
import json
import os
import tempfile
import unittest
from io import BytesIO
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from urllib.error import HTTPError
from flask import current_app
from sqlalchemy.exc import IntegrityError

from app import create_app, db
from app.models import GroupTest, NotificationConfig, NotificationTemplate, Participation, PublicResult, TelegramCommandTemplate, TelegramStatusDigestEvent, User, UserDigestEvent
from app.notifications import append_notification_log, read_notification_log, render_notification_template, send_discord_status_channel_message, send_mailjet_message, send_notification_message, send_password_reset, send_telegram_command_response, send_telegram_message, send_telegram_status_channel_message


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

        with patch("app.routes.send_password_reset") as mock_reset:
            response = self.client.post(
                "/password-reset",
                data={"username": "reset_tg", "notification_channel": "telegram"},
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("If an account matches, a password reset message has been sent.", response.get_data(as_text=True))
        mock_reset.assert_not_called()

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

    def test_send_telegram_command_response_uses_send_animation_for_mp4_key(self):
        with self.app.app_context():
            db.create_all()
            db.session.add(NotificationConfig(key="telegram_bot_token", value="123456:ABC"))
            db.session.commit()

            with patch("app.notifications.urlopen") as mock_urlopen, \
                    patch("app.storage.generate_result_image_presigned_url", return_value="https://example.com/a.mp4"):
                response = Mock()
                response.read.return_value = b'{"ok":true,"result":{"message_id":5}}'
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                mock_urlopen.return_value = response

                message_id = send_telegram_command_response("-1001", "caption", image_key="bot-commands/x.mp4")

        self.assertEqual(message_id, "5")
        request = mock_urlopen.call_args.args[0]
        self.assertIn("sendAnimation", request.full_url)
        self.assertIn(b'"animation"', request.data)

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

    def test_send_notification_message_delivers_discord_webhook(self):
        with self.app.app_context():
            db.create_all()
            db.session.add_all([
                NotificationConfig(key="discord_webhook_url", value="https://discord.example/webhook"),
                NotificationConfig(key="discord_webhook_username", value="Tracker Bot"),
            ])
            db.session.commit()

            with patch("app.notifications.post_json", return_value=(True, "ok")) as mock_post:
                result = send_notification_message(
                    User(username="discorder", email="discorder@example.com"),
                    "discord",
                    "Subject",
                    "Discord body",
                )

        self.assertTrue(result)
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.args[0], "https://discord.example/webhook")
        self.assertEqual(mock_post.call_args.args[1]["content"], "Discord body")
        self.assertEqual(mock_post.call_args.args[1]["username"], "Tracker Bot")

    def test_send_notification_message_delivers_root_webhook(self):
        with self.app.app_context():
            db.create_all()
            db.session.add_all([
                NotificationConfig(key="root_webhook_url", value="https://root.example/webhook"),
                NotificationConfig(key="root_webhook_name", value="Tracker Bot"),
            ])
            db.session.commit()

            with patch("app.notifications.post_json", return_value=(True, "ok")) as mock_post:
                result = send_notification_message(
                    User(username="rooter", email="rooter@example.com"),
                    "root",
                    "Subject",
                    "Root body",
                )

        self.assertTrue(result)
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.args[0], "https://root.example/webhook")
        self.assertEqual(mock_post.call_args.args[1]["text"], "Root body")
        self.assertEqual(mock_post.call_args.args[1]["sender"], "Tracker Bot")

    def test_password_reset_uses_email_template_for_email_channel(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="resetter", email="resetter@example.com", notification_channel="email")
            user.set_password("old-password")
            db.session.add_all([
                user,
                NotificationTemplate(
                    name="Reset Templates",
                    email_subject="Reset",
                    email_body="Email password: {{ new_password }}",
                    telegram_body="Telegram password: {{ new_password }}",
                    is_default_password_reset=True,
                    is_active=True,
                ),
            ])
            db.session.commit()

            with patch("app.notifications.send_notification_message", return_value=True) as mock_send:
                self.assertTrue(send_password_reset(user, "new-password"))

        self.assertEqual(mock_send.call_args.args[1], "email")
        self.assertEqual(mock_send.call_args.args[3], "Email password: new-password")

    def test_send_notification_message_routes_discord_to_discord_api(self):
        with self.app.app_context():
            db.create_all()
            user = User(username="discorder", email="discorder@example.com", discord_user_id="987654321")
            user.set_password("secret")
            db.session.add(user)
            db.session.add(NotificationConfig(key="discord_bot_token", value="123456:ABC"))
            db.session.commit()

            with patch("app.notifications.urlopen") as mock_urlopen:
                channel_response = Mock()
                channel_response.read.return_value = b'{"id":"555"}'
                channel_response.__enter__ = Mock(return_value=channel_response)
                channel_response.__exit__ = Mock(return_value=False)

                message_response = Mock()
                message_response.read.return_value = b'{"id":"666"}'
                message_response.__enter__ = Mock(return_value=message_response)
                message_response.__exit__ = Mock(return_value=False)

                mock_urlopen.side_effect = [channel_response, message_response]

                result = send_notification_message(user, "discord", "Subject", "Discord body")

        self.assertTrue(result)
        self.assertEqual(mock_urlopen.call_count, 2)
        first_request = mock_urlopen.call_args_list[0].args[0]
        second_request = mock_urlopen.call_args_list[1].args[0]
        self.assertIn("https://discord.com/api/v10/users/@me/channels", first_request.full_url)
        self.assertIn("https://discord.com/api/v10/channels/555/messages", second_request.full_url)

    def test_send_discord_status_channel_message_posts_to_discord_api(self):
        with self.app.app_context():
            db.create_all()
            db.session.add_all([
                NotificationConfig(key="discord_bot_token", value="123456:ABC"),
                NotificationConfig(key="discord_status_channel_id", value="999888777"),
            ])
            db.session.commit()

            with patch("app.notifications.urlopen") as mock_urlopen:
                response = Mock()
                response.read.return_value = b'{"id":"777"}'
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                mock_urlopen.return_value = response

                result = send_discord_status_channel_message("Discord status")

        self.assertTrue(result)
        request = mock_urlopen.call_args.args[0]
        self.assertIn("https://discord.com/api/v10/channels/999888777/messages", request.full_url)

    def test_discord_bot_lifecycle_helpers_push_application_context(self):
        with patch.dict(os.environ, {'SECRET_KEY': 'test-secret-key'}):
            from app import discord_bot

        def assert_context(value, **kwargs):
            self.assertIs(current_app._get_current_object(), self.app)
            return value

        with patch.object(discord_bot, "APP", self.app), \
             patch.object(discord_bot, "append_notification_log", side_effect=assert_context), \
             patch.object(discord_bot, "send_discord_status_channel_message", side_effect=assert_context):
            self.assertEqual(discord_bot._append_bot_log("ready"), "ready")
            self.assertEqual(discord_bot._send_bot_status_message("connected"), "connected")

    def test_discord_guild_sync_copies_global_commands_before_syncing(self):
        with patch.dict(os.environ, {'SECRET_KEY': 'test-secret-key'}):
            from app import discord_bot

        tree = Mock()
        tree.sync = AsyncMock(side_effect=[[Mock(), Mock()], [Mock(), Mock()]])
        subject = Mock(tree=tree)

        with patch.object(discord_bot, '_config_value', return_value='123456789012345678'):
            commands, scope = asyncio.run(discord_bot.DiscordBot._sync_commands(subject))

        guild = tree.sync.await_args_list[0].kwargs['guild']
        self.assertEqual(guild.id, 123456789012345678)
        tree.clear_commands.assert_called_once_with(guild=guild)
        tree.copy_global_to.assert_called_once_with(guild=guild)
        self.assertEqual(tree.sync.await_count, 2)
        self.assertEqual(tree.sync.await_args_list[0].kwargs, {'guild': guild})
        self.assertEqual(tree.sync.await_args_list[1].kwargs, {})
        self.assertEqual(len(commands), 2)
        self.assertEqual(
            scope,
            'guild 123456789012345678 and 2 global command(s)',
        )

    def test_discord_global_sync_does_not_build_a_guild_tree(self):
        with patch.dict(os.environ, {'SECRET_KEY': 'test-secret-key'}):
            from app import discord_bot

        tree = Mock()
        tree.sync = AsyncMock(return_value=[Mock()])
        subject = Mock(tree=tree)

        with patch.object(discord_bot, '_config_value', return_value=''):
            commands, scope = asyncio.run(discord_bot.DiscordBot._sync_commands(subject))

        tree.sync.assert_awaited_once_with()
        tree.clear_commands.assert_not_called()
        tree.copy_global_to.assert_not_called()
        self.assertEqual(len(commands), 1)
        self.assertEqual(scope, 'global scope')

    def test_discord_worker_processes_a_new_command_sync_request_once(self):
        with patch.dict(os.environ, {'SECRET_KEY': 'test-secret-key'}):
            from app import discord_bot

        subject = Mock()
        subject._last_command_sync_request_id = 'old-request'
        subject._sync_commands = AsyncMock(return_value=([Mock(), Mock(), Mock()], 'guild 123'))
        subject._command_sync_status = discord_bot.DiscordBot._command_sync_status

        with patch.object(
            discord_bot,
            '_run_db',
            new=AsyncMock(side_effect=['new-request', None]),
        ) as mock_run_db, patch.object(discord_bot, '_append_bot_log'):
            processed = asyncio.run(
                discord_bot.DiscordBot._process_pending_command_sync(subject)
            )

        self.assertTrue(processed)
        self.assertEqual(subject._last_command_sync_request_id, 'new-request')
        subject._register_dynamic_commands.assert_called_once_with()
        subject._sync_commands.assert_awaited_once_with()
        self.assertEqual(mock_run_db.await_count, 2)
        self.assertIs(mock_run_db.await_args_list[1].args[0], discord_bot._record_command_sync_result)
        self.assertEqual(mock_run_db.await_args_list[1].args[1], 'new-request')
        self.assertIn('Synchronized 3 command(s) to guild 123', mock_run_db.await_args_list[1].args[2])

    def test_discord_dynamic_command_refresh_removes_stale_commands(self):
        with patch.dict(os.environ, {'SECRET_KEY': 'test-secret-key'}):
            from app import discord_bot

        with self.app.app_context():
            db.create_all()
            db.session.add(TelegramCommandTemplate(
                command='/fresh',
                description='Fresh command',
                reply_text='Fresh response',
                is_active=True,
            ))
            db.session.commit()

        tree = Mock()
        subject = Mock(tree=tree)
        subject._dynamic_command_names = {'stale'}
        with patch.object(discord_bot, 'APP', self.app):
            discord_bot.DiscordBot._register_dynamic_commands(subject)

        tree.remove_command.assert_called_once_with('stale')
        tree.add_command.assert_called_once()
        self.assertEqual(tree.add_command.call_args.args[0].name, 'fresh')
        self.assertEqual(subject._dynamic_command_names, {'fresh'})

    def test_discord_media_only_custom_command_reads_bounded_attachment(self):
        with patch.dict(os.environ, {'SECRET_KEY': 'test-secret-key'}):
            from app import discord_bot

        with self.app.app_context():
            db.create_all()
            user = User(
                username='discord-media',
                email='discord-media@example.com',
                discord_user_id='4455',
            )
            user.set_password('secret')
            template = TelegramCommandTemplate(
                command='/groupbuy',
                reply_text='',
                response_image_key='result-images/bot-commands/example.mp4',
                is_active=True,
            )
            db.session.add_all([user, template])
            db.session.commit()
            template_id = template.id

            with patch.object(
                discord_bot,
                'read_result_file',
                return_value=(b'video-bytes', 'video/mp4'),
            ) as mock_read:
                response = discord_bot._run_dynamic_command(
                    template_id,
                    '4455',
                    'Discord Media',
                    '7788',
                    None,
                    '',
                )

        mock_read.assert_called_once_with(
            'result-images/bot-commands/example.mp4',
            discord_bot.DISCORD_COMMAND_MEDIA_MAX_BYTES,
        )
        self.assertEqual(response['media_bytes'], b'video-bytes')
        self.assertEqual(response['content'], '')
        self.assertEqual(response['media_filename'], 'command-media.mp4')

    def test_discord_custom_command_media_failure_preserves_text_or_fallback(self):
        with patch.dict(os.environ, {'SECRET_KEY': 'test-secret-key'}):
            from app import discord_bot

        with self.app.app_context():
            db.create_all()
            user = User(
                username='discord-media-failure',
                email='discord-media-failure@example.com',
                discord_user_id='5566',
            )
            user.set_password('secret')
            template = TelegramCommandTemplate(
                command='/groupbuy',
                reply_text='',
                response_image_key='private/command.gif',
                is_active=True,
            )
            text_template = TelegramCommandTemplate(
                command='/groupbuytext',
                reply_text='The group buy is open.',
                response_image_key='private/command.gif',
                is_active=True,
            )
            db.session.add_all([user, template, text_template])
            db.session.commit()

            with patch.object(
                discord_bot,
                'read_result_file',
                side_effect=discord_bot.StorageReadError('unavailable'),
            ), patch.object(discord_bot, 'append_notification_log') as mock_log:
                response = discord_bot._run_dynamic_command(
                    template.id,
                    '5566',
                    'Discord Media',
                    '8899',
                    None,
                    '',
                )
                text_response = discord_bot._run_dynamic_command(
                    text_template.id,
                    '5566',
                    'Discord Media',
                    '8899',
                    None,
                    '',
                )

        self.assertEqual(response, 'The configured command media is temporarily unavailable.')
        self.assertEqual(text_response, 'The group buy is open.')
        self.assertEqual(mock_log.call_count, 2)
        self.assertTrue(all(
            'StorageReadError' in call.args[0]
            for call in mock_log.call_args_list
        ))

    def test_discord_custom_command_response_attaches_media_and_disables_mentions(self):
        with patch.dict(os.environ, {'SECRET_KEY': 'test-secret-key'}):
            from app import discord_bot

        async def edit_response():
            interaction = Mock()
            interaction.edit_original_response = AsyncMock()
            await discord_bot._edit_discord_command_response(
                interaction,
                {
                    'content': '@everyone Group buy',
                    'media_bytes': b'GIF89a-media',
                    'media_filename': discord_bot._discord_command_media_filename('../../unsafe.GIF'),
                },
            )
            return interaction

        interaction = asyncio.run(edit_response())
        kwargs = interaction.edit_original_response.await_args.kwargs
        self.assertEqual(kwargs['content'], '@everyone Group buy')
        self.assertEqual(len(kwargs['attachments']), 1)
        self.assertEqual(kwargs['attachments'][0].filename, 'command-media.gif')
        self.assertEqual(kwargs['attachments'][0].fp.read(), b'GIF89a-media')
        self.assertFalse(kwargs['allowed_mentions'].everyone)
        self.assertFalse(kwargs['allowed_mentions'].users)
        self.assertFalse(kwargs['allowed_mentions'].roles)

    def test_discord_public_results_uses_validated_app_url_fallback(self):
        with patch.dict(os.environ, {'SECRET_KEY': 'test-secret-key'}):
            from app import discord_bot

        result = Mock(id=42, results_link='#')
        self.assertEqual(
            discord_bot._discord_public_result_url(result, 'https://tracker.example'),
            'https://tracker.example/public-results/42',
        )
        self.assertIsNone(discord_bot._discord_public_result_url(result, ''))
        result.results_link = 'javascript:alert(1)'
        self.assertIsNone(discord_bot._discord_public_result_url(result, 'not-a-url'))

    def test_discord_public_results_tag_callback_defers_and_handles_missing_links(self):
        with patch.dict(os.environ, {'SECRET_KEY': 'test-secret-key'}):
            from app import discord_bot

        async def run_callback():
            view = discord_bot.PublicResultsView(('tags', 1, 1, [(7, 'Purity')]))
            interaction = Mock()
            interaction.user.id = 11
            interaction.channel_id = 22
            interaction.guild_id = 33
            interaction.response.defer = AsyncMock()
            interaction.edit_original_response = AsyncMock()
            with patch.object(
                discord_bot,
                '_run_db',
                new=AsyncMock(side_effect=[
                    (True, None),
                    ('Public Results', ('results', 7, 1, 1), [('Uploaded COA', None)]),
                ]),
            ):
                await view.children[0].callback(interaction)
            return interaction

        interaction = asyncio.run(run_callback())
        interaction.response.defer.assert_awaited_once_with()
        interaction.edit_original_response.assert_awaited_once()
        rendered_view = interaction.edit_original_response.await_args.kwargs['view']
        self.assertTrue(rendered_view.children[0].disabled)
        self.assertIn('COA unavailable', rendered_view.children[0].label)

    def test_discord_public_results_callback_reports_failure_after_deferring(self):
        with patch.dict(os.environ, {'SECRET_KEY': 'test-secret-key'}):
            from app import discord_bot

        async def run_callback():
            view = discord_bot.PublicResultsView(('tags', 1, 1, [(7, 'Purity')]))
            interaction = Mock()
            interaction.user.id = 11
            interaction.channel_id = 22
            interaction.guild_id = 33
            interaction.response.defer = AsyncMock()
            interaction.edit_original_response = AsyncMock()
            with patch.object(discord_bot, '_run_db', new=AsyncMock(side_effect=RuntimeError)), \
                 patch.object(discord_bot, '_append_bot_log') as mock_log:
                await view.children[0].callback(interaction)
            return interaction, mock_log

        interaction, mock_log = asyncio.run(run_callback())
        interaction.response.defer.assert_awaited_once_with()
        self.assertIn(
            'could not load',
            interaction.edit_original_response.await_args.kwargs['content'].lower(),
        )
        self.assertIn('RuntimeError', mock_log.call_args.args[0])

    def test_send_discord_status_channel_message_disables_mentions_in_payload(self):
        with self.app.app_context():
            db.create_all()
            db.session.add_all([
                NotificationConfig(key="discord_bot_token", value="123456:ABC"),
                NotificationConfig(key="discord_status_channel_id", value="999888777"),
            ])
            db.session.commit()

            with patch("app.notifications.urlopen") as mock_urlopen:
                response = Mock()
                response.read.return_value = b'{"id":"777"}'
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                mock_urlopen.return_value = response

                result = send_discord_status_channel_message("@everyone hello")

        self.assertTrue(result)
        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload.get("allowed_mentions", {}).get("parse"), [])

    def test_send_discord_status_channel_message_retries_on_429(self):
        with self.app.app_context():
            db.create_all()
            db.session.add_all([
                NotificationConfig(key="discord_bot_token", value="123456:ABC"),
                NotificationConfig(key="discord_status_channel_id", value="999888777"),
            ])
            db.session.commit()

            with patch("app.notifications.time.sleep", return_value=None) as mock_sleep, \
                 patch("app.notifications.urlopen") as mock_urlopen:
                rate_limit_error = HTTPError(
                    url="https://discord.com/api/v10/channels/999888777/messages",
                    code=429,
                    msg="Too Many Requests",
                    hdrs={"Retry-After": "0"},
                    fp=BytesIO(b'{"retry_after": 0, "global": false}'),
                )

                success_response = Mock()
                success_response.read.return_value = b'{"id":"777"}'
                success_response.__enter__ = Mock(return_value=success_response)
                success_response.__exit__ = Mock(return_value=False)

                mock_urlopen.side_effect = [rate_limit_error, success_response]

                result = send_discord_status_channel_message("Discord status")

        self.assertTrue(result)
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once()

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
            db.session.add(NotificationConfig(key="service_base_url", value="https://group-tests.example"))
            db.session.commit()

            with patch("app.routes.send_telegram_status_channel_message", return_value=True) as mock_sender:
                _send_status_update_to_telegram(test, "testing")

            self.assertTrue(mock_sender.called)
            sent_body = mock_sender.call_args.args[0]
            self.assertIn("Ready Label Test is now ready for payment", sent_body)
            buttons = mock_sender.call_args.kwargs["buttons"]
            self.assertEqual(buttons, [{
                "label": "View Payment Options",
                "url": "https://group-tests.example/test/1#payment-options",
            }])

    def test_status_digest_adds_closed_view_test_button(self):
        with self.app.app_context():
            from app.routes import _send_status_update_to_telegram

            db.create_all()
            admin = User(username="admin-closed-button", email="admin-closed-button@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.flush()
            test = GroupTest(title="Closed Button Test", status="closed", created_by=admin.id)
            db.session.add(test)
            db.session.add_all([
                NotificationConfig(key="telegram_status_chat_id", value="-10012345"),
                NotificationConfig(key="telegram_digest_enabled", value="false"),
                NotificationConfig(key="service_base_url", value="https://group-tests.example"),
            ])
            db.session.commit()

            with patch("app.routes.send_telegram_status_channel_message", return_value=True) as mock_sender:
                _send_status_update_to_telegram(test, "testing")

        self.assertEqual(mock_sender.call_args.kwargs["buttons"], [{
            "label": "View Test",
            "url": f"https://group-tests.example/test/{test.id}",
        }])

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

    def test_status_digest_prefers_username_without_duplicate_id_mention(self):
        with self.app.app_context():
            from app.routes import _send_status_update_to_telegram

            db.create_all()
            admin = User(username="admin-mention-pref", email="admin-mention-pref@example.com", is_admin=True)
            admin.set_password("secret")
            member = User(
                username="member-human-name",
                email="member-human-name@example.com",
                tg_username="singlemention",
                telegram_user_id="12345678",
            )
            member.set_password("secret")
            db.session.add_all([admin, member])
            db.session.flush()

            test = GroupTest(title="No Duplicate Mention Test", status="ready_for_payment", created_by=admin.id)
            db.session.add(test)
            db.session.flush()

            db.session.add(Participation(
                group_test_id=test.id,
                user_id=member.id,
                approved=True,
                denied=False,
                name="Member",
            ))
            db.session.add(NotificationConfig(key="telegram_status_chat_id", value="-10012345"))
            db.session.add(NotificationConfig(key="telegram_digest_enabled", value="false"))
            db.session.commit()

            with patch("app.routes.send_telegram_status_channel_message", return_value=True) as mock_sender:
                _send_status_update_to_telegram(test, "testing")

            self.assertTrue(mock_sender.called)
            sent_body = mock_sender.call_args.args[0]
            self.assertIn("@singlemention", sent_body)
            self.assertEqual(sent_body.count("@singlemention"), 1)
            self.assertNotIn("tg://user?id=12345678", sent_body)

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

    def test_telegram_status_summary_returns_results_url_for_closed_paid_participant(self):
        with self.app.app_context():
            from app.routes import _telegram_status_summary_for_user

            db.create_all()
            user = User(username="member-results-template", email="member-results-template@example.com")
            user.set_password("secret")
            admin = User(username="admin-results-template", email="admin-results-template@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add_all([user, admin])
            db.session.flush()

            test = GroupTest(
                title="Closed Results Test",
                status="closed",
                results_link="https://example.com/results/closed-results-test",
                created_by=admin.id,
            )
            db.session.add(test)
            db.session.flush()

            db.session.add(Participation(
                group_test_id=test.id,
                user_id=user.id,
                approved=True,
                denied=False,
                paid_lab=True,
                order_status="received",
                amount_owed=20.0,
                amount_paid=20.0,
                name="Member",
            ))
            db.session.commit()

            text = _telegram_status_summary_for_user(user, test)

        self.assertIn("Results are available", text)
        self.assertIn("https://example.com/results/closed-results-test", text)

    def test_telegram_status_summary_uses_custom_results_template(self):
        with self.app.app_context():
            from app.routes import _telegram_status_summary_for_user

            db.create_all()
            user = User(username="member-results-custom", email="member-results-custom@example.com")
            user.set_password("secret")
            admin = User(username="admin-results-custom", email="admin-results-custom@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add_all([user, admin])
            db.session.flush()

            test = GroupTest(
                title="Custom Results Test",
                status="closed",
                results_link="https://example.com/results/custom-results-test",
                created_by=admin.id,
            )
            db.session.add(test)
            db.session.flush()

            db.session.add(Participation(
                group_test_id=test.id,
                user_id=user.id,
                approved=True,
                denied=False,
                paid_lab=True,
                amount_owed=30.0,
                amount_paid=30.0,
                name="Member",
            ))
            db.session.add(NotificationConfig(
                key="telegram_status_user_results_template",
                value="Done {{ test_title }} => {{ results_url }}",
            ))
            db.session.commit()

            text = _telegram_status_summary_for_user(user, test)

        self.assertIn("Done Custom Results Test => https://example.com/results/custom-results-test", text)

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
