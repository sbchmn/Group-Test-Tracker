"""One-time registration notification setup; email stays active until verified."""
from datetime import datetime


def is_linked(user, channel):
    if channel == 'telegram':
        return bool(user.telegram_user_id and user.telegram_chat_id)
    if channel == 'discord':
        return bool(user.discord_user_id)
    return False


def clear_setup(user):
    user.pending_notification_channel = None
    user.notification_setup_expires_at = None


def resolve_setup(user):
    """Resolve completed/expired setup. Caller commits; return whether still pending."""
    channel = user.pending_notification_channel
    if not channel:
        return False
    # Expiration wins even when an old token is redeemed after the seven-day window.
    if not user.notification_setup_expires_at or user.notification_setup_expires_at <= datetime.utcnow():
        clear_setup(user)
        return False
    if is_linked(user, channel):
        user.notification_channel = channel
        clear_setup(user)
        return False
    return True
