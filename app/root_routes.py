"""HTTP surface for the Root bridge.

Root hosts the bot side itself and accepts no inbound pushes, so everything here is
inverted from what you would expect: the Root-hosted bridge calls *us* to deliver
inbound chat events, and polls us to pick up outbound messages. The bridge is a
network caller with no session and no CSRF token, so every route here is signature
authenticated via app.root_bridge.

The event payload is a normalized shape defined by the bridge, not a raw Root event.
Keeping that translation on the bridge side means Root API changes do not reach into
this repo. See docs/root-bridge-spec.md.
"""

import json
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request

from . import csrf, db
from .bot_identity import CLAIM_OK, claim_link_token, supports_provider
from .models import RootInboundEvent, RootOutbox, User
from .notifications import append_notification_log
from .root_bridge import (
    ROOT_MAX_BODY_BYTES,
    BridgeAuthError,
    bridge_community_id,
    verify_bridge_request,
)

root_bp = Blueprint("root", __name__)

ROOT_PROVIDER = "root"

# Command parity with the Telegram/Discord bots is completed by Phase 1 increment 3,
# which extracts one resolver both platforms share. Until then Root answers this set
# directly; unknown commands get a hint rather than silence.
ROOT_COMMAND_HINT = (
    "Group Test Manager is not wired to that command yet. "
    "Try /help, or /start <token> to link your account."
)


def _verified_bridge_request():
    """Return the parsed JSON body, or raise BridgeAuthError.

    The raw bytes are read once and reused for both signature verification and
    parsing, because the signature covers the exact bytes on the wire.
    """
    raw = request.get_data(cache=False)
    if not raw:
        raise BridgeAuthError("empty request body")
    if len(raw) > ROOT_MAX_BODY_BYTES:
        raise BridgeAuthError("request body is too large")

    verify_bridge_request(
        method=request.method,
        path=request.path,
        headers=request.headers,
        body=raw,
    )

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        db.session.rollback()
        raise BridgeAuthError("body is not valid JSON") from None
    if not isinstance(payload, dict):
        db.session.rollback()
        raise BridgeAuthError("body must be a JSON object")
    return payload


def _reject(reason):
    db.session.rollback()
    append_notification_log(f"root: bridge request rejected: {reason}")
    return jsonify({"ok": False, "error": "request rejected"}), 403


def _queue_reply(channel_id, text, event_key=None):
    """Append a message for the bridge to carry into a Root channel."""
    outbox = RootOutbox(
        channel_id=str(channel_id or "").strip(),
        body=str(text or "").strip(),
        event_key=event_key,
    )
    if not outbox.channel_id or not outbox.body:
        return None
    db.session.add(outbox)
    return outbox


def _handle_start(argument, source_user_id):
    if not source_user_id:
        # Without an identity from the bridge there is nothing to link, and
        # claiming anyway would burn the member's single-use token for nothing.
        return (
            "Group Test Manager could not identify your Root account, so it cannot link it. "
            "Ask an administrator to check the bridge configuration."
        )
    user, reason = claim_link_token(
        ROOT_PROVIDER,
        argument,
        external_id=source_user_id,
    )
    if reason == CLAIM_OK:
        return (
            f"Your Root account is linked to {user.username}. "
            "Use /help to see available commands."
        )
    if reason == "inactive-user":
        return "This account is deactivated. Contact an administrator for account support."
    return "This link token is invalid or expired. Generate a new one from your profile page."


def _handle_help(source_user_id):
    linked = None
    if source_user_id:
        linked = User.query.filter_by(root_user_id=str(source_user_id).strip()).first()
    lines = [
        "Group Test Manager on Root:",
        "/start <token> - link your Root account to your profile",
        "/help - show this message",
    ]
    if linked is None:
        lines.append("")
        lines.append("You are not linked yet. Open your profile, generate a link token, then send /start <token>.")
    return "\n".join(lines)


@root_bp.route("/root/webhook", methods=["POST"])
@csrf.exempt
def root_webhook():
    """Accept one normalized Root event, usually a channel message."""
    try:
        payload = _verified_bridge_request()
    except BridgeAuthError as exc:
        return _reject(str(exc))

    community_id = bridge_community_id()
    if not community_id:
        return _reject("no community bound on this instance")
    if str(payload.get("communityId") or "").strip() != community_id:
        return _reject("communityId does not match this instance")

    message_id = str(payload.get("messageId") or "").strip()
    if not message_id:
        return _reject("payload is missing messageId")

    event_type = str(payload.get("event") or "").strip()
    channel_id = str(payload.get("channelId") or "").strip()
    source_user_id = str(payload.get("userId") or "").strip()
    content = str(payload.get("content") or "").strip()

    if RootInboundEvent.query.filter_by(message_id=message_id).first():
        db.session.commit()
        return jsonify({"ok": True, "duplicate": True})

    db.session.add(RootInboundEvent(
        message_id=message_id,
        event_type=event_type[:60],
        channel_id=channel_id[:120] or None,
        source_root_user_id=source_user_id[:40] or None,
    ))

    reply = None
    if event_type == "channelMessage.created" and content.startswith("/"):
        parts = content.split(None, 1)
        command = parts[0].lstrip("/").lower()
        argument = (parts[1] or "").strip() if len(parts) > 1 else ""
        if command == "help":
            reply = _handle_help(source_user_id)
        elif command == "start":
            if not supports_provider(ROOT_PROVIDER):
                reply = "Root account linking is not available on this instance."
            else:
                reply = _handle_start(argument, source_user_id)
        else:
            reply = ROOT_COMMAND_HINT

    if reply and channel_id:
        _queue_reply(channel_id, reply, event_key=f"evt:{message_id}")

    db.session.commit()
    return jsonify({"ok": True})


