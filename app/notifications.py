import base64
import json
import os
import re
from datetime import datetime
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from flask import current_app

from . import db
from .models import NotificationConfig, NotificationTemplate, User


def _get_config(key, default=None):
    item = NotificationConfig.query.filter_by(key=key).first()
    if item is None:
        return default
    return item.value


def _get_user_attr(user, attr, default=None):
    if user is None:
        return default

    try:
        return getattr(user, attr, default)
    except Exception:
        pass

    try:
        return user.__dict__.get(attr, default)
    except Exception:
        pass

    try:
        user_id = user.id
    except Exception:
        user_id = None

    if user_id is not None:
        try:
            fresh_user = db.session.get(User, int(user_id))
        except Exception:
            fresh_user = None
        if fresh_user is not None:
            try:
                return getattr(fresh_user, attr, default)
            except Exception:
                pass

    return default


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

    recipient_email = _get_user_attr(user, "email", None)
    recipient_name = _get_user_attr(user, "username", None)
    if not recipient_email:
        return False

    payload = {
        "Messages": [
            {
                "From": {"Email": sender_email, "Name": "Group Test Tracker"},
                "To": [{"Email": recipient_email, "Name": recipient_name or recipient_email}],
                "Subject": subject,
                "TextPart": body,
                "HTMLPart": body,
            }
        ]
    }

    data = json.dumps(payload).encode("utf-8")
    auth_string = base64.b64encode(f"{api_key}:{secret_key}".encode("utf-8")).decode("ascii")
    request = Request(
        "https://api.mailjet.com/v3.1/send",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_string}",
        },
        method="POST",
    )

    try:
        with urlopen(request, context=None) as response:
            response.read()
        return True
    except (HTTPError, URLError, TimeoutError, ValueError):
        return False


def send_telegram_message(user, body):
    bot_token = _get_config("telegram_bot_token")
    chat_id = _get_user_attr(user, "tg_username", None) or None
    if not bot_token or not chat_id:
        return False

    payload = urlencode({"chat_id": chat_id, "text": body})
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage?{payload}"
    request = Request(url, method="GET")

    try:
        with urlopen(request, context=None) as response:
            response.read()
        return True
    except (HTTPError, URLError, TimeoutError, ValueError):
        return False


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
