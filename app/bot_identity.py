"""Provider-neutral bot identity: issuing, listing and claiming account link tokens.

Every chat integration links an account the same way -- a member generates a
single-use token on their profile page and sends it to the bot -- so the rules that
make that safe live here once rather than being re-derived per provider.

Claiming is deliberately row-locked and provider-scoped. Provider scoping means a
token minted for one platform cannot be redeemed on another, and the lock closes the
window between reading `used_at` and writing it, which is what makes a token
single-use under concurrent delivery.

Adding a provider means one entry in ``LINK_FIELDS``; Root's entry is added when its
identity column exists.
"""

from datetime import datetime, timedelta
import secrets

from . import db
from .models import BotLinkToken, User

LINK_TOKEN_TTL = timedelta(hours=24)

# Where each provider's identity lands on the User row.
#   external_id: stable account handle, unique across users -- the value a re-link
#                must not silently move away from its current owner.
#   chat_id:     optional routing target for direct messages.
#   username:    display handle, overwritten on every successful claim.
LINK_FIELDS = {
    "telegram": {
        "external_id": "telegram_user_id",
        "chat_id": "telegram_chat_id",
        "username": "tg_username",
    },
    "discord": {
        "external_id": "discord_user_id",
        "username": "discord_username",
    },
    "root": {
        "external_id": "root_user_id",
    },
}

# Claim outcomes. Everything except OK is a refusal that leaves the token unconsumed.
CLAIM_OK = "ok"
CLAIM_INVALID = "invalid"
CLAIM_INACTIVE_USER = "inactive-user"
CLAIM_MISSING_USER = "missing-user"
CLAIM_EXTERNAL_OWNED = "external-owned"
CLAIM_USER_OWNED = "user-owned"
CLAIM_UNKNOWN_PROVIDER = "unknown-provider"


def supports_provider(provider):
    """Report whether a provider can link accounts."""
    return provider in LINK_FIELDS


def issue_link_token(provider, user):
    """Create a single-use link token for a user. Caller commits."""
    if provider not in LINK_FIELDS:
        raise ValueError(f"unsupported link provider: {provider}")
    if user is None or user.id is None:
        return None

    token = BotLinkToken(
        provider=provider,
        user_id=user.id,
        token=secrets.token_urlsafe(24),
        expires_at=datetime.utcnow() + LINK_TOKEN_TTL,
    )
    db.session.add(token)
    return token


def active_link_token(provider, user):
    """Return the user's newest unconsumed, unexpired token for a provider."""
    if user is None or provider not in LINK_FIELDS:
        return None

    return (
        BotLinkToken.query
        .filter_by(provider=provider, user_id=user.id)
        .filter(BotLinkToken.used_at.is_(None), BotLinkToken.expires_at >= datetime.utcnow())
        .order_by(BotLinkToken.created_at.desc())
        .first()
    )


def claim_link_token(provider, token_value, external_id=None, chat_id=None, username=None):
    """Consume a link token and move the provider identity onto its owner.

    Returns ``(user, reason)``. On refusal ``user`` is None, the row lock is released
    and the token stays unconsumed so a legitimate retry can still succeed. The caller
    owns the commit.
    """
    fields = LINK_FIELDS.get(provider)
    if fields is None:
        return None, CLAIM_UNKNOWN_PROVIDER

    token_value = str(token_value or "").strip()
    if not token_value:
        return None, CLAIM_INVALID

    token = (
        BotLinkToken.query
        .filter_by(provider=provider, token=token_value)
        .with_for_update()
        .first()
    )
    if token is None or token.used_at is not None or token.expires_at < datetime.utcnow():
        return None, CLAIM_INVALID

    user = db.session.get(User, token.user_id)
    if user is None:
        return None, CLAIM_MISSING_USER
    if not user.is_active:
        return None, CLAIM_INACTIVE_USER

    external_column = fields.get("external_id")
    if external_column and external_id:
        normalized = str(external_id).strip()
        existing_owner = User.query.filter_by(**{external_column: normalized}).first()
        if existing_owner is not None and existing_owner.id != user.id:
            return None, CLAIM_EXTERNAL_OWNED
        current = getattr(user, external_column, None)
        if current and str(current) != normalized:
            return None, CLAIM_USER_OWNED
        setattr(user, external_column, normalized)

    chat_column = fields.get("chat_id")
    if chat_column and chat_id:
        setattr(user, chat_column, str(chat_id).strip())

    username_column = fields.get("username")
    if username_column and username:
        setattr(user, username_column, str(username).strip()[:80])

    token.used_at = datetime.utcnow()
    return user, CLAIM_OK
