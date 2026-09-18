import base64
import io
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from . import db
from .models import NotificationConfig, NotificationTemplate, RootOutbox, User, UserDigestEvent
from .bot_dispatch import post_json
from .root_bridge import bridge_status_channel_id
from .saas import managed_public_url

# gthread workers do not preempt hung request threads, so every synchronous
# provider call must carry its own socket timeout.
OUTBOUND_HTTP_TIMEOUT_SECONDS = 10


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
    configured_path = current_app.config.get("NOTIFICATION_LOG_PATH")
    if configured_path:
        configured_path = os.path.abspath(str(configured_path))
        os.makedirs(os.path.dirname(configured_path), exist_ok=True)
        return configured_path

    base_dir = os.path.join(current_app.root_path, os.pardir)
    log_dir = os.path.join(base_dir, "instance")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "notification.log")


def _sanitize_notification_log_contents(contents):
    if not contents:
        return ""

    if contents.startswith("["):
        return contents

    first_bracket = contents.find("[")
    if first_bracket != -1:
        return contents[first_bracket:]

    # If no recognizable log marker exists, keep only the tail to avoid massive junk blocks.
    return contents[-2000:]


def _prune_notification_log_contents(contents, max_bytes):
    cleaned = _sanitize_notification_log_contents(contents)
    if not cleaned:
        return cleaned

    if len(cleaned.encode("utf-8", errors="ignore")) <= max_bytes:
        return cleaned

    keep_bytes = max(max_bytes // 2, 1024)
    tail = cleaned[-keep_bytes:]

    # Prefer starting at a full timestamped line.
    marker_idx = tail.find("\n[")
    if marker_idx != -1:
        tail = tail[marker_idx + 1:]
    elif not tail.startswith("["):
        first_bracket = tail.find("[")
        if first_bracket != -1:
            tail = tail[first_bracket:]

    return tail.lstrip("\n")


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
        trimmed = _prune_notification_log_contents(contents, int(max_bytes))
        if trimmed != contents:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(trimmed)
    return path


def read_notification_log():
    path = _notification_log_path()
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        contents = handle.read()

    cleaned = _sanitize_notification_log_contents(contents)
    if cleaned != contents:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(cleaned)

    return cleaned


def render_notification_template(template_text, context):
    if not template_text:
        return ""
    pattern = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
    return pattern.sub(lambda m: str(context.get(m.group(1), "")), template_text)


def select_template_body(bodies, channel):
    """Resolve the body for a channel from a {channel: rendered_body} mapping.

    Chat providers fall back to the plain-text Telegram body before the HTML email
    body, so a channel never receives markup it cannot render while its own body is
    still unset.
    """
    if channel == "email":
        return bodies.get("email")
    return bodies.get(channel) or bodies.get("telegram") or bodies.get("email")


def template_bodies(template, context=None):
    """Render every provider body variant of a notification template."""
    def render(value):
        text = value or ""
        return render_notification_template(text, context) if context else text

    return {
        "email": render(template.email_body),
        "telegram": render(template.telegram_body),
        "discord": render(template.discord_body),
        "root": render(template.root_body),
    }


def send_notification_message(user, channel, subject, body):
    deliver = _CHANNEL_SENDERS.get(channel)
    if deliver is None or deliver is _deliver_email:
        return _deliver_email(user, subject, body)

    if deliver(user, subject, body):
        return True

    append_notification_log(
        f"{channel}: falling back to email for {getattr(user, 'username', 'unknown')}"
    )
    return _deliver_email(user, subject, body)


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
    append_notification_log(
        f"mailjet: request url=https://api.mailjet.com/v3.1/send method=POST headers={{'Content-Type': 'application/json'}} payload={json.dumps(payload, ensure_ascii=False)}",
        debug=True,
    )

    try:
        with urlopen(request, context=None, timeout=OUTBOUND_HTTP_TIMEOUT_SECONDS) as response:
            response_body = response.read().decode("utf-8", errors="replace")

        try:
            parsed_response = json.loads(response_body) if response_body else {}
        except ValueError:
            parsed_response = {}

        if isinstance(parsed_response, dict):
            append_notification_log(
                f"mailjet: response for {recipient_email}: {json.dumps(parsed_response, ensure_ascii=False)}",
                debug=True,
            )
            messages = parsed_response.get("Messages")
            if isinstance(messages, list):
                failed_messages = [
                    msg for msg in messages
                    if isinstance(msg, dict) and msg.get("Status") == "error"
                ]
                if failed_messages:
                    errors = []
                    for msg in failed_messages:
                        errors.extend(
                            err.get("ErrorMessage") or str(err)
                            for err in msg.get("Errors", [])
                            if isinstance(err, dict)
                        )
                    detail = "; ".join(errors) if errors else "Mailjet returned per-message errors"
                    append_notification_log(f"mailjet: failed for {recipient_email}: {detail}")
                    return False

        append_notification_log(f"mailjet: sent to {recipient_email}")
        return True
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        append_notification_log(f"mailjet: failed for {recipient_email}: {exc}")
        return False


def _send_telegram_bot_message(chat_id, body, parse_mode=None, message_thread_id=None, reply_markup=None):
    bot_token = str(_get_config("telegram_bot_token") or "").strip()
    chat_id = str(chat_id or "").strip()
    if not bot_token or not chat_id:
        return False

    payload = {"chat_id": chat_id, "text": body}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    thread_id = normalize_telegram_thread_id(message_thread_id)
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
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
        with urlopen(request, context=None, timeout=OUTBOUND_HTTP_TIMEOUT_SECONDS) as response:
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


def send_telegram_command_response(chat_id, body, image_key=None, message_thread_id=None):
    """Send a configurable command response and return its Telegram message ID."""
    chat_id = str(chat_id or '').strip()
    if not chat_id:
        return None

    if image_key:
        from .storage import generate_result_image_presigned_url

        media_url = generate_result_image_presigned_url(image_key)
        # Animated GIFs are stored as MP4 loops and must be sent via sendAnimation.
        if str(image_key).lower().endswith('.mp4'):
            payload = {'chat_id': chat_id, 'animation': media_url, 'caption': str(body or '')[:1024]}
            method_name = 'sendAnimation'
        else:
            payload = {'chat_id': chat_id, 'photo': media_url, 'caption': str(body or '')[:1024]}
            method_name = 'sendPhoto'
    else:
        payload = {'chat_id': chat_id, 'text': str(body or '')}
        method_name = 'sendMessage'
    thread_id = normalize_telegram_thread_id(message_thread_id)
    if thread_id is not None:
        payload['message_thread_id'] = thread_id

    ok, response = _telegram_api_post(method_name, payload)
    if not ok:
        return None
    result = response.get('result') if isinstance(response, dict) else None
    return str(result.get('message_id')) if isinstance(result, dict) and result.get('message_id') is not None else None


def download_telegram_photo(file_id, max_bytes=None):
    """Download a Telegram file into a storage-compatible, optionally bounded stream."""
    bot_token = str(_get_config('telegram_bot_token') or '').strip()
    if not bot_token or not file_id:
        return None
    ok, response = _telegram_api_post('getFile', {'file_id': str(file_id)})
    result = (response.get('result') or {}) if ok and isinstance(response, dict) else {}
    file_path = result.get('file_path')
    if not file_path:
        return None
    if max_bytes and int(result.get('file_size') or 0) > max_bytes:
        return None
    url = f'https://api.telegram.org/file/bot{quote(bot_token, safe="")}/{file_path}'
    try:
        with urlopen(url, timeout=OUTBOUND_HTTP_TIMEOUT_SECONDS) as remote_file:
            payload = remote_file.read((max_bytes + 1) if max_bytes else -1)
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None
    if max_bytes and len(payload) > max_bytes:
        return None
    upload = io.BytesIO(payload)
    upload.filename = file_path.rsplit('/', 1)[-1] or 'telegram-command-image.jpg'
    return upload


def _discord_api_post(method_name, payload):
    bot_token = str(_get_config("discord_bot_token") or "").strip()
    if not bot_token:
        return False, {"description": "Discord bot token is not configured."}

    safe_token = quote(bot_token, safe="")
    url = f"https://discord.com/api/v10/{method_name.lstrip('/')}"
    debug_url = url.replace(bot_token, safe_token)
    max_rate_limit_retries = int(current_app.config.get("DISCORD_RATE_LIMIT_RETRIES", 1))
    max_retry_wait_seconds = float(current_app.config.get("DISCORD_RATE_LIMIT_MAX_WAIT_SECONDS", 2.0))
    attempt = 0

    while True:
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bot {bot_token}",
            },
            method="POST",
        )

        try:
            with urlopen(request, context=None, timeout=OUTBOUND_HTTP_TIMEOUT_SECONDS) as response:
                response_body = response.read().decode("utf-8", errors="replace")
            try:
                parsed_response = json.loads(response_body) if response_body else {}
            except ValueError:
                parsed_response = {}

            if isinstance(parsed_response, dict):
                append_notification_log(
                    f"discord: response for {method_name}: {json.dumps(parsed_response, ensure_ascii=False)}",
                    debug=True,
                )
            elif response_body:
                append_notification_log(f"discord: response for {method_name}: {response_body}", debug=True)

            status_code = getattr(response, "status", None)
            if status_code is None:
                try:
                    status_code = response.getcode()
                except Exception:
                    status_code = 200
            try:
                status_code_int = int(status_code or 0)
            except (TypeError, ValueError):
                status_code_int = 200
            ok = 200 <= status_code_int < 300
            return ok, parsed_response if isinstance(parsed_response, dict) else {"description": response_body}
        except HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = ""

            if int(getattr(exc, "code", 0) or 0) == 429 and attempt < max_rate_limit_retries:
                retry_after = None
                header_retry_after = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
                if header_retry_after:
                    try:
                        retry_after = float(header_retry_after)
                    except (TypeError, ValueError):
                        retry_after = None

                if retry_after is None and error_body:
                    try:
                        parsed_error = json.loads(error_body)
                    except ValueError:
                        parsed_error = {}
                    if isinstance(parsed_error, dict) and parsed_error.get("retry_after") is not None:
                        try:
                            retry_after = float(parsed_error.get("retry_after"))
                        except (TypeError, ValueError):
                            retry_after = None

                if retry_after is not None and retry_after <= max_retry_wait_seconds:
                    attempt += 1
                    append_notification_log(
                        f"discord: rate limited on {method_name}, retrying in {retry_after:.2f}s (attempt {attempt}/{max_rate_limit_retries})"
                    )
                    time.sleep(max(retry_after, 0.0))
                    continue

            detail = error_body or str(exc)
            append_notification_log(f"discord: failed for {method_name}: {detail}")
            append_notification_log(f"discord: request url={debug_url} detail={detail}", debug=True)
            return False, {"description": detail}
        except (URLError, TimeoutError, ValueError) as exc:
            detail = str(exc)
            append_notification_log(f"discord: failed for {method_name}: {detail}")
            append_notification_log(f"discord: request url={debug_url} detail={detail}", debug=True)
            return False, {"description": detail}


