"""Inbound HTTP endpoints for the SaaS control plane (cp_to_instance direction).

Deliberately isolated from the Telegram/Discord bot wiring in ``app.routes``:
these endpoints authenticate a different party (the private control-plane
service, not end users or bot platforms) using a distinct HMAC contract, and
must remain independently auditable.
"""

import hashlib
import secrets
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash

from . import control_plane, csrf, db
from .models import (
    RESERVED_SUPPORT_EMAIL,
    RESERVED_SUPPORT_SYSTEM_KEY,
    RESERVED_SUPPORT_USERNAME,
    ControlPlaneOperationReceipt,
    User,
)

control_plane_bp = Blueprint('control_plane', __name__)


def _verify_control_plane_request(method, path):
    """Fail-closed verification for signed SaaS control-plane requests.

    Returns ((verified_headers, raw_body), None) on success, or
    (None, (response, status_code)) when the caller should return immediately.
    """
    if not control_plane.managed_mode_enabled():
        return None, (jsonify({'error': 'not found'}), 404)
    secrets_by_key = control_plane.cp_secrets()
    if not secrets_by_key or not control_plane.tenant_id():
        return None, (jsonify({'error': 'not configured'}), 503)
    body = request.get_data(cache=True, as_text=False)
    try:
        verified = control_plane.verify_signed_headers(
            secrets_by_key=secrets_by_key,
            headers=request.headers,
            tenant_id=control_plane.tenant_id(),
            contract_version=control_plane.contract_version(),
            method=method,
            path=path,
            body=body,
        )
    except control_plane.SignatureError:
        return None, (jsonify({'error': 'invalid signature'}), 401)
    if not control_plane.reserve_nonce(verified['nonce']):
        db.session.rollback()
        return None, (jsonify({'error': 'replayed nonce'}), 401)
    return (verified, body), None


def _control_plane_receipt_response(operation_id, payload_digest):
    receipt = ControlPlaneOperationReceipt.query.filter_by(operation_id=operation_id).first()
    if receipt is None:
        return None
    if receipt.payload_digest != payload_digest:
        return jsonify({'error': 'operation payload conflict'}), 409
    return jsonify(receipt.response_body), receipt.response_code


def _record_control_plane_receipt(operation_id, payload_digest, response_code, response_body):
    db.session.add(ControlPlaneOperationReceipt(
        operation_id=operation_id, payload_digest=payload_digest,
        response_code=response_code, response_body=response_body,
    ))


@control_plane_bp.route('/internal/control-plane/v1/bootstrap', methods=['POST'])
@csrf.exempt
def control_plane_bootstrap():
    path = '/internal/control-plane/v1/bootstrap'
    result, error_response = _verify_control_plane_request('POST', path)
    if error_response:
        return error_response
    verified, body = result

    payload = request.get_json(silent=True) or {}
    username = str(payload.get('username') or '').strip()
    email = str(payload.get('email') or '').strip()
    password_hash = str(payload.get('password_hash') or '')
    support_username = str(payload.get('support_username') or '').strip()
    support_email = str(payload.get('support_email') or '').strip()
    if not (username and email and password_hash and support_username and support_email):
        db.session.rollback()
        return jsonify({'error': 'invalid payload'}), 400

    payload_digest = hashlib.sha256(body).hexdigest()
    cached = _control_plane_receipt_response(verified['operation_id'], payload_digest)
    if cached is not None:
        db.session.commit()
        return cached

    admin_user = User.query.filter_by(username=username).first()
    created = admin_user is None
    if admin_user is None:
        admin_user = User(username=username, email=email, password_hash=password_hash, is_admin=True, is_active=True)
        db.session.add(admin_user)
    else:
        admin_user.password_hash = password_hash
        admin_user.is_admin = True
        admin_user.is_active = True

    support_user = User.query.filter_by(system_account_key=RESERVED_SUPPORT_SYSTEM_KEY).first()
    if support_user is None:
        # Never adopt/overwrite a conflicting ordinary account with this normalized
        # identity; only a record carrying the reserved system key is authoritative.
        if User.query.filter_by(username=support_username).first() is not None:
            db.session.rollback()
            return jsonify({'error': 'reserved support identity conflict'}), 409
        created = True
        # Support access stays disabled until the /support endpoint enables it.
        db.session.add(User(
            username=support_username, email=support_email,
            password_hash=generate_password_hash(secrets.token_urlsafe(32), method='scrypt'),
            is_admin=True, is_active=False,
            system_account_key=RESERVED_SUPPORT_SYSTEM_KEY,
        ))

    response_body = {'acknowledged': True}
    response_code = 201 if created else 200
    _record_control_plane_receipt(verified['operation_id'], payload_digest, response_code, response_body)
    db.session.commit()
    return jsonify(response_body), response_code


