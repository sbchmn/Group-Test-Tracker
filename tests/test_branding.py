"""Optional identity, publication, asset privacy, and member theme behavior."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask_migrate import downgrade, upgrade
from PIL import Image
from sqlalchemy import inspect, text

from app import create_app, db
from app.branding import DEFAULTS, brand_text, contrast, effective_settings, email_parts, foreground, get_state, hover_color, link_color, validate_settings
from app.models import BrandingAsset, BrandingRevision, BrandingState, NotificationConfig, NotificationTemplate, User


class BrandingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(self.tmp.name) / 'branding.db'),
            'NOTIFICATION_LOG_PATH': str(Path(self.tmp.name) / 'notifications.log')})
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            for name in ('admin', 'member'):
                user = User(username=name, email=name + '@example.com', is_admin=name == 'admin')
                user.set_password('secret123')
                db.session.add(user)
            db.session.commit()
        self.login()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.tmp.cleanup()

    def login(self, name='admin', client=None):
        client = client or self.client
        client.get('/logout')
        client.post('/login', data={'username': name, 'password': 'secret123'})

    def version(self):
        with self.app.app_context():
            state = get_state()
            return state.version if state else 0

    def action(self, action, **data):
        return self.client.post('/admin/branding', data={'version': str(self.version()), 'action': action, **data})

    def save(self, **overrides):
        data = {**DEFAULTS, 'enabled': 'y', 'name': 'Community Lab', 'short_name': 'CL', **overrides}
        if not data['enabled']:
            data.pop('enabled')
        return self.action('save', **data)

    def publish(self, **settings):
        self.assertEqual(self.save(**settings).status_code, 302)
        self.assertEqual(self.action('publish').status_code, 302)

    def image(self):
        buffer = io.BytesIO()
        Image.new('RGBA', (500, 100), '#008877').save(buffer, format='PNG')
        buffer.seek(0)
        return buffer

    def test_defaults_editor_and_all_previews_render(self):
        self.assertIn(b'Branding & Appearance', self.client.get('/admin/branding').data)
        for surface in ('home', 'login', 'register', 'dashboard', 'terms', 'privacy', 'email'):
            with self.subTest(surface=surface):
                page = self.client.get('/admin/branding/preview/' + surface)
                self.assertEqual(page.status_code, 200)
                self.assertIn(b'Private draft preview', page.data)
                if surface != 'dashboard':
                    self.assertNotIn(b'href="/admin/settings"', page.data)
        with self.app.app_context():
            self.assertIsNone(get_state())

    def test_private_draft_publish_and_disable_preserve_legal_and_draft(self):
        self.save(operator_name='Customer LLC', legal_email='legal@example.com')
        self.assertNotIn(b'Community Lab', self.client.get('/', follow_redirects=True).data)
        self.assertIn(b'Community Lab', self.client.get('/admin/branding/preview/home').data)
        self.action('publish')
        page = self.client.get('/', follow_redirects=True).data
        self.assertIn(b'Community Lab', page)
        self.assertIn(b'Powered by GTM', page)
        terms = self.client.get('/terms').data
        self.assertIn(b'Customer LLC', terms)
        self.assertIn(b'legal@example.com', terms)
        self.action('defaults')
        self.assertNotIn(b'Community Lab', self.client.get('/', follow_redirects=True).data)
        self.assertIn(b'Customer LLC', self.client.get('/terms').data)
        with self.app.app_context():
            self.assertEqual(get_state().draft['name'], 'Community Lab')
            self.assertEqual(BrandingRevision.query.count(), 2)

    def test_discard_and_restore_revisions(self):
        self.publish()
        with self.app.app_context():
            revision_id = BrandingRevision.query.one().id
        self.save(name='Second name')
        self.action('discard')
        with self.app.app_context():
            self.assertEqual(get_state().draft['name'], 'Community Lab')
        self.publish(name='Second name')
        self.action('restore', revision_id=revision_id)
        self.assertIn(b'Community Lab', self.client.get('/', follow_redirects=True).data)
        with self.app.app_context():
            self.assertEqual(get_state().draft['name'], 'Community Lab')
            self.assertEqual(BrandingRevision.query.order_by(BrandingRevision.id.desc()).first().action, 'restore')

    def test_conflicting_edit_is_rejected_without_overwriting(self):
        original = self.version()
        self.save()
        page = self.client.post('/admin/branding', data={**DEFAULTS, 'version': original, 'action': 'save', 'name': 'Stale admin'})
        self.assertEqual(page.status_code, 409)
        with self.app.app_context():
            self.assertEqual(get_state().draft['name'], 'Community Lab')

    def test_invalid_values_do_not_publish_or_replace_draft(self):
        self.save()
        for values in ({'font': 'url(evil)'}, {'name': ''}, {'user_help_url': 'javascript:alert(1)'},
                       {'support_email': 'bad'}, {'light_surface': '#000000'}, {'dark_surface': '#ffffff'},
                       {'light_accent': 'red; color: black'}, {'name': 'x' * 81}, {'name': 'A\nB'}):
            with self.subTest(values=values):
                self.assertEqual(self.save(**values).status_code, 400)
                with self.app.app_context():
                    self.assertEqual(get_state().draft['name'], 'Community Lab')
                    self.assertEqual(BrandingRevision.query.count(), 0)

    def test_text_is_escaped_and_help_is_role_restricted(self):
        self.publish(name='<script>alert(1)</script>', user_help_url='https://example.com/help', admin_help_url='https://example.com/admin')
        self.client.get('/logout')
        body = self.client.get('/', follow_redirects=True).data
        self.assertIn(b'&lt;script&gt;', body)
        self.assertIn(b'https://example.com/help', body)
        self.assertNotIn(b'https://example.com/admin', body)

    def test_draft_assets_private_and_published_assets_immutable(self):
        self.save(logo_upload=(self.image(), 'logo.png'))
        with self.app.app_context():
            asset_id = get_state().draft['logo']
        route = f'/branding/assets/{asset_id}/image.png'
        self.assertEqual(self.client.get(route).status_code, 200)
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get(route).status_code, 404)
        self.action('publish')
        response = anonymous.get(route)
        self.assertEqual(response.mimetype, 'image/png')
        self.assertIn('immutable', response.headers['Cache-Control'])
        with Image.open(io.BytesIO(anonymous.get(f'/branding/assets/{asset_id}/icon.png').data)) as icon:
            self.assertEqual(icon.size, (32, 32))
        self.save(logo_upload=(self.image(), 'replacement.png'))
        self.action('publish')
        self.assertEqual(anonymous.get(route).status_code, 200)
        self.assertEqual(anonymous.get(f'/branding/assets/{asset_id}/forged.png').status_code, 404)

    def test_invalid_upload_is_atomic(self):
        self.save()
        self.assertEqual(self.save(name='Bad upload', logo_upload=(io.BytesIO(b'<svg onload="evil"/>'), 'image.png')).status_code, 400)
        with self.app.app_context():
            self.assertEqual(get_state().draft['name'], 'Community Lab')
            self.assertEqual(BrandingAsset.query.count(), 0)
        self.assertEqual(self.save(logo_upload=(io.BytesIO(b'x' * (2 * 1024 * 1024 + 1)), 'huge.png')).status_code, 400)

    def test_member_and_anonymous_cannot_manage_or_preview(self):
        self.login('member')
        for path in ('/admin/branding', '/admin/branding/preview/home'):
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.action('save').status_code, 403)
        self.client.get('/logout')
        self.assertEqual(self.client.get('/admin/branding').status_code, 302)

    def test_csrf_and_subscription_guards(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assertEqual(self.action('publish').status_code, 400)
        self.assertEqual(self.client.post('/appearance', data={'theme': 'dark'}).status_code, 400)
        self.app.config['WTF_CSRF_ENABLED'] = False
        with patch.dict('os.environ', {'GTT_DEPLOYMENT_MODE': 'managed', 'GTT_SUBSCRIPTION_STATUS': 'suspended'}):
            self.assertEqual(self.save().status_code, 302)
        with self.app.app_context():
            self.assertIsNone(get_state())

    def test_themes_persist_per_member_and_anonymous_browser(self):
        self.publish(default_theme='dark')
        self.client.post('/appearance', data={'theme': 'system', 'next': '/profile'})
        with self.app.app_context():
            self.assertEqual(User.query.filter_by(username='admin').one().theme_preference, 'system')
        other = self.app.test_client()
        self.login(client=other)
        self.assertIn(b'preference: "system"', other.get('/', follow_redirects=True).data)
        self.assertEqual(self.client.post('/appearance', data={'theme': 'forged'}).status_code, 400)
        self.client.get('/logout')
        response = self.client.post('/appearance', data={'theme': 'light', 'next': 'https://evil.example'})
        self.assertEqual(response.location, '/')
        self.assertEqual(self.client.post('/appearance', data={'theme': 'light', 'next': '/\\evil.example'}).location, '/')
        self.assertIn('HttpOnly', response.headers['Set-Cookie'])
        self.assertIn(b'preference: "light"', self.client.get('/', follow_redirects=True).data)

    def test_email_branding_preserves_body_sender_address_and_custom_templates(self):
        self.publish()
        with self.app.app_context():
            from app.notifications import render_notification_template, send_mailjet_message
            for key, value in {'mailjet_api_key': 'key', 'mailjet_secret_key': 'secret', 'mailjet_sender_email': 'sender@example.com'}.items():
                db.session.add(NotificationConfig(key=key, value=value))
            template = NotificationTemplate(name='Custom', email_body='<p>Custom text</p>', is_active=True)
            db.session.add(template)
            db.session.commit()
            user = User.query.filter_by(username='member').one()
            reply = MagicMock()
            reply.__enter__.return_value.status = 200
            reply.__enter__.return_value.read.return_value = b'{}'
            with patch('app.notifications.urlopen', return_value=reply) as send:
                self.assertTrue(send_mailjet_message(user, 'Subject', template.email_body))
                payload = json.loads(send.call_args.args[0].data)['Messages'][0]
                self.assertEqual(payload['From'], {'Email': 'sender@example.com', 'Name': 'Community Lab'})
                self.assertIn('<p>Custom text</p>', payload['HTMLPart'])
                self.assertIn('Powered by GTM', payload['TextPart'])
            self.assertEqual(template.email_body, '<p>Custom text</p>')
            self.assertEqual(render_notification_template('{{ brand_name }}: {{ username }}', {'username': 'Alex'}), 'Community Lab: Alex')
            self.assertEqual(brand_text('Group Test Manager link'), 'Community Lab link')

    def test_workers_observe_new_published_revision_in_fresh_context(self):
        self.publish()
        with self.app.app_context():
            self.assertEqual(effective_settings()['name'], 'Community Lab')
        self.publish(name='New published name')
        with self.app.app_context():
            self.assertEqual(effective_settings()['name'], 'New published name')

    def test_bright_accents_get_readable_links_buttons_and_hover_states(self):
        for mode, surface in (('light', '#ffffff'), ('dark', '#212529')):
            for accent in ('#ffff00', '#ffffff', '#000000', '#887766'):
                self.assertGreaterEqual(contrast(link_color(accent, surface, mode), surface), 4.5)
                self.assertGreaterEqual(contrast(accent, foreground(accent)), 4.5)
                self.assertGreaterEqual(contrast(hover_color(accent), foreground(accent)), 4.5)

    def test_email_logo_uses_stable_customer_url_and_keeps_published_asset(self):
        self.publish(logo_upload=(self.image(), 'logo.png'))
        with self.app.app_context():
            db.session.add(NotificationConfig(key='service_base_url', value='https://customer.grouptest.online'))
            db.session.commit()
            asset_id = get_state().published['logo']
            _, markup = email_parts('Message')
            self.assertIn(f'https://customer.grouptest.online/branding/assets/{asset_id}/image.png', markup)
            self.assertNotIn('token=', markup)

    def test_publish_revalidates_the_saved_draft(self):
        self.publish()
        with self.app.app_context():
            state = get_state()
            state.draft = {**state.draft, 'logo': 'f' * 32}
            db.session.commit()
        self.assertEqual(self.action('publish').status_code, 400)
        with self.app.app_context():
            self.assertEqual(get_state().published['logo'], '')

    def test_retort_persona_uses_published_brand_without_touching_provider_config(self):
        from types import SimpleNamespace
        self.publish()
        with self.app.app_context():
            from app.telegram_bot_retorts import generate_retort
            client = MagicMock()
            client.__enter__.return_value.responses.create.return_value.output_text = 'That command was meant for CL.'
            with patch.dict('sys.modules', {'openai': SimpleNamespace(OpenAI=MagicMock(return_value=client))}):
                result = generate_retort({'name': 'openai', 'api_key': 'test', 'model': 'existing-model'}, '/help', 'A bot reply')
            self.assertEqual(result, 'That command was meant for CL.')
            arguments = client.__enter__.return_value.responses.create.call_args.kwargs
            self.assertIn('Community Lab', arguments['instructions'])
            self.assertNotIn('GTT', arguments['instructions'])
            self.assertEqual(arguments['model'], 'existing-model')

    def test_preview_is_get_only_and_does_not_mutate_state(self):
        self.save()
        version = self.version()
        page = self.client.get('/admin/branding/preview/register?theme=dark')
        self.assertIn(b'<div inert>', page.data)
        self.assertIn(b'preference: "dark"', page.data)
        self.assertEqual(self.client.post('/admin/branding/preview/register').status_code, 405)
        self.assertEqual(self.version(), version)


class BrandingMigrationTests(unittest.TestCase):
    def test_upgrade_downgrade_preserves_existing_accounts_and_deleted_id_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(directory) / 'migration.db')})
            with app.app_context():
                try:
                    upgrade(directory='migrations', revision='d6f8a0b2c4e5')
                    db.session.execute(text("INSERT INTO users (id, username, username_key, email, password_hash, is_admin, is_active, session_epoch, created_at) VALUES (99, 'legacy', 'legacy', 'legacy@example.com', 'hash', 0, 1, 0, CURRENT_TIMESTAMP)"))
                    db.session.commit()
                    upgrade(directory='migrations')
                    user = db.session.get(User, 99)
                    self.assertEqual(user.theme_preference, 'site')
                    self.assertIsNone(get_state())
                    db.session.delete(user)
                    db.session.commit()
                    downgrade(directory='migrations', revision='d6f8a0b2c4e5')
                    self.assertNotIn('branding_state', inspect(db.engine).get_table_names())
                    self.assertGreaterEqual(db.session.execute(text("SELECT seq FROM sqlite_sequence WHERE name='users'")).scalar_one(), 99)
                finally:
                    db.session.remove()
                    db.engine.dispose()