def _build_discord_message_payloads(body, limit=2000):
    # Discord Create Message limits content to 2000 characters.
    text = str(body or "")
    if not text.strip():
        return []

    payloads = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunk = remaining
            remaining = ""
        else:
            split_index = remaining.rfind("\n", 0, limit)
            if split_index < 1:
                split_index = limit
            chunk = remaining[:split_index]
            remaining = remaining[split_index:]
            if remaining.startswith("\n"):
                remaining = remaining[1:]

        payloads.append({
            "content": chunk,
            # Prevent accidental mentions from user-generated strings.
            "allowed_mentions": {"parse": []},
        })

    return payloads


def _send_discord_dm_message(discord_user_id, body):
    discord_user_id = str(discord_user_id or "").strip()
    if not discord_user_id:
        return False

    channel_ok, channel_response = _discord_api_post("users/@me/channels", {"recipient_id": discord_user_id})
    if not channel_ok:
        return False

    channel_id = str(channel_response.get("id") or "").strip()
    if not channel_id:
        return False

    payloads = _build_discord_message_payloads(body)
    if not payloads:
        return False

    for payload in payloads:
        message_ok, _ = _discord_api_post(f"channels/{channel_id}/messages", payload)
        if not message_ok:
            return False

    append_notification_log(f"discord: sent to user {discord_user_id}")
    return True


