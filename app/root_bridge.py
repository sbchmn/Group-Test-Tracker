"""Authentication for the Root bridge: the Root-hosted bot that talks to us.

Root exposes no inbound webhook and cannot be pushed to, so the integration is
inverted: a TypeScript bot hosted inside Root POSTs normalized events to us, and
polls us for outbound messages. That makes the bridge an unauthenticated network
caller unless every request is signed, so both directions use the HMAC scheme below.

Design notes for whoever builds the bridge:
  * The signature covers the *raw* request body bytes, so sign before serializing
    changes (re-order keys, re-encode) or verification fails.
  * Nonces are stored, so a captured request cannot be replayed inside the window.
  * Secrets are per-tenant: each managed instance holds its own key id + secret in
    NotificationConfig, and the bridge is configured with the same pair.
  * See docs/root-bridge-spec.md for the full contract, payloads and error codes.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from . import db
from .models import NotificationConfig, RootBridgeNonce

ROOT_CONTRACT_VERSION = "root-bridge-v1"
ROOT_SIGNATURE_WINDOW_SECONDS = 300
ROOT_MAX_BODY_BYTES = 65536
ROOT_NONCE_BYTES = 16

BRIDGE_SECRET_KEY = "root_bridge_secret"
BRIDGE_KEY_ID_KEY = "root_bridge_key_id"
BRIDGE_COMMUNITY_KEY = "root_community_id"
BRIDGE_STATUS_CHANNEL_KEY = "root_status_channel_id"

HEADER_KEY_ID = "X-Root-Bridge-Key-Id"
HEADER_TIMESTAMP = "X-Root-Bridge-Timestamp"
HEADER_NONCE = "X-Root-Bridge-Nonce"
HEADER_SIGNATURE = "X-Root-Bridge-Signature"


class BridgeAuthError(Exception):
    """Raised for any failed authentication, replay or freshness check.

    The caller turns this into a single generic 403; the specific reason is logged
    rather than returned, so the endpoint does not become an oracle for which step
    a caller got right.
    """


def _config_value(key):
    item = NotificationConfig.query.filter_by(key=key).first()
    return str(item.value).strip() if item and item.value else ""


def bridge_credentials():
    """Return the (key_id, secret) pair this instance expects, or empty values."""
    return _config_value(BRIDGE_KEY_ID_KEY), _config_value(BRIDGE_SECRET_KEY)


def bridge_community_id():
    return _config_value(BRIDGE_COMMUNITY_KEY)


def bridge_status_channel_id():
    return _config_value(BRIDGE_STATUS_CHANNEL_KEY)


def generate_bridge_key_id():
    return f"root-{secrets.token_hex(6)}"


def generate_bridge_secret():
    return secrets.token_hex(32)


def canonical_request(*, method, path, key_id, timestamp, nonce, body):
    """Build the exact string both sides must sign.

    Fields are joined with newlines and the version prefix, so no field value can be
    reshaped into another field's position.
    """
    if isinstance(body, str):
        body = body.encode("utf-8")
    body_digest = hashlib.sha256(body or b"").hexdigest()
    return "\n".join([
        ROOT_CONTRACT_VERSION,
        str(method).upper(),
        str(path),
        str(key_id),
        str(timestamp),
        str(nonce),
        body_digest,
    ])


def sign_request(secret, *, method, path, key_id, timestamp, nonce, body):
    """Produce the signature header value for a request. Used by tests and tooling."""
    message = canonical_request(
        method=method, path=path, key_id=key_id,
        timestamp=timestamp, nonce=nonce, body=body,
    )
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def request_headers(secret, *, key_id, method, path, body, nonce=None, timestamp=None):
    """Return the full header set a bridge client must send."""
    timestamp = str(timestamp if timestamp is not None else int(datetime.now(timezone.utc).timestamp()))
    nonce = nonce or secrets.token_hex(ROOT_NONCE_BYTES)
    signature = sign_request(
        secret, method=method, path=path, key_id=key_id,
        timestamp=timestamp, nonce=nonce, body=body,
    )
    return {
        HEADER_KEY_ID: key_id,
        HEADER_TIMESTAMP: timestamp,
        HEADER_NONCE: nonce,
        HEADER_SIGNATURE: signature,
    }


def _require_headers(headers):
    key_id = str(headers.get(HEADER_KEY_ID) or "").strip()
    timestamp = str(headers.get(HEADER_TIMESTAMP) or "").strip()
    nonce = str(headers.get(HEADER_NONCE) or "").strip()
    signature = str(headers.get(HEADER_SIGNATURE) or "").strip()
    if not key_id or not timestamp or not nonce or not signature:
        raise BridgeAuthError("missing signature headers")
    return key_id, timestamp, nonce, signature


def _reserve_nonce(key_id, nonce, expires_at):
    """Claim a nonce, returning False when it was already seen. Caller commits."""
    digest = hashlib.sha256(f"{key_id}:{nonce}".encode("utf-8")).hexdigest()
    existing = RootBridgeNonce.query.filter_by(nonce_digest=digest).first()
    if existing is not None:
        return False
    db.session.add(RootBridgeNonce(nonce_digest=digest, expires_at=expires_at))
    db.session.flush()
    return True


def verify_bridge_request(*, method, path, headers, body):
    """Verify a bridge request. Raises BridgeAuthError on any failure.

    On success the nonce is consumed, so this is not idempotent: call it once per
    request and only after the body has been read. The row is written but not
    committed here; the caller commits when it accepts the request.
    """
    configured_key_id, secret = bridge_credentials()
    if not secret or not configured_key_id:
        raise BridgeAuthError("bridge is not configured")

    key_id, timestamp, nonce, signature = _require_headers(headers)

    if not hmac.compare_digest(key_id, configured_key_id):
        raise BridgeAuthError("unknown key id")

    try:
        request_time = int(timestamp)
    except (TypeError, ValueError):
        raise BridgeAuthError("timestamp is not an integer") from None

    now = int(datetime.now(timezone.utc).timestamp())
    if abs(now - request_time) > ROOT_SIGNATURE_WINDOW_SECONDS:
        raise BridgeAuthError("timestamp outside the acceptance window")

    if len(nonce) < 16 or len(nonce) > 128:
        raise BridgeAuthError("nonce has an unusable length")

    expected = sign_request(
        secret, method=method, path=path, key_id=key_id,
        timestamp=timestamp, nonce=nonce, body=body,
    )
    if not hmac.compare_digest(expected, signature):
        raise BridgeAuthError("signature mismatch")

    ttl = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=ROOT_SIGNATURE_WINDOW_SECONDS * 2)
    if not _reserve_nonce(key_id, nonce, ttl):
        raise BridgeAuthError("nonce already used")


def prune_expired_nonces(now=None):
    """Drop replay records past their acceptance window. Returns rows removed."""
    cutoff = (now or datetime.utcnow())
    deleted = RootBridgeNonce.query.filter(RootBridgeNonce.expires_at < cutoff).delete()
    db.session.commit()
    return deleted
