"""BST identity, permissions, application transitions, and delivery.

Telegram vendors and group administrators do not need GTM accounts. All web and
bot actions share these transitions, including optimistic revision checks.
"""
import hashlib
import html
import secrets
from datetime import datetime, timedelta
from types import SimpleNamespace

from email_validator import validate_email, EmailNotValidError
from flask import current_app
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from . import db
from .models import BSTTopic, BSTVendor, BSTEvent, BSTNotice, BSTConversation, User
from .notifications import (
    _telegram_api_post, _get_config, append_notification_log,
    send_telegram_chat_message, send_notification_message, send_mailjet_message,
)
from .saas import managed_public_url

FIELDS = {
    'vendor_name': 'Vendor name', 'email': 'Email', 'guarantees': 'Vendor guarantees',
    'dispute_contact': 'Dispute resolution contact', 'dispute_process': 'Dispute resolution process',
}
OPTIONS = {
    'allow_text': ('Allow text-only listings', True),
    'allow_photos': ('Allow photos', True),
    'allow_documents': ('Allow image files', False),
    'allow_captions': ('Allow captions', True),
    'allow_albums': ('Allow photo albums', True),
    'allow_links': ('Allow links', False),
    'require_image': ('Require an image', False),
    'require_caption': ('Require captions on images', False),
    'allow_forwards': ('Allow forwarded listings', False),
    'verify_email': ('Require verified vendor email', False),
}


class BSTError(ValueError):
    pass


def options(topic):
    return {key: bool((topic.options or {}).get(key, default)) for key, (_, default) in OPTIONS.items()}


def validate_options(values):
    values = {key: bool(values.get(key, default)) for key, (_, default) in OPTIONS.items()}
    images = values['allow_photos'] or values['allow_documents']
    if values['require_image'] and not images:
        raise BSTError('Requiring an image needs photos or image files enabled.')
    if values['require_caption'] and (not images or not values['allow_captions']):
        raise BSTError('Requiring captions needs an image format and captions enabled.')
    if values['allow_albums'] and not values['allow_photos']:
        raise BSTError('Photo albums need photos enabled.')
    if not values['allow_text'] and not images:
        raise BSTError('Allow at least one listing format.')
    return values


def telegram_id(value):
    raw = str(value or '').strip()
    if not raw.isdigit() or int(raw) <= 0 or len(raw) > 20:
        raise BSTError('Enter a positive numeric Telegram user ID, not a username.')
    return str(int(raw))


def validate_answer(field, value):
    value = str(value or '').strip()
    limit = 160 if field == 'vendor_name' else 254 if field == 'email' else 3000
    if field not in FIELDS or not value or len(value) > limit:
        raise BSTError(f'{FIELDS.get(field, "Answer")} is required (maximum {limit} characters).')
    if field == 'email':
        try:
            value = validate_email(value, check_deliverability=False).normalized
        except EmailNotValidError:
            raise BSTError('Enter a valid email address.') from None
    return value


def profile(values):
    return {field: validate_answer(field, values.get(field)) for field in FIELDS}


def linked_admin(uid):
    return User.query.filter_by(telegram_user_id=str(uid), is_admin=True, is_active=True).first()


def can_manage(uid, chat_id, web_user=None):
    if web_user is not None and web_user.is_authenticated and web_user.is_active and web_user.is_admin:
        return True
    if not uid:
        return False
    if linked_admin(uid):
        return True
    ok, response = _telegram_api_post('getChatMember', {'chat_id': str(chat_id), 'user_id': int(uid)})
    member = response.get('result') if ok else None
    return isinstance(member, dict) and member.get('status') in {'creator', 'administrator'}


def require_manager(topic, uid=None, web_user=None):
    if not can_manage(uid, topic.chat_id, web_user):
        raise BSTError('Only current group admins or linked GTM admins can manage this topic.')


def check_bot_permissions(chat_id):
    ok, response = _telegram_api_post('getMe', {})
    me = response.get('result') if ok else None
    if not isinstance(me, dict) or not me.get('id'):
        raise BSTError('Unable to verify the bot identity. Check Telegram configuration.')
    ok, response = _telegram_api_post('getChatMember', {'chat_id': str(chat_id), 'user_id': me['id']})
    member = response.get('result') if ok else None
    if not isinstance(member, dict) or member.get('status') not in {'creator', 'administrator'} or not member.get('can_delete_messages'):
        raise BSTError('The bot must be a group administrator with Delete Messages permission before enabling BST.')


def event(topic, action, vendor=None, uid=None, web_user=None, details=None):
    actor = web_user if web_user is not None else linked_admin(uid) if uid else None
    item = BSTEvent(topic_id=topic.id, vendor_id=vendor.id if vendor else None, action=action,
                    actor_telegram_id=str(uid) if uid else None, actor_gtm_id=actor.id if actor else None,
                    details=details or {})
    db.session.add(item)
    db.session.flush()
    return item