def send_telegram_message(user, body):
    append_notification_log(f"telegram: queued for {getattr(user, 'username', 'unknown')}")
    chat_id = str(_get_user_attr(user, "telegram_chat_id", None) or "").strip()
    fallback_username = str(_get_user_attr(user, "tg_username", None) or "").strip()
    if not chat_id and fallback_username:
        chat_id = fallback_username if fallback_username.startswith("@") else f"@{fallback_username}"
    if not chat_id:
        return False

    if not chat_id.startswith("@") and not re.fullmatch(r"-?\d+", chat_id):
        chat_id = f"@{chat_id}"

    return _send_telegram_bot_message(chat_id, body)


def send_discord_message(user, body):
    append_notification_log(f"discord: queued for {getattr(user, 'username', 'unknown')}")
    discord_user_id = str(_get_user_attr(user, "discord_user_id", None) or "").strip()
    if not discord_user_id:
        # The shared webhook posts to one org-wide channel, so using it as a
        # per-user fallback publishes this member's private body to everyone.
        return False
    return _send_discord_dm_message(discord_user_id, body)


def _parse_telegram_channel_target(raw_target):
    target_chat = str(raw_target or "").strip()
    if not target_chat:
        return "", None

    if "_" not in target_chat:
        return target_chat, None

    base_chat_id, suffix = target_chat.rsplit("_", 1)
    base_chat_id = base_chat_id.strip()
    suffix = suffix.strip()
    if not base_chat_id or not suffix.isdigit():
        return target_chat, None

    return base_chat_id, int(suffix)