@root_bp.route("/root/outbox/claim", methods=["POST"])
@csrf.exempt
def root_outbox_claim():
    """Hand the bridge up to `limit` messages to deliver, under a time-boxed lease."""
    try:
        payload = _verified_bridge_request()
    except BridgeAuthError as exc:
        return _reject(str(exc))

    community_id = bridge_community_id()
    if str(payload.get("communityId") or "").strip() != community_id:
        return _reject("communityId does not match this instance")

    try:
        limit = int(payload.get("limit") or 5)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 20))

    lease_seconds = int(current_app.config.get("ROOT_OUTBOX_LEASE_SECONDS", 120))
    now = datetime.utcnow()
    token = secrets.token_urlsafe(18)

    due = (
        RootOutbox.query
        .filter(
            db.or_(
                # Never handed out, or waiting out a retry backoff.
                db.and_(
                    RootOutbox.status == RootOutbox.PENDING,
                    db.or_(
                        RootOutbox.next_attempt_at.is_(None),
                        RootOutbox.next_attempt_at <= now,
                    ),
                ),
                # Handed out, but the bridge never acknowledged before its lease lapsed.
                db.and_(
                    RootOutbox.status == RootOutbox.CLAIMED,
                    RootOutbox.lease_expires_at.isnot(None),
                    RootOutbox.lease_expires_at < now,
                ),
            ),
        )
        .order_by(RootOutbox.created_at)
        .limit(limit)
        .with_for_update()
        .all()
    )

    messages = []
    for row in due:
        row.status = RootOutbox.CLAIMED
        row.attempt_count = (row.attempt_count or 0) + 1
        row.lease_token = token
        row.lease_expires_at = now + timedelta(seconds=lease_seconds)
        messages.append({"id": row.id, "channelId": row.channel_id, "body": row.body})

    db.session.commit()
    return jsonify({"ok": True, "leaseToken": token, "messages": messages, "retryAfterSeconds": lease_seconds})


@root_bp.route("/root/outbox/ack", methods=["POST"])
@csrf.exempt
def root_outbox_ack():
    """Record the bridge's delivery result for claimed messages."""
    try:
        payload = _verified_bridge_request()
    except BridgeAuthError as exc:
        return _reject(str(exc))

    lease_token = str(payload.get("leaseToken") or "").strip()
    if not lease_token:
        return _reject("ack is missing leaseToken")

    results = payload.get("results")
    if not isinstance(results, list):
        return _reject("ack is missing a results list")

    for result in results:
        if not isinstance(result, dict):
            continue
        try:
            message_id = int(result.get("id"))
        except (TypeError, ValueError):
            continue
        row = RootOutbox.query.filter_by(id=message_id, lease_token=lease_token).first()
        if row is None:
            continue
        if result.get("delivered"):
            row.status = RootOutbox.SENT
            row.sent_at = datetime.utcnow()
            row.lease_token = None
            row.lease_expires_at = None
            continue

        row.last_error = str(result.get("error") or "bridge reported failure")[:300]
        row.lease_token = None
        row.lease_expires_at = None
        if row.attempt_count >= row.max_attempts:
            row.status = RootOutbox.FAILED
        else:
            row.status = RootOutbox.PENDING
            row.next_attempt_at = datetime.utcnow() + timedelta(seconds=min(300, 15 * (2 ** row.attempt_count)))

    db.session.commit()
    return jsonify({"ok": True})


@root_bp.route("/root/outbox/stats", methods=["POST"])
@csrf.exempt
def root_outbox_stats():
    """Counters the bridge can surface in its own logs while debugging a deploy."""
    try:
        _verified_bridge_request()
    except BridgeAuthError as exc:
        return _reject(str(exc))

    now = datetime.utcnow()
    return jsonify({
        "ok": True,
        "pending": RootOutbox.query.filter(RootOutbox.status.in_([RootOutbox.PENDING, RootOutbox.CLAIMED])).count(),
        "sent": RootOutbox.query.filter_by(status=RootOutbox.SENT).count(),
        "failed": RootOutbox.query.filter_by(status=RootOutbox.FAILED).count(),
        "serverTime": now.isoformat(),
    })
