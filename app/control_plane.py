"""Verification for signed requests from the SaaS control plane.

Mirrors the HMAC contract implemented by the private
`sbchmn/Group-Test-Tracker-Control-Plane` repository's
`app/services/hmac_contract.py` so inbound `cp_to_instance` requests can be
verified without importing that private codebase.
"""

import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from . import db
from .models import ControlPlaneNonce

HEADER_PREFIX = 'X-GTT-'
MAX_AGE_SECONDS = 120
MAX_CLOCK_SKEW_SECONDS = 60
_HEADER_LIMITS = {
    'Key-ID': 80, 'Tenant': 64, 'Contract': 32, 'Timestamp': 20, 'Nonce': 128,
    'Operation-ID': 128, 'Revision': 20, 'Body-SHA256': 64, 'Signature': 64,
}


class SignatureError(ValueError):
    pass


def managed_mode_enabled():
    return os.environ.get('GTT_DEPLOYMENT_MODE', 'standalone').strip().lower() == 'managed'


def tenant_id():
    return os.environ.get('GTT_TENANT_ID', '').strip()


def contract_version():
    return os.environ.get('GTT_CONTRACT_VERSION', '1').strip()


def cp_secrets():
    """Current (and, during rotation, previous) cp_to_instance key/secret pairs."""
    secrets_by_key = {}
    key_id = os.environ.get('GTT_CP_TO_INSTANCE_KEY_ID', '').strip()
    secret = os.environ.get('GTT_CP_TO_INSTANCE_SECRET', '').strip()
    if key_id and secret:
        secrets_by_key[key_id] = secret
    previous_key_id = os.environ.get('GTT_CP_TO_INSTANCE_KEY_ID_PREVIOUS', '').strip()
    previous_secret = os.environ.get('GTT_CP_TO_INSTANCE_SECRET_PREVIOUS', '').strip()
    if previous_key_id and previous_secret:
        secrets_by_key[previous_key_id] = previous_secret
    return secrets_by_key


def _body_digest(body):
    return hashlib.sha256(body).hexdigest()


def _canonical_message(*, key_id, tenant_id, contract_version, method, path, timestamp, nonce, operation_id, revision, digest):
    fields = [key_id, tenant_id, contract_version, method.upper(), path, str(timestamp), nonce, operation_id, str(revision), digest]
    return '\n'.join(fields).encode('utf-8')


def verify_signed_headers(*, secrets_by_key, headers, tenant_id, contract_version, method, path, body=b'', now=None):
    def required(name):
        value = headers.get(f'{HEADER_PREFIX}{name}')
        if not value:
            raise SignatureError(f'missing {name}')
        if len(value) > _HEADER_LIMITS[name]:
            raise SignatureError(f'oversized {name}')
        return value

    key_id = required('Key-ID')
    secret = secrets_by_key.get(key_id)
    if not secret:
        raise SignatureError('unknown key')
    if not hmac.compare_digest(required('Tenant'), tenant_id):
        raise SignatureError('wrong tenant')
    if not hmac.compare_digest(required('Contract'), contract_version):
        raise SignatureError('wrong contract')
    try:
        timestamp = int(required('Timestamp'))
        revision = int(required('Revision'))
    except ValueError as exc:
        raise SignatureError('invalid numeric header') from exc
    current = int(time.time() if now is None else now)
    if timestamp > current + MAX_CLOCK_SKEW_SECONDS or current - timestamp > MAX_AGE_SECONDS:
        raise SignatureError('expired request')
    digest = _body_digest(body)
    if len(required('Signature')) != 64 or len(required('Body-SHA256')) != 64:
        raise SignatureError('invalid digest encoding')
    if not hmac.compare_digest(required('Body-SHA256'), digest):
        raise SignatureError('body digest mismatch')
    nonce = required('Nonce')
    operation_id = required('Operation-ID')
    message = _canonical_message(
        key_id=key_id, tenant_id=tenant_id, contract_version=contract_version,
        method=method, path=path, timestamp=timestamp, nonce=nonce,
        operation_id=operation_id, revision=revision, digest=digest,
    )
    expected = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(required('Signature'), expected):
        raise SignatureError('invalid signature')
    return {'key_id': key_id, 'timestamp': timestamp, 'nonce': nonce, 'operation_id': operation_id, 'revision': revision}


def reserve_nonce(nonce):
    """Reject a signed request whose nonce was already used (replay defense)."""
    digest = hashlib.sha256(nonce.encode('utf-8')).hexdigest()
    if ControlPlaneNonce.query.filter_by(nonce_digest=digest).first() is not None:
        return False
    db.session.add(ControlPlaneNonce(nonce_digest=digest, expires_at=datetime.utcnow() + timedelta(minutes=10)))
    try:
        db.session.flush()
    except IntegrityError:
        return False
    return True
