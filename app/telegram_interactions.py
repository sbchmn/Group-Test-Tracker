"""Persistent Telegram prompt ownership and menu cleanup, shared by web/worker."""
from datetime import datetime, timedelta

from sqlalchemy import or_, update

from . import db
from .models import TelegramInteraction
from .notifications import (
    append_notification_log, delete_telegram_message, delete_telegram_ephemeral_message,
)


def find_interaction(kind, chat_id, message_id, ephemeral=False, telegram_user_id=None):
    query = TelegramInteraction.query.filter_by(
        kind=kind, chat_id=str(chat_id), bot_message_id=str(message_id),
        is_ephemeral=ephemeral,
    )
    if telegram_user_id is not None:
        query = query.filter_by(telegram_user_id=str(telegram_user_id))
    return query.order_by(TelegramInteraction.id.desc()).first()


def close_public_results(interaction):
    """Close immediately; retain unsuccessful deletes for bounded worker retries."""
    now = datetime.utcnow()
    if interaction.closed_at is None:
        interaction.closed_at = now
    db.session.commit()
    # Claim a short lease so the web close button and multiple workers don't
    # delete the same ephemeral identifier concurrently (Telegram reuses IDs).
    claimed = db.session.execute(update(TelegramInteraction).where(
        TelegramInteraction.id == interaction.id,
        TelegramInteraction.cleanup_complete.is_(False),
        or_(TelegramInteraction.next_attempt_at.is_(None), TelegramInteraction.next_attempt_at <= now),
    ).values(next_attempt_at=now + timedelta(minutes=2)))
    db.session.commit()
    if not claimed.rowcount:
        return True
    db.session.refresh(interaction)
    if not interaction.menu_deleted:
        if interaction.is_ephemeral:
            interaction.menu_deleted = delete_telegram_ephemeral_message(
                interaction.chat_id, interaction.telegram_user_id, interaction.bot_message_id)
        else:
            interaction.menu_deleted = delete_telegram_message(interaction.chat_id, interaction.bot_message_id)
    if not interaction.command_deleted:
        if not interaction.command_message_id:
            interaction.command_deleted = True
        elif interaction.command_is_ephemeral:
            interaction.command_deleted = delete_telegram_ephemeral_message(
                interaction.chat_id, interaction.telegram_user_id, interaction.command_message_id)
        else:
            interaction.command_deleted = delete_telegram_message(interaction.chat_id, interaction.command_message_id)
    interaction.cleanup_attempts += 1
    interaction.cleanup_complete = interaction.menu_deleted and interaction.command_deleted
    if interaction.cleanup_attempts >= 5 and not interaction.cleanup_complete:
        append_notification_log(
            f'telegram: publicresults cleanup abandoned interaction={interaction.id} '
            f'menu_deleted={interaction.menu_deleted} command_deleted={interaction.command_deleted}; '
            'check bot delete-message permissions')
        interaction.cleanup_complete = True
    interaction.next_attempt_at = now + timedelta(seconds=30)
    db.session.commit()
    return True


def cleanup_due_interactions(now=None):
    now = now or datetime.utcnow()
    due = TelegramInteraction.query.filter(
        TelegramInteraction.kind == 'publicresults',
        TelegramInteraction.cleanup_complete.is_(False),
        or_(TelegramInteraction.expires_at <= now, TelegramInteraction.closed_at.is_not(None)),
        or_(TelegramInteraction.next_attempt_at.is_(None), TelegramInteraction.next_attempt_at <= now),
    ).order_by(TelegramInteraction.expires_at).limit(100).all()
    for interaction in due:
        close_public_results(interaction)
    # Prompts are single-use and expire after a day. Keep closed menu records a
    # day for rejecting stale callbacks, then prune without retaining user data.
    TelegramInteraction.query.filter(
        or_(
            (TelegramInteraction.kind == 'coa_prompt') & (TelegramInteraction.expires_at <= now),
            TelegramInteraction.cleanup_complete.is_(True) &
            (TelegramInteraction.closed_at < now - timedelta(days=1)),
        )
    ).delete(synchronize_session=False)
    db.session.commit()
    return len(due)