def topic_link(topic, admin=False):
    username = str(_get_config('telegram_bot_username') or '').strip().lstrip('@')
    return f'https://t.me/{username}?start={"bsa" if admin else "bst"}_{topic.code}' if username else None


def save_topic(chat_id, thread_id, name, values, enabled, topic=None, version=None, uid=None, web_user=None):
    chat_id = str(chat_id or '').strip()
    if not chat_id.startswith('-') or not chat_id[1:].isdigit():
        raise BSTError('Use the numeric Telegram group Chat ID (starting with -).')
    try:
        thread_id = int(thread_id)
    except (TypeError, ValueError):
        raise BSTError('Topic ID must be a positive integer.') from None
    if thread_id <= 0:
        raise BSTError('Topic ID must be a positive integer.')
    if not can_manage(uid, chat_id, web_user):
        raise BSTError('You must administer the selected group.')
    values = validate_options(values)
    if not str(name or '').strip() or len(str(name)) > 160:
        raise BSTError('Enter a topic label (maximum 160 characters).')
    if enabled:
        if not str(_get_config('telegram_bot_username') or '').strip().lstrip('@'):
            raise BSTError('Configure the Telegram bot username in GTM before enabling BST application links.')
        check_bot_permissions(chat_id)
    if topic is None:
        if BSTTopic.query.filter_by(chat_id=chat_id, thread_id=thread_id).first():
            raise BSTError('That group/topic is already configured. Open its existing settings.')
        topic = BSTTopic(chat_id=chat_id, thread_id=thread_id, name=name.strip(), code=secrets.token_urlsafe(18),
                         options=values, enabled=enabled)
        db.session.add(topic)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            raise BSTError('That group/topic was just configured by another admin. Reopen its settings.') from None
    else:
        if (topic.chat_id, topic.thread_id) != (chat_id, thread_id):
            raise BSTError('Create a new policy to configure a different group/topic.')
        changed = db.session.execute(update(BSTTopic).where(BSTTopic.id == topic.id, BSTTopic.version == version).values(
            name=name.strip(), options=values, enabled=enabled, version=BSTTopic.version + 1))
        if not changed.rowcount:
            raise BSTError('Topic settings changed. Reload before saving.')
        db.session.refresh(topic)
    event(topic, 'configure', uid=uid, web_user=web_user, details={'enabled': enabled, 'options': values})
    db.session.commit()
    return topic


def get_vendor(topic, uid, username=None):
    uid = telegram_id(uid)
    vendor = BSTVendor.query.filter_by(topic_id=topic.id, telegram_user_id=uid).first()
    if vendor is None:
        vendor = BSTVendor(topic_id=topic.id, telegram_user_id=uid, username=username)
        db.session.add(vendor)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            vendor = BSTVendor.query.filter_by(topic_id=topic.id, telegram_user_id=uid).one()
    return vendor


def change_vendor(vendor, version, **values):
    changed = db.session.execute(update(BSTVendor).where(BSTVendor.id == vendor.id, BSTVendor.version == version).values(
        **values, version=BSTVendor.version + 1))
    if not changed.rowcount:
        raise BSTError('This application changed or was already reviewed. Reopen it before continuing.')
    db.session.refresh(vendor)


def save_answer(vendor, field, value, version):
    if vendor.status == 'revoked':
        raise BSTError('Approval was revoked. An admin must restore it before you can reapply.')
    draft = dict(vendor.draft or {})
    draft[field] = validate_answer(field, value)
    change_vendor(vendor, version, draft=draft, status='draft', verification={} if field == 'email' else vendor.verification)
    db.session.commit()


def notices(item, vendor, admins=False, text=''):
    subject = f'BST: {vendor.draft.get("vendor_name") or vendor.telegram_user_id}'[:160]
    if admins:
        base = managed_public_url() or str(_get_config('service_base_url') or '').strip().rstrip('/')
        body = f'{text}\nTopic: {vendor.topic.name}\nReview in GTM: {base}/admin/bst/vendors/{vendor.id}\nOr open /bstadmin in Telegram.'
        # Group admins who have linked a regular GTM profile can use their
        # configured notification channel too; no GTM admin promotion is needed.
        ok, response = _telegram_api_post('getChatAdministrators', {'chat_id': vendor.topic.chat_id})
        members = response.get('result') if ok else None
        group_admin_ids = {str(member.get('user', {}).get('id')) for member in members
                           if isinstance(member, dict) and not member.get('user', {}).get('is_bot')} if isinstance(members, list) else set()
        from sqlalchemy import or_
        recipients = User.query.filter(User.is_active.is_(True), User.telegram_user_id.isnot(None),
                                       or_(User.is_admin.is_(True), User.telegram_user_id.in_(group_admin_ids))).all()
        for admin in recipients:
            if admin.telegram_user_id:
                db.session.add(BSTNotice(event_id=item.id, recipient=f'gtm:{admin.id}', subject=subject, body=body))
    else:
        db.session.add(BSTNotice(event_id=item.id, recipient=f'tg:{vendor.telegram_user_id}', subject=subject,
                                body=f'{vendor.topic.name}: {text}\nOpen /bst to view your application.'))


