"""Topic-scoped moderation, album checks, and bounded deletion retries."""
import io
from datetime import datetime, timedelta

from PIL import Image, UnidentifiedImageError
from sqlalchemy import update

from . import db
from .models import BSTTopic, BSTVendor, BSTMessage, BSTEvent
from .bst_service import options, eligible, topic_link
from .notifications import (
    _get_config, delete_telegram_message, download_telegram_photo,
    send_telegram_interactive_message, append_notification_log,
)

OTHER_MEDIA = {'video', 'animation', 'audio', 'voice', 'video_note', 'sticker', 'contact', 'location',
               'venue', 'poll', 'dice', 'game', 'invoice', 'paid_media', 'story', 'checklist', 'live_photo', 'widget'}
SERVICE_FIELDS = {'new_chat_members', 'left_chat_member', 'new_chat_title', 'new_chat_photo', 'delete_chat_photo',
                  'group_chat_created', 'supergroup_chat_created', 'channel_chat_created', 'message_auto_delete_timer_changed',
                  'migrate_to_chat_id', 'migrate_from_chat_id', 'pinned_message', 'forum_topic_created',
                  'forum_topic_edited', 'forum_topic_closed', 'forum_topic_reopened', 'general_forum_topic_hidden',
                  'general_forum_topic_unhidden', 'video_chat_scheduled', 'video_chat_started', 'video_chat_ended',
                  'video_chat_participants_invited', 'proximity_alert_triggered', 'write_access_allowed', 'users_shared', 'chat_shared'}


def image_document(document):
    if not document.get('file_id') or not str(document.get('mime_type', '')).startswith('image/'):
        return False
    upload = download_telegram_photo(document['file_id'], max_bytes=8 * 1024 * 1024)
    if upload is None:
        return False
    try:
        with Image.open(io.BytesIO(upload.read())) as image:
            if image.width * image.height > 40000000:
                return False
            image.verify()
        return True
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        return False


def content(topic, message):
    rules = options(topic)
    caption = str(message.get('caption') or '').strip()
    text = str(message.get('text') or '').strip()
    entities = (message.get('entities') or []) + (message.get('caption_entities') or [])
    import re
    links = any(entity.get('type') in {'url', 'text_link', 'email'} for entity in entities) or bool(
        re.search(r'(?:https?://|tg://|www\.|t\.me/|\b[a-z0-9-]+\.(?:com|org|net|io|co|me|xyz|app)\b)', text + ' ' + caption, re.I))
    reason = None
    has_image = bool(message.get('photo'))
    if message.get('document'):
        has_image = rules['allow_documents'] and image_document(message['document'])
        if not has_image:
            reason = 'Only permitted image files are allowed; this file could not be validated.'
    if OTHER_MEDIA.intersection(message):
        reason = 'This media type is not permitted in this BST topic.'
    if message.get('photo') and not rules['allow_photos']:
        reason = 'Photos are not permitted in this BST topic.'
    if not has_image and (not text or not rules['allow_text'] or rules['require_image']):
        reason = reason or 'This topic requires an allowed image listing; text-only messages are not permitted.'
    if caption and not rules['allow_captions']:
        reason = 'Captions are not permitted in this BST topic.'
    if links and not rules['allow_links']:
        reason = 'Links are not permitted in this BST topic.'
    if (message.get('forward_origin') or message.get('forward_from') or message.get('forward_from_chat')) and not rules['allow_forwards']:
        reason = 'Forwarded listings are not permitted in this BST topic.'
    if message.get('media_group_id') and not rules['allow_albums']:
        reason = 'Photo albums are not permitted in this BST topic.'
    return {'caption': bool(caption), 'image': has_image, 'reason': reason}


def remember(topic, message_id, uid, action, payload=None, album=None, due=None):
    row = BSTMessage.query.filter_by(topic_id=topic.id, message_id=str(message_id)).first()
    if row is None:
        row = BSTMessage(topic_id=topic.id, message_id=str(message_id), telegram_user_id=str(uid))
        db.session.add(row)
    row.action = action
    row.payload = payload or {}
    row.album_id = str(album) if album else None
    row.due_at = due or datetime.utcnow()
    db.session.commit()
    return row


def reminder(topic, uid, reason):
    now = datetime.utcnow()
    recent = BSTEvent.query.filter(BSTEvent.topic_id == topic.id, BSTEvent.action == 'reminder',
                                   BSTEvent.actor_telegram_id == str(uid), BSTEvent.created_at > now - timedelta(minutes=5)).first()
    if recent:
        return
    db.session.add(BSTEvent(topic_id=topic.id, action='reminder', actor_telegram_id=str(uid), details={'reason': reason}))
    db.session.commit()
    link = topic_link(topic)
    keyboard = {'inline_keyboard': [[{'text': 'Apply to Sell / My Application', 'url': link}]]} if link else None
    body = f'Your message in {topic.name} was removed. {reason}\nOnly approved vendors may post listings. Open /bst in the bot to apply or check your status.'
    sent = send_telegram_interactive_message(uid, body, reply_markup=keyboard) if uid and str(uid).isdigit() and int(uid) > 0 else None
    if sent is None:
        sent = send_telegram_interactive_message(topic.chat_id, 'BST listing removed. ' + reason + '\nApply to become an approved BST vendor using the button below.',
                                                message_thread_id=topic.thread_id, reply_markup=keyboard)
        if sent:
            remember(topic, sent, uid, 'reminder', due=now + timedelta(seconds=60))