def send_telegram_status_channel_message(body, parse_mode=None, buttons=None):
    configured_target = str(_get_config("telegram_status_chat_id") or "").strip()
    if not configured_target:
        return False
    target_chat, message_thread_id = _parse_telegram_channel_target(configured_target)
    append_notification_log(f"telegram: queued status channel message to {configured_target}")
    return _send_telegram_bot_message(
        target_chat,
        body,
        parse_mode=parse_mode,
        message_thread_id=message_thread_id,
        reply_markup={'inline_keyboard': [[
            {'text': str(button['label'])[:64], 'url': str(button['url'])}
            for button in (buttons or [])
            if button.get('label') and button.get('url')
        ]]} if buttons else None,
    )


def send_discord_status_channel_message(body, buttons=None):
    configured_channel_id = str(_get_config("discord_status_channel_id") or "").strip()
    if not configured_channel_id:
        return False

    append_notification_log(f"discord: queued status channel message to {configured_channel_id}")
    payloads = _build_discord_message_payloads(body)
    if not payloads:
        return False

    if buttons:
        components = [{
            'type': 1,
            'components': [
                {'type': 2, 'style': 5, 'label': str(button['label'])[:80], 'url': str(button['url'])}
                for button in buttons
                if button.get('label') and button.get('url')
            ],
        }]
        if components[0]['components']:
            payloads[-1]['components'] = components

    for payload in payloads:
        message_ok, _ = _discord_api_post(f"channels/{configured_channel_id}/messages", payload)
        if not message_ok:
            return False
    return True


def send_telegram_chat_message(chat_id, body, parse_mode=None, message_thread_id=None, reply_markup=None):
    return _send_telegram_bot_message(
        chat_id,
        body,
        parse_mode=parse_mode,
        message_thread_id=message_thread_id,
        reply_markup=reply_markup,
    )


def send_telegram_interactive_message(
        chat_id, body, message_thread_id=None, reply_markup=None, reply_to_message_id=None):
    payload = {'chat_id': str(chat_id or ''), 'text': str(body or '')[:4096]}
    thread_id = normalize_telegram_thread_id(message_thread_id)
    if thread_id is not None:
        payload['message_thread_id'] = thread_id
    if reply_markup is not None:
        payload['reply_markup'] = reply_markup
    if reply_to_message_id is not None:
        reply_id = normalize_telegram_thread_id(reply_to_message_id)
        if reply_id is not None:
            payload['reply_parameters'] = {'message_id': reply_id}
    ok, response = _telegram_api_post('sendMessage', payload)
    result = response.get('result') if ok and isinstance(response, dict) else None
    return str(result.get('message_id')) if isinstance(result, dict) and result.get('message_id') is not None else None