def submit(vendor, version):
    if not vendor.topic.enabled:
        raise BSTError('This BST topic is currently disabled.')
    if vendor.status == 'revoked':
        raise BSTError('Only an admin can restore revoked approval.')
    if vendor.status == 'pending':
        raise BSTError('This application is already awaiting review.')
    draft = profile(vendor.draft)
    if options(vendor.topic)['verify_email'] and vendor.verified_email != draft['email']:
        raise BSTError('Verify your email before submitting this application.')
    change_vendor(vendor, version, draft=draft, status='pending', submitted_at=datetime.utcnow(), reason=None)
    item = event(vendor.topic, 'submit', vendor, uid=vendor.telegram_user_id, details={'revision': vendor.version, 'profile': draft})
    notices(item, vendor, admins=True, text=f'A BST application requires review: {draft["vendor_name"]}.')
    db.session.commit()


def decide(vendor, action, version, reason='', uid=None, web_user=None):
    require_manager(vendor.topic, uid, web_user)
    reason = str(reason or '').strip()
    if action not in {'approve', 'deny', 'changes', 'revoke', 'restore'}:
        raise BSTError('Unknown decision.')
    if action != 'approve' and (not reason or len(reason) > 2000):
        raise BSTError('Provide an applicant-visible reason (maximum 2000 characters).')
    values = {'reason': reason}
    if action in {'approve', 'deny', 'changes'} and vendor.status != 'pending':
        raise BSTError('This application is no longer awaiting review.')
    if action == 'approve':
        data = profile(vendor.draft)
        verified = vendor.verified_email == data['email']
        if options(vendor.topic)['verify_email'] and not verified:
            raise BSTError('The applicant must verify this email before approval.')
        data['email_verified'] = verified
        values.update(status='approved', is_approved=True, approved=data)
    elif action == 'deny':
        values['status'] = 'denied'
    elif action == 'changes':
        values['status'] = 'changes'
    elif action == 'revoke':
        if not vendor.is_approved:
            raise BSTError('This vendor has no active approval to revoke.')
        values.update(status='revoked', is_approved=False)
    elif action == 'restore':
        if vendor.status != 'revoked' or not vendor.approved:
            raise BSTError('Only a previously approved, revoked vendor can be restored.')
        values.update(status='approved', is_approved=True)
    change_vendor(vendor, version, **values)
    item = event(vendor.topic, action, vendor, uid, web_user,
                 {'reason': reason, 'profile': vendor.approved if action == 'approve' else vendor.draft if action in {'deny', 'changes'} else {}, 'revision': vendor.version})
    text = {'approve': 'Your application is approved.', 'deny': 'Your application was denied. You may revise and reapply.',
            'changes': 'Changes are required before review.', 'revoke': 'Your vendor approval was revoked.',
            'restore': 'Your vendor approval was restored.'}[action]
    if vendor.is_approved and action in {'deny', 'changes'}:
        text += ' Your previously approved listing information remains active.'
    notices(item, vendor, text=text + (f' Reason: {reason}' if reason else ''))
    db.session.commit()


def preapprove(topic, target_uid, data, uid=None, web_user=None):
    require_manager(topic, uid, web_user)
    target_uid = telegram_id(target_uid)
    data = profile(data)
    if BSTVendor.query.filter_by(topic_id=topic.id, telegram_user_id=target_uid).first():
        raise BSTError('A vendor/application already exists for this Telegram ID. Manage that record instead.')
    approved = dict(data, email_verified=False)
    vendor = BSTVendor(topic_id=topic.id, telegram_user_id=target_uid, draft=data, approved=approved,
                       status='approved', is_approved=True)
    db.session.add(vendor)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise BSTError('That vendor was just created by another admin. Open the existing record.') from None
    item = event(topic, 'preapprove', vendor, uid, web_user, {'profile': data})
    notices(item, vendor, text='An admin created and approved your vendor record. '
            + ('Verify your email in /bst before posting.' if options(topic)['verify_email'] else 'You may post compliant listings.'))
    db.session.commit()
    return vendor


def eligible(vendor):
    return bool(vendor and vendor.is_approved and vendor.status != 'revoked' and
                (not options(vendor.topic)['verify_email'] or vendor.approved.get('email_verified')))


