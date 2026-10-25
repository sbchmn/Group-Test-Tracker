"""Registration setup lifecycle and duplicate account identity protections."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from flask_migrate import upgrade, downgrade
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import create_app, db
from app.bot_identity import issue_link_token, claim_link_token
from app.models import BotLinkToken, NotificationConfig, User
from app.notifications import send_telegram_message


class RegistrationSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({
            'TESTING': True, 'WTF_CSRF_ENABLED': False,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(self.tmp.name) / 'registration.db'),
            'NOTIFICATION_LOG_PATH': str(Path(self.tmp.name) / 'notifications.log'),
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add_all([
                NotificationConfig(key='telegram_bot_token', value='test-token'),
                NotificationConfig(key='telegram_bot_username', value='test_bot'),
                NotificationConfig(key='discord_bot_token', value='discord-token'),
            ])
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.tmp.cleanup()

    def register(self, **overrides):
        data = dict(username='new-member', email='new@example.com', password='secret123',
                    confirm_password='secret123', notification_channel='telegram')
        data.update(overrides)
        with patch('app.routes.send_notification_message', return_value=True):
            return self.client.post('/register', data=data)

    def login(self, **overrides):
        data = dict(username='new-member', password='secret123')
        data.update(overrides)
        return self.client.post('/login', data=data)

    def test_registration_keeps_email_and_defers_linking_to_normal_login(self):
        self.assertEqual(self.register().location, '/login')
        with self.client.session_transaction() as session:
            self.assertNotIn('_user_id', session)
        with self.app.app_context():
            user = User.query.one()
            self.assertEqual(user.notification_channel, 'email')
            self.assertEqual(user.pending_notification_channel, 'telegram')
            self.assertAlmostEqual((user.notification_setup_expires_at - user.created_at).total_seconds(), 7 * 86400, delta=2)
        self.assertEqual(self.login().location, '/notification-setup')
        page = self.client.get('/notification-setup')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Link Telegram notifications', page.data)
        self.assertIn(b'Use email instead', page.data)

    def test_email_selection_never_prompts(self):
        self.register(notification_channel='email')
        self.assertEqual(self.login().location, '/dashboard')
        self.assertEqual(self.client.get('/notification-setup').location, '/dashboard')

    def test_unavailable_or_broadcast_channels_cannot_be_submitted(self):
        with self.app.app_context():
            NotificationConfig.query.filter_by(key='discord_bot_token').delete()
            db.session.add(NotificationConfig(key='discord_webhook_url', value='https://example.com/webhook'))
            db.session.commit()
        page = self.client.get('/register').get_data(as_text=True)
        self.assertIn('value="telegram"', page)
        self.assertNotIn('value="discord"', page)
        for channel in ('discord', 'root', 'forged'):
            with self.subTest(channel=channel):
                self.assertEqual(self.register(notification_channel=channel).status_code, 200)
        with self.app.app_context():
            self.assertEqual(User.query.count(), 0)

    def test_skip_stops_future_prompts_and_old_tokens_do_not_change_preference(self):
        self.register()
        self.login()
        self.client.post('/notification-setup', data={'action': 'generate'})
        with self.app.app_context():
            token = BotLinkToken.query.one().token
        self.assertEqual(self.client.post('/notification-setup', data={'action': 'skip'}).location, '/dashboard')
        with self.app.app_context():
            user, reason = claim_link_token('telegram', token, external_id='111', chat_id='111')
            self.assertEqual(reason, 'ok')
            db.session.commit()
            self.assertEqual(user.notification_channel, 'email')
            self.assertIsNone(user.pending_notification_channel)
        self.client.get('/logout')
        self.assertEqual(self.login().location, '/dashboard')

    def test_abandonment_reprompts_only_within_seven_days(self):
        self.register()
        self.login()
        self.client.get('/logout')
        self.assertEqual(self.login().location, '/notification-setup')
        self.client.get('/logout')
        with self.app.app_context():
            User.query.one().notification_setup_expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.session.commit()
        self.assertEqual(self.login().location, '/dashboard')
        with self.app.app_context():
            user = User.query.one()
            self.assertIsNone(user.pending_notification_channel)
            self.assertEqual(user.notification_channel, 'email')

    def test_expiration_while_on_linking_page_keeps_email(self):
        self.register()
        self.login()
        with self.app.app_context():
            User.query.one().notification_setup_expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.session.commit()
        self.assertEqual(self.client.post('/notification-setup', data={'action': 'generate'}).location, '/dashboard')
        with self.app.app_context():
            self.assertEqual(BotLinkToken.query.count(), 0)

    def test_disabled_provider_clears_pending_setup(self):
        self.register()
        self.login()
        with self.app.app_context():
            NotificationConfig.query.filter_by(key='telegram_bot_token').delete()
            db.session.commit()
        self.assertEqual(self.client.get('/notification-setup').location, '/dashboard')
        with self.app.app_context():
            self.assertIsNone(User.query.one().pending_notification_channel)

    def test_linking_activates_selected_channel_and_never_prompts_again(self):
        for channel in ('telegram', 'discord'):
            with self.subTest(channel=channel):
                self.client.get('/logout')
                name = channel + '-member'
                self.register(username=name, email=channel + '@example.com', notification_channel=channel)
                self.login(username=name)
                self.client.post('/notification-setup', data={'action': 'generate'})
                with self.app.app_context():
                    token = BotLinkToken.query.filter_by(provider=channel).one()
                    user, reason = claim_link_token(channel, token.token, external_id='123', chat_id='123', username=channel + '_handle')
                    self.assertEqual(reason, 'ok')
                    db.session.commit()
                    self.assertEqual(user.notification_channel, channel)
                    self.assertIsNone(user.pending_notification_channel)
                self.assertEqual(self.client.post('/notification-setup', data={'action': 'check'}).location, '/dashboard')
                self.client.get('/logout')
                self.assertEqual(self.login(username=name).location, '/dashboard')

    def test_unlinked_check_does_not_activate_channel_and_tokens_respect_deadline(self):
        self.register()
        self.login()
        with self.app.app_context():
            User.query.one().notification_setup_expires_at = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()
        self.client.post('/notification-setup', data={'action': 'generate'})
        page = self.client.post('/notification-setup', data={'action': 'check'})
        self.assertIn(b'not linked yet', page.data)
        with self.app.app_context():
            user = User.query.one()
            self.assertEqual(user.notification_channel, 'email')
            self.assertLessEqual(BotLinkToken.query.one().expires_at, user.notification_setup_expires_at)

    def test_email_choice_is_honored_when_linking_finishes_in_another_tab(self):
        self.register()
        self.login()
        self.client.post('/notification-setup', data={'action': 'generate'})
        with self.app.app_context():
            token = BotLinkToken.query.one()
            user, reason = claim_link_token('telegram', token.token, external_id='111', chat_id='111')
            self.assertEqual(reason, 'ok')
            db.session.commit()
            self.assertEqual(user.notification_channel, 'telegram')
        self.client.post('/notification-setup', data={'action': 'skip'})
        with self.app.app_context():
            self.assertEqual(User.query.one().notification_channel, 'email')

    def test_login_next_is_preserved_and_external_redirect_is_rejected(self):
        self.register()
        self.client.post('/login?next=/profile', data={'username': 'new-member', 'password': 'secret123'})
        self.assertEqual(self.client.post('/notification-setup?next=/profile', data={'action': 'skip'}).location, '/profile')
        self.assertEqual(self.client.get('/notification-setup?next=https://evil.example').location, '/dashboard')

    def test_setup_requires_authentication_and_csrf(self):
        self.assertIn('/login', self.client.get('/notification-setup').location)
        self.register()
        self.login()
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assertEqual(self.client.post('/notification-setup', data={'action': 'skip'}).status_code, 400)

    def test_registration_rejects_normalized_duplicate_names_without_modifying_owner(self):
        with self.app.app_context():
            owner = User(username='Existing', email='owner@example.com', tg_username='@TelegramOwner', discord_username='DiscordOwner', password_hash='unchanged')
            db.session.add(owner)
            db.session.commit()
        for fields in ({'username': 'eXISTING'}, {'tg_username': ' telegramowner '}, {'tg_username': '@TELEGRAMOWNER'}, {'discord_username': '@discordowner'}):
            with self.subTest(fields=fields):
                response = self.register(**fields)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'already in use', response.data)
        with self.app.app_context():
            self.assertEqual(User.query.count(), 1)
            self.assertEqual(User.query.one().password_hash, 'unchanged')

    def test_profile_and_admin_cannot_introduce_new_duplicate_handles(self):
        self.register(notification_channel='email')
        with self.app.app_context():
            db.session.add(User(username='owner', email='owner@example.com', tg_username='owned', discord_username='owned-discord', password_hash='hash'))
            db.session.commit()
        self.login()
        payload = dict(username='new-member', email='new@example.com', notification_channel='email', digest_frequency='off', tg_username='@OWNED')
        self.assertIn(b'already in use', self.client.post('/profile', data=payload).data)
        with self.app.app_context():
            user = User.query.filter_by(username='new-member').one()
            self.assertIsNone(user.tg_username)
            user.is_admin = True
            db.session.commit()
            user_id = user.id
        payload.update(tg_username='', discord_username='@Owned-Discord')
        self.assertIn(b'already in use', self.client.post(f'/admin/users/{user_id}/edit', data=payload).data)
        payload.update(username='admin-created', email='another@example.com')
        self.assertIn(b'already in use', self.client.post('/admin/users/new', data=payload).data)

    def test_model_rejects_duplicates_and_blanks_are_not_reserved(self):
        with self.app.app_context():
            db.session.add(User(username='first', email='first@example.com', tg_username='@owned', password_hash='hash'))
            db.session.commit()
            db.session.add(User(username='second', email='second@example.com', tg_username='OWNED', password_hash='hash'))
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()
            db.session.add_all([User(username=name, email=name + '@example.com', tg_username='', discord_username='', password_hash='hash') for name in ('blank1', 'blank2')])
            db.session.commit()

    def test_linking_cannot_overwrite_another_recorded_handle(self):
        self.register()
        with self.app.app_context():
            db.session.add(User(username='owner', email='owner@example.com', tg_username='@owned', password_hash='hash'))
            user = User.query.filter_by(username='new-member').one()
            token = issue_link_token('telegram', user)
            db.session.commit()
            self.assertEqual(claim_link_token('telegram', token.token, external_id='123', chat_id='123', username='OWNED'), (None, 'username-owned'))
            db.session.commit()
            self.assertIsNone(token.used_at)
            self.assertIsNone(user.telegram_user_id)

    def test_database_blocks_duplicate_handles_in_one_concurrent_insert_batch(self):
        with self.app.app_context():
            # Both before-insert checks run before either row exists; the database
            # constraint must catch the conflict after those checks have passed.
            db.session.add_all([
                User(username='batch1', email='batch1@example.com', tg_username='@same', password_hash='hash'),
                User(username='batch2', email='batch2@example.com', tg_username='SAME', password_hash='hash'),
            ])
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()
            self.assertEqual(User.query.count(), 0)

    def test_existing_telegram_username_fallback_is_preserved(self):
        with self.app.app_context(), patch('app.notifications._send_telegram_bot_message', return_value=True) as send:
            user = User(username='fallback', tg_username='@existing_handle')
            self.assertTrue(send_telegram_message(user, 'message'))
            send.assert_called_once_with('@existing_handle', 'message')


class RegistrationMigrationTests(unittest.TestCase):
    def test_migration_preserves_duplicates_and_blocks_new_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(directory) / 'migration.db')})
            with app.app_context():
                try:
                    upgrade(directory='migrations', revision='c5e7a9b1d3f4')
                    for ident, username, handle in ((1, 'Same', '@shared'), (2, 'same', 'SHARED')):
                        db.session.execute(text("INSERT INTO users (id, username, email, password_hash, tg_username, discord_username, is_admin, is_active, session_epoch, created_at) VALUES (:id, :username, :email, 'hash', :handle, :handle, 0, 1, 0, CURRENT_TIMESTAMP)"), dict(id=ident, username=username, email=f'{ident}@example.com', handle=handle))
                    db.session.execute(text("INSERT INTO users (id, username, email, password_hash, is_admin, is_active, session_epoch, created_at) VALUES (90, 'deleted', 'deleted@example.com', 'hash', 0, 1, 0, CURRENT_TIMESTAMP)"))
                    db.session.execute(text('DELETE FROM users WHERE id=90'))
                    db.session.commit()
                    upgrade(directory='migrations')
                    users = User.query.order_by(User.id).all()
                    self.assertEqual([(u.username, u.tg_username) for u in users], [('Same', '@shared'), ('same', 'SHARED')])
                    for user in users:
                        user.email = f'updated{user.id}@example.com'
                    db.session.commit()  # Existing duplicates can still be edited.
                    with app.test_request_context():
                        from app.routes import ProfileForm
                        for user in users:
                            form = ProfileForm(obj=user)
                            self.assertTrue(form.username.validate(form))
                            self.assertTrue(form.tg_username.validate(form))
                            self.assertTrue(form.discord_username.validate(form))
                    for fields in ({'username': 'SAME'}, {'username': 'fresh', 'tg_username': 'shared'}, {'username': 'fresh', 'discord_username': '@SHARED'}):
                        db.session.add(User(email='fresh@example.com', password_hash='hash', **fields))
                        with self.assertRaises(IntegrityError):
                            db.session.commit()
                        db.session.rollback()
                    user = User(username='fresh', email='fresh@example.com', password_hash='hash')
                    db.session.add(user)
                    db.session.commit()
                    self.assertGreater(user.id, 90)
                    downgrade(directory='migrations', revision='c5e7a9b1d3f4')
                    self.assertEqual(db.session.execute(text('SELECT COUNT(*) FROM users')).scalar_one(), 3)
                finally:
                    db.session.remove()
                    db.engine.dispose()
