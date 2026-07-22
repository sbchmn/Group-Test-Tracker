import os
import re
from datetime import datetime
from flask import current_app

from . import db
from .models import NotificationConfig, NotificationTemplate, User


def _get_config(key, default=None):
    item = NotificationConfig.query.filter_by(key=key).first()
    if item is None:
        return default
    return item.value


def render_notification_template(template_text, context):
    if not template_text:
        return ""
    pattern = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
    return pattern.sub(lambda m: str(context.get(m.group(1), "")), template_text)


def send_notification_message(user, channel, subject, body):
    if channel == "telegram":
        return send_telegram_message(user, body)
    return send_mailjet_message(user, subject, body)


def send_mailjet_message(user, subject, body):
    api_key = _get_config("mailjet_api_key")
    secret_key = _get_config("mailjet_secret_key")
    sender_email = _get_config("mailjet_sender_email")
    if not api_key or not secret_key or not sender_email:
        return False

    # Placeholder implementation for the requested architecture.
    # In production, this would call Mailjet's API.
    return True


def send_telegram_message(user, body):
    bot_token = _get_config("telegram_bot_token")
    chat_id = user.tg_username if user.tg_username else None
    if not bot_token or not chat_id:
        return False

    # Placeholder implementation for the requested architecture.
    # In production, this would call Telegram Bot API.
    return True


def send_password_reset(user, new_password):
    template = NotificationTemplate.query.filter_by(is_default_password_reset=True, is_active=True).first()
    if template is None:
        body = f"Your new password is: {new_password}"
        subject = "Password Reset"
    else:
        body = render_notification_template(template.telegram_body or template.email_body or "", {"new_password": new_password, "username": user.username})
        subject = template.email_subject or "Password Reset"

    channel = user.notification_channel or "email"
    return send_notification_message(user, channel, subject, body)


def send_group_test_notification(test, user, template, amount_owed=None):
    context = {
        "username": user.username,
        "amount_owed": f"{amount_owed:.2f}" if amount_owed is not None else "",
        "test_title": test.title,
        "test_link": f"{current_app.config.get('SERVER_NAME', 'http://localhost')}/test/{test.id}",
        "test_id": str(test.id),
    }
    email_subject = render_notification_template(template.email_subject or "", context)
    email_body = render_notification_template(template.email_body or "", context)
    telegram_body = render_notification_template(template.telegram_body or "", context)

    channel = user.notification_channel or "email"
    if channel == "telegram":
        return send_notification_message(user, "telegram", email_subject, telegram_body)
    return send_notification_message(user, "email", email_subject, email_body)