@control_plane_bp.route('/internal/control-plane/v1/support', methods=['POST'])
@csrf.exempt
def control_plane_support():
    path = '/internal/control-plane/v1/support'
    result, error_response = _verify_control_plane_request('POST', path)
    if error_response:
        return error_response
    verified, body = result

    payload = request.get_json(silent=True) or {}
    action = str(payload.get('action') or '').strip()
    username = str(payload.get('username') or '').strip()
    email = str(payload.get('email') or '').strip()
    password_hash = payload.get('password_hash')
    credential_version = payload.get('credential_version')
    expires_at_value = payload.get('expires_at')
    if action not in {'rotate', 'enable', 'disable'} or not username or not email:
        db.session.rollback()
        return jsonify({'error': 'invalid payload'}), 400
    if username.casefold() != RESERVED_SUPPORT_USERNAME.casefold() or email.casefold() != RESERVED_SUPPORT_EMAIL.casefold():
        db.session.rollback()
        return jsonify({'error': 'invalid reserved identity'}), 400
    try:
        credential_version = int(credential_version)
    except (TypeError, ValueError):
        db.session.rollback()
        return jsonify({'error': 'invalid credential version'}), 400
    if credential_version <= 0:
        db.session.rollback()
        return jsonify({'error': 'invalid credential version'}), 400
    expires_at = None
    if expires_at_value is not None:
        try:
            expires_at = datetime.fromisoformat(str(expires_at_value).replace('Z', '+00:00'))
            if expires_at.tzinfo is not None:
                expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            db.session.rollback()
            return jsonify({'error': 'invalid expiry'}), 400
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    if action == 'enable' and (not password_hash or expires_at is None or expires_at <= now_utc):
        db.session.rollback()
        return jsonify({'error': 'invalid enable payload'}), 400
    if action == 'rotate' and not password_hash:
        db.session.rollback()
        return jsonify({'error': 'missing password hash'}), 400

    payload_digest = hashlib.sha256(body).hexdigest()
    cached = _control_plane_receipt_response(verified['operation_id'], payload_digest)
    if cached is not None:
        db.session.commit()
        return cached

    user = User.query.filter_by(system_account_key=RESERVED_SUPPORT_SYSTEM_KEY).first()
    if user is None:
        if User.query.filter_by(username=username).first() is not None:
            db.session.rollback()
            return jsonify({'error': 'reserved support identity conflict'}), 409
        user = User(
            username=username, email=email,
            password_hash=generate_password_hash(secrets.token_urlsafe(32), method='scrypt'),
            is_admin=True, is_active=False,
            system_account_key=RESERVED_SUPPORT_SYSTEM_KEY,
        )
        db.session.add(user)
        db.session.flush()
    elif user.username.casefold() != username.casefold() or user.email.casefold() != email.casefold():
        db.session.rollback()
        return jsonify({'error': 'reserved identity conflict'}), 409

    current_version = user.support_credential_version
    if current_version is not None:
        if credential_version < current_version or (action == 'rotate' and credential_version == current_version):
            db.session.rollback()
            return jsonify({'error': 'stale credential version'}), 409

    if action in {'rotate', 'enable'}:
        user.password_hash = str(password_hash)
        # A credential change must invalidate any existing support session immediately;
        # replacing the password hash alone is not sufficient session revocation.
        user.session_epoch += 1
    if action == 'enable':
        user.is_active = True
        user.support_state = 'enabled'
        user.support_credential_version = credential_version
        user.support_expires_at = expires_at
    elif action == 'rotate':
        user.is_active = False
        user.support_state = 'disabled'
        user.support_credential_version = credential_version
        user.support_expires_at = None
    elif action == 'disable':
        user.is_active = False
        user.support_state = 'disabled'
        user.support_credential_version = credential_version
        user.support_expires_at = None
        user.session_epoch += 1
        # Rotate the hash on disable so a leaked prior credential cannot be replayed.
        user.password_hash = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')

    response_body = {
        'accepted': True,
        'state': user.support_state,
        'credential_version': user.support_credential_version,
        'expires_at': user.support_expires_at.isoformat() if user.support_expires_at else None,
    }
    _record_control_plane_receipt(verified['operation_id'], payload_digest, 200, response_body)
    db.session.commit()
    return jsonify(response_body), 200
