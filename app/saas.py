"""Managed-deployment SaaS contract helpers for GTM.

This module centralizes the environment contract the private control plane
expects for tenant entitlement, subscription status, and documentation links.
The logic is intentionally fail-closed for managed deployments and permissive for
standalone/local operation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Iterable
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError


HEADER_PREFIX = 'X-GTT-'


def managed_mode_enabled():
    return os.environ.get('GTT_DEPLOYMENT_MODE', 'standalone').strip().lower() == 'managed'


def tenant_id():
    return os.environ.get('GTT_TENANT_ID', '').strip()


def managed_public_url():
    if not managed_mode_enabled():
        return ''
    value = os.environ.get('GTT_PUBLIC_URL', '').strip()
    if value:
        return value.rstrip('/')
    return ''


def managed_user_docs_url():
    if not managed_mode_enabled():
        return ''
    return os.environ.get('GTT_USER_DOCUMENTATION_URL', '').strip()


def managed_admin_docs_url():
    if not managed_mode_enabled():
        return ''
    return os.environ.get('GTT_ADMIN_DOCUMENTATION_URL', '').strip()


def entitlement_revision():
    raw = os.environ.get('GTT_ENTITLEMENT_REVISION', '0').strip()
    try:
        return int(raw or '0')
    except ValueError:
        return 0


def _normalize_entitlements(raw: str) -> set[str]:
    return {item.strip().lower() for item in str(raw or '').split(',') if item.strip()}


def entitlements() -> set[str]:
    return _normalize_entitlements(os.environ.get('GTT_ENTITLEMENTS', ''))


def entitlement_enabled(feature: str) -> bool:
    feature_name = str(feature or '').strip().lower()
    if not feature_name:
        return False
    if not managed_mode_enabled():
        return True
    return feature_name in entitlements()


def subscription_status():
    return os.environ.get('GTT_SUBSCRIPTION_STATUS', 'active').strip().lower() or 'active'


def subscription_is_readonly():
    if not managed_mode_enabled():
        return False
    return subscription_status() in {'suspended', 'canceled', 'cancelled', 'expired'}


def subscription_access_allowed(feature: str | None = None) -> bool:
    if not managed_mode_enabled():
        return True
    status = subscription_status()
    if status in {'active', 'trial', 'past_due'}:
        if feature is None:
            return True
        return entitlement_enabled(feature)
    if subscription_is_readonly():
        if feature is None:
            return True
        return False
    return True


def instance_status_payload(*, component: str, ready: bool, schema_bytes: int = 0, pool_checked_out: int = 0, pool_capacity: int = 0) -> dict:
    """Build the stable status body consumed by the private control plane."""
    from .version import APP_VERSION

    def bounded_metric(value):
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    return {
        'component': str(component or 'web')[:64],
        'application_version': APP_VERSION[:64],
        'schema_revision': os.environ.get('GTT_SCHEMA_REVISION', 'b3c4d5e6f7a8')[:128],
        'contract_version': os.environ.get('GTT_CONTRACT_VERSION', '1').strip() or '1',
        'entitlement_revision': entitlement_revision(),
        'schema_bytes': bounded_metric(schema_bytes),
        'pool_checked_out': bounded_metric(pool_checked_out),
        'pool_capacity': bounded_metric(pool_capacity),
        'ready': bool(ready),
    }


def _instance_to_cp_url():
    base_url = os.environ.get('GTT_CONTROL_PLANE_URL', '').strip().rstrip('/')
    if not base_url:
        return ''
    tenant = tenant_id()
    if not tenant:
        return ''
    return f'{base_url}/internal/tenants/{tenant}/events'


def _instance_event_signature(secret: str, *, key_id: str, tenant: str, operation_id: str, payload: dict) -> tuple[dict, bytes]:
    body = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    timestamp = int(time.time())
    nonce = secrets.token_urlsafe(24)
    digest = hashlib.sha256(body).hexdigest()
    message = '\n'.join([
        key_id,
        tenant,
        os.environ.get('GTT_CONTRACT_VERSION', '1').strip() or '1',
        'POST',
        '/internal/tenants/' + tenant + '/events',
        str(timestamp),
        nonce,
        operation_id,
        str(entitlement_revision()),
        digest,
    ]).encode('utf-8')
    signature = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()
    headers = {
        f'{HEADER_PREFIX}Key-ID': key_id,
        f'{HEADER_PREFIX}Tenant': tenant,
        f'{HEADER_PREFIX}Contract': os.environ.get('GTT_CONTRACT_VERSION', '1').strip() or '1',
        f'{HEADER_PREFIX}Timestamp': str(timestamp),
        f'{HEADER_PREFIX}Nonce': nonce,
        f'{HEADER_PREFIX}Operation-ID': operation_id,
        f'{HEADER_PREFIX}Revision': str(entitlement_revision()),
        f'{HEADER_PREFIX}Body-SHA256': digest,
        f'{HEADER_PREFIX}Signature': signature,
        'Content-Type': 'application/json',
    }
    return headers, body


def report_instance_event(event_name: str, payload: dict | None = None):
    """Send a signed instance-to-control-plane event when managed mode is active."""
    if not managed_mode_enabled():
        return False
    event_name = str(event_name or '').strip()
    if not event_name:
        return False
    url = _instance_to_cp_url()
    key_id = os.environ.get('GTT_INSTANCE_TO_CP_KEY_ID', '').strip()
    secret = os.environ.get('GTT_INSTANCE_TO_CP_SECRET', '').strip()
    if not url or not key_id or not secret:
        return False

    event_body = {'type': event_name, **(payload or {})}
    operation_id = f'instance:{event_name}:{int(time.time())}:{secrets.token_urlsafe(12)}'
    headers, body = _instance_event_signature(secret, key_id=key_id, tenant=tenant_id(), operation_id=operation_id, payload=event_body)
    req = urllib_request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib_request.urlopen(req, timeout=10) as response:
            response_body = response.read()
            return json.loads(response_body.decode('utf-8')) if response_body else {'ok': True}
    except (HTTPError, URLError, ValueError):
        return False