def send_verification(vendor):
    email = validate_answer('email', (vendor.draft or {}).get('email'))
    state = vendor.verification or {}
    now = datetime.utcnow()
    if state.get('sent_at') and datetime.fromisoformat(state['sent_at']) > now - timedelta(seconds=60):
        raise BSTError('Wait one minute before requesting another verification email.')
    code = f'{secrets.randbelow(1000000):06d}'
    salt = secrets.token_hex(16)
    vendor.verification = {'hash': hashlib.sha256((salt + code).encode()).hexdigest(), 'salt': salt,
                           'email': email, 'expires': (now + timedelta(minutes=15)).isoformat(),
                           'sent_at': now.isoformat(), 'attempts': 0}
    db.session.commit()
    recipient = SimpleNamespace(email=email, username=vendor.draft.get('vendor_name', 'BST applicant'))
    sent = send_mailjet_message(recipient, 'Verify your BST email',
                               f'Your BST email verification code is {code}. It expires in 15 minutes. '
                               'Enter it in the Telegram bot. If you did not request this, ignore this email.')
    if not sent:
        append_notification_log(f'bst: verification email failed vendor={vendor.id}')
        raise BSTError('Email delivery failed. Ask an admin to check GTM email settings, then retry after one minute.')


def verify_email(vendor, code):
    # Lock across code checks to enforce the attempt budget under concurrency.
    vendor = BSTVendor.query.filter_by(id=vendor.id).with_for_update().populate_existing().one()
    state = dict(vendor.verification or {})
    if not state or state.get('attempts', 0) >= 5 or datetime.fromisoformat(state['expires']) < datetime.utcnow():
        raise BSTError('Verification expired or too many attempts. Request a new code.')
    if state['email'] != vendor.draft.get('email'):
        raise BSTError('Email changed. Request a new code.')
    state['attempts'] = state.get('attempts', 0) + 1
    vendor.verification = state
    digest = hashlib.sha256((state['salt'] + str(code).strip()).encode()).hexdigest()
    valid = secrets.compare_digest(digest, state['hash'])
    if valid:
        vendor.verified_email = state['email']
        vendor.verification = {}
        if vendor.approved.get('email') == state['email']:
            vendor.approved = dict(vendor.approved, email_verified=True)
    db.session.commit()
    if not valid:
        raise BSTError('Incorrect verification code. You have at most five attempts per code.')


def conversation(uid, state=None):
    row = db.session.get(BSTConversation, str(uid))
    if state is None:
        return row.state if row and row.expires_at > datetime.utcnow() else {}
    if row is None:
        row = BSTConversation(telegram_user_id=str(uid))
        db.session.add(row)
    row.state = state
    row.expires_at = datetime.utcnow() + timedelta(days=1)
    db.session.commit()
    return state


def deliver_notices():
    now = datetime.utcnow()
    rows = BSTNotice.query.filter(BSTNotice.complete.is_(False), BSTNotice.next_attempt_at <= now).order_by(BSTNotice.id).limit(30).all()
    for row in rows:
        claimed = db.session.execute(update(BSTNotice).where(BSTNotice.id == row.id, BSTNotice.complete.is_(False),
            BSTNotice.next_attempt_at <= now).values(next_attempt_at=now + timedelta(minutes=2), attempts=BSTNotice.attempts + 1))
        db.session.commit()
        if not claimed.rowcount:
            continue
        db.session.refresh(row)
        try:
            kind, recipient = row.recipient.split(':', 1)
            if kind == 'gtm':
                admin = db.session.get(User, int(recipient))
                source_event = db.session.get(BSTEvent, row.event_id)
                topic = db.session.get(BSTTopic, source_event.topic_id) if source_event else None
                if not admin or not admin.is_active or not admin.telegram_user_id or not topic or not can_manage(admin.telegram_user_id, topic.chat_id):
                    row.complete = True
                    db.session.commit()
                    continue
                # Existing email renderer accepts HTML; escape all applicant input.
                email_body = html.escape(row.body).replace('\n', '<br>')
                sent = send_notification_message(admin, admin.notification_channel or 'email', row.subject,
                                                 row.body, email_body=email_body)
            else:
                sent = send_telegram_chat_message(recipient, row.body)
            row.complete = bool(sent) or row.attempts >= 5
            if not sent and row.complete:
                append_notification_log(f'bst: notification abandoned notice={row.id}; applicant/admin can use /bst or /bstadmin')
            row.next_attempt_at = now + timedelta(seconds=60)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('BST notification delivery failed notice=%s', row.id)
            row.complete = row.attempts >= 5
            row.next_attempt_at = now + timedelta(seconds=60)
            db.session.commit()
    BSTConversation.query.filter(BSTConversation.expires_at < now).delete(synchronize_session=False)
    db.session.commit()