def normalize_telegram_thread_id(value):
    """Return a valid Telegram thread ID, or None for an unset/invalid value."""
    if value is None or str(value).strip().lower() in {'', 'none', 'null'}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def answer_telegram_callback_query(callback_query_id, text=None, show_alert=False):
    payload = {'callback_query_id': str(callback_query_id or '')}
    if text:
        payload['text'] = str(text)[:200]
        payload['show_alert'] = bool(show_alert)
    ok, _ = _telegram_api_post('answerCallbackQuery', payload)
    return ok


def delete_telegram_message(chat_id, message_id):
    message_id = normalize_telegram_thread_id(message_id)
    if message_id is None:
        return False
    ok, _ = _telegram_api_post('deleteMessage', {
        'chat_id': str(chat_id or ''),
        'message_id': message_id,
    })
    return ok


def edit_telegram_message(chat_id, message_id, body, reply_markup=None):
    message_id = normalize_telegram_thread_id(message_id)
    if message_id is None:
        return False
    payload = {
        'chat_id': str(chat_id or ''),
        'message_id': message_id,
        'text': body,
    }
    if reply_markup is not None:
        payload['reply_markup'] = reply_markup
    ok, response = _telegram_api_post('editMessageText', payload)
    if not ok:
        detail = response.get('description', 'unknown Telegram API error') if isinstance(response, dict) else 'unknown Telegram API error'
        detail = str(detail).replace('\r', ' ').replace('\n', ' ')[:500]
        append_notification_log(
            f'telegram: editMessageText failed chat={chat_id} message={message_id}: {detail}',
        )
    return ok


def _queue_bot_webhook_message(provider_name, webhook_url, payload):
    webhook_url = str(webhook_url or "").strip()
    if not webhook_url:
        return False

    delivered, response_body = post_json(webhook_url, payload, timeout=10)
    if delivered:
        append_notification_log(f"{provider_name}: delivered webhook message")
        return True

    append_notification_log(
        f"{provider_name}: webhook delivery failed: {response_body}",
    )
    return False


def _send_discord_webhook_message(body):
    webhook_url = _get_config("discord_webhook_url")
    username = str(_get_config("discord_webhook_username") or "Group Test Manager").strip() or "Group Test Manager"
    payloads = [
        {**payload, "username": username}
        for payload in _build_discord_message_payloads(body)
    ]

    for payload in payloads:
        if not _queue_bot_webhook_message("discord", webhook_url, payload):
            return False

    return bool(payloads)


def root_plain_text(body):
    """Reduce a rendered notification body to text Root can actually display.

    Root renders no markup, and ``select_template_body`` can hand a chat channel the
    HTML email body when its own body is unset. Tag stripping keeps the anchor text
    (so a ``tg://`` mention degrades to the member's name) and drops the target.
    """
    from html import unescape

    text = re.sub(r"<[^>]+>", "", str(body or ""))
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def send_root_message(body):
    """Queue a message for delivery into Root.

    Root accepts no pushes at all, so "sending" here means handing the body to the
    pull-based outbox that the Root-hosted bridge drains. True means the message was
    accepted for delivery, not that it landed in a channel.
    """
    channel_id = bridge_status_channel_id()
    text = root_plain_text(body)
    if not channel_id or not text:
        append_notification_log(
            "root: message not queued ({})".format("no status channel configured" if not channel_id else "empty body")
        )
        return False

    try:
        db.session.add(RootOutbox(channel_id=channel_id, body=text))
        db.session.commit()
    except SQLAlchemyError as exc:
        # Every other adapter turns transport failure into False so
        # send_notification_message can fall back to email; a raise here would
        # 500 the caller mid-loop instead, with the notification unsent.
        db.session.rollback()
        append_notification_log(f"root: could not queue outbox message: {exc}")
        return False

    append_notification_log(f"root: queued outbox message for {channel_id}")
    return True