def remove(topic, message_id, uid, reason, retry=None):
    if delete_telegram_message(topic.chat_id, message_id):
        if retry:
            db.session.delete(retry)
            db.session.commit()
        reminder(topic, uid, reason)
        return
    append_notification_log(f'bst: deletion failed topic={topic.id} message={message_id}; check bot permissions')
    if retry is None:
        remember(topic, message_id, uid, 'delete', {'reason': reason}, due=datetime.utcnow() + timedelta(seconds=30))


def moderate(message):
    chat = message.get('chat') or {}
    topic = BSTTopic.query.filter_by(chat_id=str(chat.get('id')), thread_id=message.get('message_thread_id'), enabled=True).first()
    if topic is None:
        return False
    sender = message.get('from') or {}
    own_username = str(_get_config('telegram_bot_username') or '').lstrip('@').lower()
    if (own_username and sender.get('is_bot') and str(sender.get('username') or '').lower() == own_username) or SERVICE_FIELDS.intersection(message):
        return True
    # Temporary notices sent by this bot are recorded even when its configured
    # username is missing. Never moderate our own recorded notices.
    if BSTMessage.query.filter_by(topic_id=topic.id, message_id=str(message.get('message_id')), action='reminder').first():
        return True
    uid = str(sender.get('id') or '') if not message.get('sender_chat') else ''
    vendor = BSTVendor.query.filter_by(topic_id=topic.id, telegram_user_id=uid).first() if not message.get('sender_chat') else None
    if not eligible(vendor):
        remove(topic, message.get('message_id'), uid, 'You must apply and be approved for this topic before posting. If email verification is required, complete it in /bst.')
        return True
    info = content(topic, message)
    album = message.get('media_group_id')
    if album and options(topic)['allow_albums'] and options(topic)['require_caption']:
        remember(topic, message['message_id'], uid, 'album', info, album, datetime.utcnow() + timedelta(seconds=3))
        BSTMessage.query.filter_by(topic_id=topic.id, telegram_user_id=uid, album_id=str(album)).update(
            {'action': 'album', 'due_at': datetime.utcnow() + timedelta(seconds=3)}, synchronize_session=False)
        db.session.commit()
        return True
    reason = info['reason']
    if info['image'] and options(topic)['require_caption'] and not info['caption']:
        reason = reason or 'Image listings require a caption.'
    if reason:
        remove(topic, message.get('message_id'), uid, reason)
    return True


def maintain_messages():
    now = datetime.utcnow()
    rows = BSTMessage.query.filter(BSTMessage.due_at <= now).order_by(BSTMessage.due_at).limit(100).all()
    processed_albums = set()
    for row in rows:
        if row not in db.session or row.due_at > now:
            continue
        if row.album_id and (row.topic_id, row.telegram_user_id, row.album_id) in processed_albums:
            continue
        topic = db.session.get(BSTTopic, row.topic_id)
        if row.action == 'album_ok' or (not topic.enabled and row.action != 'reminder'):
            db.session.delete(row)
            continue
        if row.action == 'album':
            key = (row.topic_id, row.telegram_user_id, row.album_id)
            if key in processed_albums:
                continue
            processed_albums.add(key)
            album = BSTMessage.query.filter_by(topic_id=row.topic_id, telegram_user_id=row.telegram_user_id, album_id=row.album_id).all()
            if any(item.due_at > now for item in album):
                continue
            vendor = BSTVendor.query.filter_by(topic_id=topic.id, telegram_user_id=row.telegram_user_id).first()
            reason = next((item.payload.get('reason') for item in album if item.payload.get('reason')), None)
            if not eligible(vendor):
                reason = 'Vendor approval is required for this topic.'
            if options(topic)['require_caption'] and not any(item.payload.get('caption') for item in album):
                reason = 'Photo albums require at least one caption.'
            for item in album:
                if reason:
                    item.action = 'delete'
                    item.payload = {'reason': reason}
                    item.due_at = now
                else:
                    item.action = 'album_ok'
                    item.due_at = now + timedelta(days=1)
            db.session.commit()
            # Deletions are processed on the next poll; no additional process.
            continue
        claimed = db.session.execute(update(BSTMessage).where(BSTMessage.id == row.id, BSTMessage.due_at <= now).values(
            due_at=now + timedelta(minutes=2), attempts=BSTMessage.attempts + 1))
        db.session.commit()
        if not claimed.rowcount:
            continue
        db.session.refresh(row)
        if row.action == 'reminder':
            sent = delete_telegram_message(topic.chat_id, row.message_id)
            if sent or row.attempts >= 5:
                db.session.delete(row)
        else:
            remove(topic, row.message_id, row.telegram_user_id, row.payload.get('reason', 'This listing is not permitted.'), row)
            if row in db.session and row.attempts >= 5:
                append_notification_log(f'bst: deletion abandoned topic={topic.id} message={row.message_id}')
                db.session.delete(row)
        if row in db.session:
            row.due_at = now + timedelta(seconds=30)
        db.session.commit()
    db.session.commit()
