"""Tests for the inbound SaaS control-plane bootstrap/support endpoints.

The signing helper below is a self-contained reimplementation of the
canonical-message/HMAC algorithm used by the private
`sbchmn/Group-Test-Tracker-Control-Plane` client (`app/services/hmac_contract.py`)
so these tests do not depend on that private repository.
"""

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import create_app, db
from app.models import User

HEADER_PREFIX = 'X-GTT-'


def sign(secret, key_id, tenant, contract, method, path, body, operation_id, revision, timestamp=None, nonce=None):
    timestamp = int(time.time()) if timestamp is None else timestamp
    nonce = nonce or secrets.token_urlsafe(24)
    digest = hashlib.sha256(body).hexdigest()
    message = '\n'.join([
        key_id, tenant, contract, method.upper(), path, str(timestamp), nonce, operation_id, str(revision), digest,
    ]).encode('utf-8')
    signature = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()
    return {
        f'{HEADER_PREFIX}Key-ID': key_id,
        f'{HEADER_PREFIX}Tenant': tenant,
        f'{HEADER_PREFIX}Contract': contract,
        f'{HEADER_PREFIX}Timestamp': str(timestamp),
        f'{HEADER_PREFIX}Nonce': nonce,
        f'{HEADER_PREFIX}Operation-ID': operation_id,
        f'{HEADER_PREFIX}Revision': str(revision),
        f'{HEADER_PREFIX}Body-SHA256': digest,
        f'{HEADER_PREFIX}Signature': signature,
        'Content-Type': 'application/json',
    }


class ControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / 'test.db'
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
            'WTF_CSRF_ENABLED': False,
        })
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()

        self.secret = 'test-cp-secret'
        self.key_id = 'cp-key-1'
        self.tenant = 'tenant-public-id'
        self._env_keys = [
            'GTT_DEPLOYMENT_MODE', 'GTT_TENANT_ID', 'GTT_CONTRACT_VERSION',
            'GTT_CP_TO_INSTANCE_KEY_ID', 'GTT_CP_TO_INSTANCE_SECRET',
            'GTT_CP_TO_INSTANCE_KEY_ID_PREVIOUS', 'GTT_CP_TO_INSTANCE_SECRET_PREVIOUS',
            'GTT_ENTITLEMENTS', 'GTT_ENTITLEMENT_REVISION', 'GTT_PUBLIC_URL',
            'GTT_USER_DOCUMENTATION_URL', 'GTT_ADMIN_DOCUMENTATION_URL',
            'GTT_SUBSCRIPTION_STATUS', 'GTT_CONTROL_PLANE_URL',
            'GTT_INSTANCE_TO_CP_KEY_ID', 'GTT_INSTANCE_TO_CP_SECRET',
        ]
        self._env_backup = {key: os.environ.get(key) for key in self._env_keys}
        os.environ['GTT_DEPLOYMENT_MODE'] = 'managed'
        os.environ['GTT_TENANT_ID'] = self.tenant
        os.environ['GTT_CONTRACT_VERSION'] = '1'
        os.environ['GTT_CP_TO_INSTANCE_KEY_ID'] = self.key_id
        os.environ['GTT_CP_TO_INSTANCE_SECRET'] = self.secret

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.temp_dir.cleanup()
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _post(self, path, body_dict, operation_id, revision=1, **sign_kwargs):
        body = json.dumps(body_dict, sort_keys=True, separators=(',', ':')).encode('utf-8')
        headers = sign(self.secret, self.key_id, self.tenant, '1', 'POST', path, body, operation_id, revision, **sign_kwargs)
        return self.client.post(path, data=body, headers=headers)

    def test_bootstrap_creates_admin_and_inert_support_account(self):
        response = self._post('/internal/control-plane/v1/bootstrap', {
            'username': 'owner1', 'email': 'owner1@example.com',
            'password_hash': 'scrypt:32768:8:1$salt$hash',
            'support_username': 'gtmsupport', 'support_email': 'support@grouptest.online',
        }, operation_id='bootstrap:tenant-public-id')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.get_json()['acknowledged'])
        admin = User.query.filter_by(username='owner1').first()
        self.assertIsNotNone(admin)
        self.assertTrue(admin.is_admin)
        self.assertTrue(admin.is_active)
        self.assertEqual(admin.password_hash, 'scrypt:32768:8:1$salt$hash')
        support = User.query.filter_by(username='gtmsupport').first()
        self.assertIsNotNone(support)
        self.assertFalse(support.is_active)

    def test_bootstrap_replay_with_same_operation_id_is_idempotent(self):
        body_dict = {
            'username': 'owner2', 'email': 'owner2@example.com',
            'password_hash': 'scrypt:32768:8:1$salt$hash',
            'support_username': 'gtmsupport', 'support_email': 'support@grouptest.online',
        }
        first = self._post('/internal/control-plane/v1/bootstrap', body_dict, operation_id='bootstrap:dup')
        self.assertEqual(first.status_code, 201)
        second = self._post('/internal/control-plane/v1/bootstrap', body_dict, operation_id='bootstrap:dup')
        self.assertEqual(second.status_code, 201)
        self.assertEqual(User.query.filter_by(username='owner2').count(), 1)

    def test_bootstrap_rejects_conflicting_payload_for_same_operation_id(self):
        body_dict = {
            'username': 'owner3', 'email': 'owner3@example.com',
            'password_hash': 'scrypt:32768:8:1$salt$hash',
            'support_username': 'gtmsupport', 'support_email': 'support@grouptest.online',
        }
        self._post('/internal/control-plane/v1/bootstrap', body_dict, operation_id='bootstrap:conflict')
        other = dict(body_dict, username='owner3-changed')
        response = self._post('/internal/control-plane/v1/bootstrap', other, operation_id='bootstrap:conflict')
        self.assertEqual(response.status_code, 409)

    def test_bootstrap_rejects_invalid_signature(self):
        body = json.dumps({
            'username': 'x', 'email': 'x@example.com', 'password_hash': 'h',
            'support_username': 'gtmsupport', 'support_email': 's@example.com',
        }, sort_keys=True, separators=(',', ':')).encode('utf-8')
        headers = sign('wrong-secret', self.key_id, self.tenant, '1', 'POST',
                        '/internal/control-plane/v1/bootstrap', body, 'bootstrap:bad-sig', 1)
        response = self.client.post('/internal/control-plane/v1/bootstrap', data=body, headers=headers)
        self.assertEqual(response.status_code, 401)

    def test_bootstrap_rejects_expired_timestamp(self):
        body = json.dumps({
            'username': 'x', 'email': 'x@example.com', 'password_hash': 'h',
            'support_username': 'gtmsupport', 'support_email': 's@example.com',
        }, sort_keys=True, separators=(',', ':')).encode('utf-8')
        headers = sign(self.secret, self.key_id, self.tenant, '1', 'POST',
                        '/internal/control-plane/v1/bootstrap', body, 'bootstrap:expired', 1,
                        timestamp=int(time.time()) - 300)
        response = self.client.post('/internal/control-plane/v1/bootstrap', data=body, headers=headers)
        self.assertEqual(response.status_code, 401)

    def test_bootstrap_returns_404_when_not_managed(self):
        os.environ['GTT_DEPLOYMENT_MODE'] = 'standalone'
        response = self._post('/internal/control-plane/v1/bootstrap', {
            'username': 'x', 'email': 'x@example.com', 'password_hash': 'h',
            'support_username': 'gtmsupport', 'support_email': 's@example.com',
        }, operation_id='bootstrap:standalone')
        self.assertEqual(response.status_code, 404)

    def test_support_rotate_then_enable_then_disable_lifecycle(self):
        self._post('/internal/control-plane/v1/bootstrap', {
            'username': 'owner4', 'email': 'owner4@example.com',
            'password_hash': 'scrypt:32768:8:1$salt$hash',
            'support_username': 'gtmsupport', 'support_email': 'support@grouptest.online',
        }, operation_id='bootstrap:owner4')

        rotate = self._post('/internal/control-plane/v1/support', {
            'action': 'rotate', 'username': 'gtmsupport', 'email': 'support@grouptest.online',
            'password_hash': 'scrypt:32768:8:1$salt$hash2', 'credential_version': 1, 'expires_at': None,
        }, operation_id='support:owner4:1:rotate')
        self.assertEqual(rotate.status_code, 200)
        self.assertEqual(rotate.get_json()['state'], 'disabled')

        enable = self._post('/internal/control-plane/v1/support', {
            'action': 'enable', 'username': 'gtmsupport', 'email': 'support@grouptest.online',
            'password_hash': 'scrypt:32768:8:1$salt$hash2', 'credential_version': 1,
            'expires_at': (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        }, operation_id='support:owner4:1:enable')
        self.assertEqual(enable.status_code, 200)
        self.assertEqual(enable.get_json()['state'], 'enabled')
        support = User.query.filter_by(username='gtmsupport').first()
        self.assertTrue(support.is_active)
        self.assertEqual(support.password_hash, 'scrypt:32768:8:1$salt$hash2')

        disable = self._post('/internal/control-plane/v1/support', {
            'action': 'disable', 'username': 'gtmsupport', 'email': 'support@grouptest.online',
            'password_hash': None, 'credential_version': 1, 'expires_at': None,
        }, operation_id='support:owner4:1:disable')
        self.assertEqual(disable.status_code, 200)
        self.assertEqual(disable.get_json()['state'], 'disabled')
        db.session.refresh(support)
        self.assertFalse(support.is_active)
        self.assertNotEqual(support.password_hash, 'scrypt:32768:8:1$salt$hash2')

    def test_managed_mode_parses_entitlements_and_documentation_urls(self):
        from app.saas import (
            entitlement_enabled,
            entitlement_revision,
            managed_admin_docs_url,
            managed_mode_enabled,
            managed_public_url,
            managed_user_docs_url,
            subscription_status,
        )

        os.environ['GTT_DEPLOYMENT_MODE'] = 'managed'
        os.environ['GTT_ENTITLEMENTS'] = 'discord_bot,result_analysis'
        os.environ['GTT_ENTITLEMENT_REVISION'] = '7'
        os.environ['GTT_PUBLIC_URL'] = 'https://example.com'
        os.environ['GTT_USER_DOCUMENTATION_URL'] = 'https://docs.example.com/user'
        os.environ['GTT_ADMIN_DOCUMENTATION_URL'] = 'https://docs.example.com/admin'
        os.environ['GTT_SUBSCRIPTION_STATUS'] = 'active'

        self.assertTrue(managed_mode_enabled())
        self.assertEqual(entitlement_revision(), 7)
        self.assertTrue(entitlement_enabled('discord_bot'))
        self.assertTrue(entitlement_enabled('result_analysis'))
        self.assertEqual(managed_public_url(), 'https://example.com')
        self.assertEqual(managed_user_docs_url(), 'https://docs.example.com/user')
        self.assertEqual(managed_admin_docs_url(), 'https://docs.example.com/admin')
        self.assertEqual(subscription_status(), 'active')

    def test_suspended_subscription_sets_readonly_recovery_surface(self):
        from app.saas import (
            subscription_access_allowed,
            subscription_is_readonly,
        )

        os.environ['GTT_DEPLOYMENT_MODE'] = 'managed'
        os.environ['GTT_SUBSCRIPTION_STATUS'] = 'suspended'
        os.environ['GTT_ENTITLEMENTS'] = 'discord_bot,result_analysis'

        self.assertTrue(subscription_is_readonly())
        self.assertTrue(subscription_access_allowed())
        self.assertFalse(subscription_access_allowed(feature='discord_bot'))

    def test_unknown_managed_subscription_status_fails_closed(self):
        from app.saas import subscription_access_allowed

        os.environ['GTT_DEPLOYMENT_MODE'] = 'managed'
        os.environ['GTT_SUBSCRIPTION_STATUS'] = 'future_status'

        self.assertFalse(subscription_access_allowed())
        self.assertFalse(subscription_access_allowed(feature='discord_bot'))

    @patch('app.saas.urllib_request.urlopen')
    def test_report_instance_event_keeps_authoritative_type(self, urlopen):
        from app.saas import report_instance_event

        os.environ.update({
            'GTT_CONTROL_PLANE_URL': 'https://control.example',
            'GTT_INSTANCE_TO_CP_KEY_ID': 'instance-key',
            'GTT_INSTANCE_TO_CP_SECRET': 'instance-secret',
        })
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"accepted":true}'

        result = report_instance_event('status', {'type': 'support_emergency_disabled', 'ready': True})

        self.assertEqual(result, {'accepted': True})
        request = urlopen.call_args.args[0]
        self.assertEqual(json.loads(request.data.decode('utf-8'))['type'], 'status')

    def test_instance_event_uses_control_plane_canonical_signature(self):
        from app.saas import _instance_event_signature

        os.environ['GTT_ENTITLEMENT_REVISION'] = '12'
        headers, body = _instance_event_signature(
            'instance-secret',
            key_id='instance-key-1',
            tenant=self.tenant,
            operation_id='instance:status:1',
            payload={'event': 'status', 'payload': {'component': 'worker'}},
        )

        digest = hashlib.sha256(body).hexdigest()
        self.assertEqual(headers['X-GTT-Tenant'], self.tenant)
        self.assertEqual(headers['X-GTT-Revision'], '12')
        self.assertEqual(headers['X-GTT-Body-SHA256'], digest)
        canonical = '\n'.join([
            'instance-key-1', self.tenant, '1', 'POST',
            f'/internal/tenants/{self.tenant}/events',
            headers['X-GTT-Timestamp'], headers['X-GTT-Nonce'],
            'instance:status:1', '12', digest,
        ]).encode('utf-8')
        expected = hmac.new('instance-secret'.encode('utf-8'), canonical, hashlib.sha256).hexdigest()
        self.assertTrue(hmac.compare_digest(headers['X-GTT-Signature'], expected))

    def test_managed_urls_and_docs_are_ignored_outside_managed_mode(self):
        from app.saas import managed_admin_docs_url, managed_public_url, managed_user_docs_url

        os.environ['GTT_DEPLOYMENT_MODE'] = 'standalone'
        os.environ['GTT_PUBLIC_URL'] = 'https://managed.example'
        os.environ['GTT_USER_DOCUMENTATION_URL'] = 'https://docs.example/user'
        os.environ['GTT_ADMIN_DOCUMENTATION_URL'] = 'https://docs.example/admin'

        self.assertEqual(managed_public_url(), '')
        self.assertEqual(managed_user_docs_url(), '')
        self.assertEqual(managed_admin_docs_url(), '')


if __name__ == '__main__':
    unittest.main()


if __name__ == '__main__':
    unittest.main()
