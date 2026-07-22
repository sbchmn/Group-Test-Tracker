import base64
import json
import os
import re
from datetime import datetime
from pathlib import Path
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


def _notification_log_path():
    base_dir = os.path.join(current_app.root_path, os.pardir)
    log_dir = os.path.join(base_dir, "instance")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "notification.log")


def append_notification_log(message, debug=False):
    if debug and str(_get_config("notification_debug_enabled", "false")).lower() != "true":
        return None

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}\n"
    path = _notification_log_path()
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)

    max_bytes = current_app.config.get("NOTIFICATION_LOG_MAX_BYTES", 200000)
    if os.path.getsize(path) > max_bytes:
        with open(path, "r", encoding="utf-8") as handle:
            contents = handle.read()
        if len(contents) > max_bytes:
            keep = max_bytes // 2
            trimmed = contents[-keep:] if keep > 0 else ""
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(trimmed)
    return path


def read_notification_log():
    path = _notification_log_path()
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


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
    append_notification_log(f"mailjet: queued for {getattr(user, 'username', 'unknown')}")
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
        append_notification_log(f"mailjet: sent to {recipient_email}")
        return True
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        append_notification_log(f"mailjet: failed for {recipient_email}: {exc}")
        return False


def send_telegram_message(user, body):
    append_notification_log(f"telegram: queued for {getattr(user, 'username', 'unknown')}")
    bot_token = str(_get_config("telegram_bot_token") or "").strip()
    chat_id = str(_get_user_attr(user, "tg_username", None) or "").strip()
    if not bot_token or not chat_id:
        return False

    if not chat_id.startswith("@") and not re.fullmatch(r"-?\d+", chat_id):
        chat_id = f"@{chat_id}"

    payload = {"chat_id": chat_id, "text": body}
    payload_json = json.dumps(payload, ensure_ascii=False)
    safe_token = quote(bot_token, safe="")
    url = f"https://api.telegram.org/bot{safe_token}/sendMessage"
    debug_url = "https://api.telegram.org/bot<redacted>/sendMessage"
    append_notification_log(
        f"telegram: request url={debug_url} method=POST headers={{'Content-Type': 'application/json'}} payload={payload_json}",
        debug=True,
    )
    request = Request(
        url,
        data=payload_json.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, context=None) as response:
            response_body = response.read().decode("utf-8", errors="replace")

        try:
            parsed_response = json.loads(response_body) if response_body else {}
        except ValueError:
            parsed_response = {}

        if isinstance(parsed_response, dict):
            append_notification_log(
                f"telegram: response for {chat_id}: {json.dumps(parsed_response, ensure_ascii=False)}",
                debug=True,
            )
        elif response_body:
            append_notification_log(f"telegram: response for {chat_id}: {response_body}", debug=True)

        if isinstance(parsed_response, dict) and parsed_response.get("ok") is True:
            append_notification_log(f"telegram: sent to {chat_id}")
            return True

        description = parsed_response.get("description") if isinstance(parsed_response, dict) else None
        detail = description or response_body or "empty response"
        append_notification_log(f"telegram: failed for {chat_id}: {detail}")
        return False
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        error_body = ""
        if isinstance(exc, HTTPError):
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = str(exc)
        append_notification_log(f"telegram: failed for {chat_id}: {exc} | {error_body}")
        append_notification_log(f"telegram: exception details for {chat_id}: {exc} | {error_body}", debug=True)
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