def send_root_status_channel_message(body, buttons=None):
    """Queue a status-channel broadcast for delivery into Root.

    Root renders plain text only — no in-message buttons or interactive components —
    so ``buttons`` degrades to text: every button carrying both a label and a url is
    appended as a visible absolute link, which the Root client auto-links. A button
    missing either part cannot be rendered at all, so it is skipped and logged rather
    than passed on half-formed.

    Delivery is the same pull-based outbox handoff as ``send_root_message``, so True
    means the message was accepted for delivery, not that it landed in a channel.
    """
    text = str(body or "").strip()
    if not text:
        append_notification_log("root: status channel message not queued (empty body)")
        return False

    link_lines = []
    skipped = 0
    for button in (buttons or []):
        label = str(button.get("label") or "").strip() if isinstance(button, dict) else ""
        url = str(button.get("url") or "").strip() if isinstance(button, dict) else ""
        if not label or not url:
            skipped += 1
            continue
        link_lines.append(f"{label}: {url}")

    if skipped:
        append_notification_log(
            f"root: skipped {skipped} status channel button(s) without a label or url"
        )
    if link_lines:
        text = "\n".join([text, ""] + link_lines)

    return send_root_message(text)


# Uniform transport seam: every adapter accepts (user, subject, body) and returns a
# truthy delivery result. Chat providers have no message subject, so they accept and
# ignore it rather than forcing callers to special-case by channel.
def _deliver_email(user, subject, body):
    return send_mailjet_message(user, subject, body)


def _deliver_telegram(user, subject, body):
    return send_telegram_message(user, body)


def _deliver_discord(user, subject, body):
    return send_discord_message(user, body)


def _deliver_root(user, subject, body):
    # Root cannot address a message to one person: everything lands in a channel the
    # whole community reads. Personal content (a new password, an amount owed) must
    # never be broadcast, so this adapter refuses and the caller falls back to email
    # even for a stored channel value predating that rule.
    append_notification_log(
        f"root: {getattr(user, 'username', 'unknown')} asked for a personal channel Root cannot provide; "
        "using email"
    )
    return False


_CHANNEL_SENDERS = {
    "email": _deliver_email,
    "telegram": _deliver_telegram,
    "discord": _deliver_discord,
    "root": _deliver_root,
}


def _telegram_api_post(method_name, payload):
    bot_token = str(_get_config("telegram_bot_token") or "").strip()
    if not bot_token:
        append_notification_log(f'telegram: {method_name} failed: bot token is not configured')
        return False, {"description": "Telegram bot token is not configured."}

    safe_token = quote(bot_token, safe="")
    url = f"https://api.telegram.org/bot{safe_token}/{method_name}"
    request_payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=request_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, context=None, timeout=OUTBOUND_HTTP_TIMEOUT_SECONDS) as response:
            response_body = response.read().decode("utf-8", errors="replace")
        parsed_response = json.loads(response_body) if response_body else {}
        ok = isinstance(parsed_response, dict) and parsed_response.get("ok") is True
        if not ok:
            detail = parsed_response.get('description') if isinstance(parsed_response, dict) else response_body
            detail = str(detail or 'empty response').replace('\r', ' ').replace('\n', ' ')[:500]
            append_notification_log(f'telegram: {method_name} failed: {detail}')
        return ok, parsed_response if isinstance(parsed_response, dict) else {"description": response_body}
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        detail = str(exc)
        if isinstance(exc, HTTPError):
            try:
                detail = exc.read().decode("utf-8", errors="replace") or str(exc)
            except Exception:
                detail = str(exc)
        detail = str(detail).replace('\r', ' ').replace('\n', ' ')[:500]
        append_notification_log(f'telegram: {method_name} request failed: {detail}')
        return False, {"description": detail}


def register_telegram_webhook(webhook_url, secret_token=None, drop_pending_updates=False):
    payload = {
        "url": str(webhook_url or "").strip(),
        "drop_pending_updates": bool(drop_pending_updates),
    }
    secret_value = str(secret_token or "").strip()
    if secret_value:
        payload["secret_token"] = secret_value
    return _telegram_api_post("setWebhook", payload)


def unregister_telegram_webhook(drop_pending_updates=False):
    payload = {"drop_pending_updates": bool(drop_pending_updates)}
    return _telegram_api_post("deleteWebhook", payload)


def send_password_reset(user, new_password):
    template = NotificationTemplate.query.filter_by(is_default_password_reset=True, is_active=True).first()
    channel = user.notification_channel or "email"
    if template is None:
        body = f"Your new password is: {new_password}"
        subject = "Password Reset"
    else:
        bodies = template_bodies(template)
        template_body = select_template_body(bodies, channel)
        body = render_notification_template(
            template_body or "",
            {"new_password": new_password, "username": user.username},
        )
        subject = template.email_subject or "Password Reset"

    return send_notification_message(user, channel, subject, body)


def send_group_test_notification(test, user, template, amount_owed=None):
    base_url = managed_public_url() or str(_get_config("service_base_url") or "").strip()
    if not base_url:
        base_url = current_app.config.get("SERVER_NAME") or "http://localhost"
    if not base_url.startswith(("http://", "https://")):
        base_url = f"https://{base_url}"

    context = {
        "username": user.username,
        "amount_owed": f"{amount_owed:.2f}" if amount_owed is not None else "",
        "test_title": test.title,
        "test_link": f"{base_url}/test/{test.id}",
        "test_id": str(test.id),
    }
    email_subject = render_notification_template(template.email_subject or "", context)
    bodies = template_bodies(template, context)

    channel = user.notification_channel or "email"
    return send_notification_message(user, channel, email_subject, select_template_body(bodies, channel))


def _digest_slot_for_user(user, now):
    frequency = str(getattr(user, "digest_frequency", "off") or "off").strip().lower()
    if frequency not in {"hourly", "daily"}:
        return None

    if frequency == "hourly":
        minute = int(getattr(user, "digest_hourly_minute_utc", 0) or 0)
        minute = max(0, min(59, minute))
        slot = now.replace(minute=minute, second=0, microsecond=0)
        if now < slot:
            slot = slot - timedelta(hours=1)
        return slot

    hour = int(getattr(user, "digest_daily_hour_utc", 9) or 9)
    hour = max(0, min(23, hour))
    slot = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if now < slot:
        slot = slot - timedelta(days=1)
    return slot


def _is_user_digest_due(user, now):
    slot = _digest_slot_for_user(user, now)
    if slot is None:
        return False

    last_sent = getattr(user, "digest_last_sent_at", None)
    if last_sent is None:
        return True
    return last_sent < slot


def _render_user_digest_email(user, events):
    lines = [
        f"Hello {user.username},",
        "",
        "Here is your Group Test status digest:",
        "",
    ]
    for event in events:
        old_status = str(event.old_status or '').replace('_', ' ').title()
        new_status = str(event.new_status or '').replace('_', ' ').title()
        lines.append(f"- #{event.test_id} {event.test_title}: {old_status} -> {new_status}")
    lines.extend([
        "",
        "You can review details by logging into Group Test Tracker.",
    ])
    return "\n".join(lines)


def send_due_user_digests(now=None):
    now = now or datetime.utcnow()
    users = User.query.filter(
        User.is_active == True,
        User.receive_group_test_notifications == True,
        User.digest_frequency.in_(["hourly", "daily"]),
    ).all()

    sent_count = 0
    user_count = 0
    for user in users:
        try:
            if not _is_user_digest_due(user, now):
                continue

            due_events = (
                UserDigestEvent.query
                .filter_by(user_id=user.id, sent_at=None)
                .order_by(UserDigestEvent.created_at.asc(), UserDigestEvent.id.asc())
                .all()
            )
            if not due_events:
                user.digest_last_sent_at = now
                db.session.add(user)
                db.session.commit()
                continue

            subject = f"Group Test Digest ({len(due_events)} update{'s' if len(due_events) != 1 else ''})"
            body = _render_user_digest_email(user, due_events)
            sent = send_mailjet_message(user, subject, body)
            if not sent:
                append_notification_log(f"digest: failed for {getattr(user, 'username', 'unknown')}")
                continue

            sent_at = datetime.utcnow()
            for event in due_events:
                event.sent_at = sent_at
            user.digest_last_sent_at = now
            db.session.add(user)
            db.session.add_all(due_events)
            # Commit per user: one delivery receipt per user must survive a later
            # user's failure, otherwise the whole run rewinds and re-notifies everyone.
            db.session.commit()
            sent_count += len(due_events)
            user_count += 1
        except Exception:
            db.session.rollback()
            append_notification_log(f"digest: error for {getattr(user, 'username', 'unknown')}")

    append_notification_log(f"digest: completed users={user_count} events={sent_count}")
    return {"users": user_count, "events": sent_count}
