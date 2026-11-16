"""Private Telegram application and administration menus for BST."""
from datetime import datetime

from . import db
from .models import BSTTopic, BSTVendor, User
from . import bst_service as bst
from .notifications import (
    send_telegram_interactive_message, delete_telegram_message, _telegram_api_post,
)


def button(text, data):
    return {'text': text[:64], 'callback_data': 'bs:' + data}


def send(uid, text, rows=None):
    message_id = send_telegram_interactive_message(uid, text[:4096], reply_markup={'inline_keyboard': rows} if rows else None)
    state = bst.conversation(uid)
    if message_id and state:
        bst.conversation(uid, dict(state, prompt_message_id=str(message_id)))
    return message_id


def own_vendor(uid, vendor_id):
    vendor = db.session.get(BSTVendor, int(vendor_id))
    if vendor is None or vendor.telegram_user_id != str(uid):
        raise bst.BSTError('This application is not available to you.')
    return vendor


def admin_topic(uid, topic_id):
    topic = db.session.get(BSTTopic, int(topic_id))
    if topic is None:
        raise bst.BSTError('Topic not found.')
    bst.require_manager(topic, uid)
    return topic


def home(uid):
    vendors = BSTVendor.query.filter_by(telegram_user_id=str(uid)).order_by(BSTVendor.created_at.desc()).limit(30).all()
    send(uid, 'Your BST applications. To apply to another topic, use its pinned Apply to Sell button.',
         [[button(f'{v.topic.name}: {v.status}', f'self:{v.id}')] for v in vendors])


def applicant_card(uid, vendor):
    data = vendor.draft or {}
    text = f'BST application: {vendor.topic.name}\nTelegram ID: {vendor.telegram_user_id}\nStatus: {vendor.status}'
    if vendor.is_approved:
        different = any(data.get(field) != vendor.approved.get(field) for field in bst.FIELDS)
        text += '\nYour previously approved information remains active; the changes below are not yet approved.' if different else '\nApproved until revoked.'
        if not bst.eligible(vendor):
            text += '\nVerify the approved email before posting in this topic.'
    if vendor.reason:
        text += '\nAdmin reason: ' + vendor.reason[:600]
    for field, label in bst.FIELDS.items():
        text += f'\n\n{label}: {data.get(field, "Not provided")[:250]}'
    rows = [[button('View complete application', f'answers:{vendor.id}')]]
    if vendor.approved:
        rows.append([button('View approved information', f'approvedanswers:{vendor.id}')])
    if vendor.status != 'revoked':
        rows.extend([[button('Edit ' + label, f'edit:{vendor.id}:{field}')] for field, label in bst.FIELDS.items()])
        if bst.options(vendor.topic)['verify_email']:
            rows.append([button('Verify email / Send code', f'verify:{vendor.id}')])
        if vendor.status != 'pending':
            rows.append([button('Submit for review', f'submit:{vendor.id}:{vendor.version}')])
    rows.append([button('My applications', 'home')])
    send(uid, text, rows)


def next_field(uid, vendor):
    missing = next((field for field in bst.FIELDS if not vendor.draft.get(field)), None)
    if missing:
        bst.conversation(uid, {'mode': 'field', 'vendor_id': vendor.id, 'field': missing, 'version': vendor.version})
        send(uid, f'{vendor.topic.name}\nEnter {bst.FIELDS[missing].lower()}:', [[button('Cancel / View application', f'self:{vendor.id}')]])
    else:
        bst.conversation(uid, {})
        applicant_card(uid, vendor)


def admin_home(uid):
    # Do not expose configured private group names to non-administrators.
    checks = {}
    rows = []
    for topic in BSTTopic.query.order_by(BSTTopic.name).all():
        if topic.chat_id not in checks:
            checks[topic.chat_id] = bst.can_manage(uid, topic.chat_id)
        if checks[topic.chat_id]:
            rows.append([button(topic.name, f'admin:{topic.id}')])
    send(uid, 'B/S/T administration. Choose a topic. To add one, run /bstadmin in that group topic, '
         'or send /bstadmin <group_chat_id> <topic_id> here.', rows[:80])


def admin_card(uid, topic):
    count = BSTVendor.query.filter_by(topic_id=topic.id, status='pending').count()
    send(uid, f'B/S/T: {topic.name}\nChat: {topic.chat_id} / Topic: {topic.thread_id}\n'
         f'Enforcement: {"Enabled" if topic.enabled else "Disabled"}\n{count} applications awaiting review.', [
             [button(f'Pending ({count})', f'list:{topic.id}:pending:0')],
             [button('Approved vendors', f'list:{topic.id}:approved:0'), button('All vendors', f'list:{topic.id}:all:0')],
             [button('Topic settings', f'config:{topic.id}')],
             [button('Create and approve vendor', f'create:{topic.id}')],
             [button('Application link / Onboarding card', f'link:{topic.id}')],
             [button('Other topics', 'admins')],
         ])


def config_card(uid, topic):
    values = bst.options(topic)
    rows = [[button(f'{"ON" if values[key] else "OFF"}: {label}', f'toggle:{topic.id}:{key}:{topic.version}')] for key, (label, _) in bst.OPTIONS.items()]
    rows.insert(0, [button('Disable enforcement' if topic.enabled else 'Enable enforcement', f'toggle:{topic.id}:enabled:{topic.version}')])
    rows.extend([[button('Rename topic label', f'rename:{topic.id}')], [button('Back', f'admin:{topic.id}')]])
    send(uid, f'{topic.name}: topic settings\nOnly approved vendors may post. Approval never bypasses these rules. '
         'Dependent options must be configured together: enable photos before albums, and captions before requiring captions.', rows)


def admin_vendor_card(uid, vendor):
    bst.require_manager(vendor.topic, uid)
    text = f'{vendor.topic.name}\nVendor #{vendor.id} / Telegram ID: {vendor.telegram_user_id}\n'
    text += f'Status: {vendor.status}; posting approval: {"active" if vendor.is_approved else "none"}\nRevision: {vendor.version}'
    for field, label in bst.FIELDS.items():
        text += f'\n\n{label}: {vendor.draft.get(field, "Not provided")[:250]}'
    if vendor.reason:
        text += '\n\nLast reason: ' + vendor.reason[:600]
    if vendor.is_approved and vendor.draft != {key: value for key, value in vendor.approved.items() if key != 'email_verified'}:
        text += '\n\nA prior approved profile remains active; use GTM to compare the full profiles.'
    rows = [[button('Full application / Approved profile', f'details:{vendor.id}')]]
    if vendor.status == 'pending':
        rows.append([button('Approve', f'decide:{vendor.id}:approve:{vendor.version}'),
                     button('Request changes', f'decide:{vendor.id}:changes:{vendor.version}')])
        rows.append([button('Deny', f'decide:{vendor.id}:deny:{vendor.version}')])
    if vendor.is_approved:
        rows.append([button('Revoke approval', f'decide:{vendor.id}:revoke:{vendor.version}')])
    if vendor.status == 'revoked':
        rows.append([button('Restore approval', f'decide:{vendor.id}:restore:{vendor.version}')])
    rows.append([button('Back to topic', f'admin:{vendor.topic_id}')])
    send(uid, text, rows)


def configure_from_command(uid, chat_id, thread_id, name=None):
    if not bst.can_manage(uid, str(chat_id)):
        raise bst.BSTError('Only group admins and linked GTM admins can configure BST.')
    try:
        thread_id = int(thread_id)
    except (TypeError, ValueError):
        raise bst.BSTError('Run /bstadmin inside a forum topic, or DM /bstadmin <group_chat_id> <topic_id>.') from None
    topic = BSTTopic.query.filter_by(chat_id=str(chat_id), thread_id=int(thread_id)).first()
    if topic is None:
        topic = bst.save_topic(chat_id, thread_id, name or f'BST {chat_id} / {thread_id}', {}, False, uid=uid)
    return topic


def handle_message(message, command, args):
    chat = message.get('chat') or {}
    uid = str((message.get('from') or {}).get('id') or '')
    private = chat.get('type') == 'private'
    if not uid or (message.get('from') or {}).get('is_bot'):
        return False
    if private and command in {'/start', '/help'} and not args and BSTTopic.query.filter_by(enabled=True).first():
        if User.query.filter_by(telegram_user_id=uid).first() is None:
            send(uid, 'For BST, use your group’s Apply to Sell button to apply, or /bst to view your applications. '
                 'BST applicants do not need a GTM account. Group admins can use /bstadmin. '
                 'To use GTM group-test features, generate a Telegram link token from your GTM profile.',
                 [[button('My BST applications', 'home')], [button('BST administration', 'admins')]])
            return True
    is_start = command == '/start' and (args.startswith('bst_') or args.startswith('bsa_'))
    if command in {'/bst', '/bstadmin'} or is_start:
        try:
            if not private:
                topic = BSTTopic.query.filter_by(chat_id=str(chat.get('id')), thread_id=message.get('message_thread_id')).first()
                if command == '/bstadmin':
                    topic = configure_from_command(uid, chat['id'], message.get('message_thread_id'),
                                                   f'{chat.get("title", "BST")} / {message.get("message_thread_id")}')
                if topic is None:
                    return False
                if topic.enabled:
                    delete_telegram_message(str(chat['id']), message.get('message_id'))
                link = bst.topic_link(topic, admin=command == '/bstadmin')
                if link:
                    sent = send_telegram_interactive_message(str(chat['id']), 'Open the bot privately to manage BST.' if command == '/bstadmin' else 'Apply or check your BST application in the bot.',
                        message_thread_id=message.get('message_thread_id'), reply_markup={'inline_keyboard': [[{'text': 'B/S/T Admin' if command == '/bstadmin' else 'Apply to Sell / My Application', 'url': link}]]})
                    if sent:
                        from .bst_moderation import remember
                        from datetime import timedelta
                        remember(topic, sent, uid, 'reminder', due=datetime.utcnow() + timedelta(seconds=60))
                return True
            bst.conversation(uid, {})
            if is_start:
                prefix, code = args.split('_', 1)
                topic = BSTTopic.query.filter_by(code=code).first()
                if topic is None:
                    raise bst.BSTError('This BST application link is unavailable. Ask a group admin for the current link.')
                if prefix == 'bsa':
                    bst.require_manager(topic, uid)
                    admin_card(uid, topic)
                else:
                    if not topic.enabled:
                        raise bst.BSTError('This BST topic is currently disabled.')
                    vendor = bst.get_vendor(topic, uid, (message.get('from') or {}).get('username'))
                    if vendor.status == 'draft':
                        next_field(uid, vendor)
                    else:
                        applicant_card(uid, vendor)
            elif command == '/bstadmin':
                if args:
                    parts = args.split()
                    if len(parts) != 2:
                        raise bst.BSTError('Use /bstadmin <group_chat_id> <topic_id>.')
                    topic = configure_from_command(uid, parts[0], parts[1])
                    admin_card(uid, topic)
                else:
                    admin_home(uid)
            else:
                home(uid)
        except (bst.BSTError, ValueError, TypeError) as exc:
            db.session.rollback()
            if private:
                send(uid, str(exc))
            elif command == '/bstadmin' and bst.can_manage(uid, str(chat.get('id'))):
                send_telegram_interactive_message(str(chat.get('id')), str(exc), message_thread_id=message.get('message_thread_id'))
        return True
    if not private or command:
        return False
    state = bst.conversation(uid)
    if not state:
        return False
    replied_id = (message.get('reply_to_message') or {}).get('message_id')
    if replied_id and str(replied_id) != state.get('prompt_message_id'):
        return False
    text = message.get('text') or ''
    try:
        mode = state.get('mode')
        if mode == 'field':
            vendor = own_vendor(uid, state['vendor_id'])
            bst.save_answer(vendor, state['field'], text, state['version'])
            next_field(uid, vendor)
        elif mode == 'email_code':
            vendor = own_vendor(uid, state['vendor_id'])
            bst.verify_email(vendor, text)
            bst.conversation(uid, {})
            send(uid, 'Email verified.')
            applicant_card(uid, vendor)
        elif mode == 'decision':
            vendor = db.session.get(BSTVendor, state['vendor_id'])
            if vendor is None:
                raise bst.BSTError('Application not found.')
            bst.decide(vendor, state['action'], state['version'], text, uid=uid)
            bst.conversation(uid, {})
            admin_vendor_card(uid, vendor)
        elif mode == 'rename':
            topic = admin_topic(uid, state['topic_id'])
            bst.save_topic(topic.chat_id, topic.thread_id, text, bst.options(topic), topic.enabled, topic, state['version'], uid=uid)
            bst.conversation(uid, {})
            config_card(uid, topic)
        elif mode == 'create':
            topic = admin_topic(uid, state['topic_id'])
            data = dict(state.get('data') or {})
            field = state['field']
            data[field] = bst.telegram_id(text) if field == 'telegram_user_id' else bst.validate_answer(field, text)
            fields = ['telegram_user_id', *bst.FIELDS]
            following = next((key for key in fields if key not in data), None)
            if following:
                state.update(data=data, field=following)
                bst.conversation(uid, state)
                send(uid, 'Enter ' + bst.FIELDS.get(following, 'numeric Telegram user ID') + ':', [[button('Cancel', f'admin:{topic.id}')]])
            else:
                state.update(data=data, mode='create_preview')
                bst.conversation(uid, state)
                summary = '\n'.join(f'{bst.FIELDS.get(key, "Telegram ID")}: {value}' for key, value in data.items())
                send(uid, f'Create and approve vendor for {topic.name}?\n{summary}\n'
                     + ('Email verification will still be required before posting.' if bst.options(topic)['verify_email'] else ''),
                     [[button('Create and approve', f'preapprove:{topic.id}')], [button('Cancel', f'admin:{topic.id}')]])
        else:
            return False
    except (bst.BSTError, ValueError, TypeError) as exc:
        db.session.rollback()
        send(uid, str(exc) + '\nUse /bst or /bstadmin to return to the menu.')
    return True


def handle_callback(query):
    uid = str((query.get('from') or {}).get('id') or '')
    chat = (query.get('message') or {}).get('chat') or {}
    if not uid or chat.get('type') != 'private' or str(chat.get('id')) != uid:
        return 'Open /bst or /bstadmin in a private chat with the bot.'
    parts = str(query.get('data') or '').split(':')[1:]
    try:
        action = parts[0]
        if action in {'home', 'admins', 'self', 'admin', 'config', 'list', 'view', 'details', 'answers', 'approvedanswers', 'link'}:
            bst.conversation(uid, {})
        if action == 'home':
            home(uid)
        elif action == 'admins':
            admin_home(uid)
        elif action == 'self':
            applicant_card(uid, own_vendor(uid, parts[1]))
        elif action in {'answers', 'approvedanswers'}:
            vendor = own_vendor(uid, parts[1])
            data = vendor.approved if action == 'approvedanswers' else vendor.draft
            for field, label in bst.FIELDS.items():
                send(uid, f'{label}:\n{data.get(field, "Not provided")}')
            if vendor.reason:
                send(uid, 'Admin reason:\n' + vendor.reason)
            applicant_card(uid, vendor)
        elif action == 'edit':
            vendor = own_vendor(uid, parts[1])
            field = parts[2]
            if vendor.status == 'revoked' or field not in bst.FIELDS:
                raise bst.BSTError('This application cannot be edited.')
            bst.conversation(uid, {'mode': 'field', 'vendor_id': vendor.id, 'field': field, 'version': vendor.version})
            send(uid, 'Enter ' + bst.FIELDS[field] + ':', [[button('Cancel', f'self:{vendor.id}')]])
        elif action == 'submit':
            vendor = own_vendor(uid, parts[1])
            bst.submit(vendor, int(parts[2]))
            bst.conversation(uid, {})
            applicant_card(uid, vendor)
        elif action == 'verify':
            vendor = own_vendor(uid, parts[1])
            bst.send_verification(vendor)
            bst.conversation(uid, {'mode': 'email_code', 'vendor_id': vendor.id})
            send(uid, 'Enter the six-digit code sent to your email. It expires in 15 minutes.', [[button('Back / Resend', f'self:{vendor.id}')]])
        elif action == 'admin':
            admin_card(uid, admin_topic(uid, parts[1]))
        elif action == 'config':
            config_card(uid, admin_topic(uid, parts[1]))
        elif action == 'toggle':
            topic = admin_topic(uid, parts[1])
            key = parts[2]
            if key not in bst.OPTIONS and key != 'enabled':
                raise bst.BSTError('Unknown setting.')
            values = bst.options(topic)
            enabled = topic.enabled
            if key == 'enabled':
                enabled = not enabled
            else:
                values[key] = not values[key]
            bst.save_topic(topic.chat_id, topic.thread_id, topic.name, values, enabled, topic, int(parts[3]), uid=uid)
            config_card(uid, topic)
        elif action == 'rename':
            topic = admin_topic(uid, parts[1])
            bst.conversation(uid, {'mode': 'rename', 'topic_id': topic.id, 'version': topic.version})
            send(uid, 'Enter a short label for this BST topic:')
        elif action == 'list':
            topic = admin_topic(uid, parts[1])
            kind, page = parts[2], max(0, int(parts[3]))
            query = BSTVendor.query.filter_by(topic_id=topic.id)
            if kind == 'approved':
                query = query.filter_by(is_approved=True)
            elif kind == 'pending':
                query = query.filter_by(status='pending')
            elif kind != 'all':
                raise bst.BSTError('Unknown vendor filter.')
            vendors = query.order_by(BSTVendor.created_at, BSTVendor.id).offset(page * 8).limit(9).all()
            rows = [[button(f'{v.draft.get("vendor_name") or v.telegram_user_id}: {v.status}', f'view:{v.id}')] for v in vendors[:8]]
            navigation = []
            if page:
                navigation.append(button('Previous', f'list:{topic.id}:{kind}:{page - 1}'))
            if len(vendors) > 8:
                navigation.append(button('Next', f'list:{topic.id}:{kind}:{page + 1}'))
            if navigation:
                rows.append(navigation)
            rows.append([button('Back', f'admin:{topic.id}')])
            send(uid, f'{topic.name}: {kind} vendors', rows)
        elif action in {'view', 'decide', 'details'}:
            vendor = db.session.get(BSTVendor, int(parts[1]))
            if vendor is None:
                raise bst.BSTError('Application not found.')
            bst.require_manager(vendor.topic, uid)
            if action == 'details':
                for title, data in [('Latest application', vendor.draft), ('Approved profile', vendor.approved)]:
                    if data:
                        for field, label in bst.FIELDS.items():
                            send(uid, f'{title}: {label}\n{data.get(field, "Not provided")}')
                admin_vendor_card(uid, vendor)
            elif action == 'view':
                admin_vendor_card(uid, vendor)
            elif parts[2] == 'approve':
                bst.decide(vendor, 'approve', int(parts[3]), uid=uid)
                bst.conversation(uid, {})
                admin_vendor_card(uid, vendor)
            else:
                if parts[2] not in {'deny', 'changes', 'revoke', 'restore'}:
                    raise bst.BSTError('Unknown decision.')
                bst.conversation(uid, {'mode': 'decision', 'vendor_id': vendor.id, 'action': parts[2], 'version': int(parts[3])})
                send(uid, 'Enter the reason to share with the applicant:', [[button('Cancel', f'view:{vendor.id}')]])
        elif action == 'create':
            topic = admin_topic(uid, parts[1])
            bst.conversation(uid, {'mode': 'create', 'topic_id': topic.id, 'data': {}, 'field': 'telegram_user_id'})
            send(uid, 'Enter the vendor’s numeric Telegram user ID:', [[button('Cancel', f'admin:{topic.id}')]])
        elif action == 'preapprove':
            topic = admin_topic(uid, parts[1])
            state = bst.conversation(uid)
            if state.get('mode') != 'create_preview' or state.get('topic_id') != topic.id:
                raise bst.BSTError('This vendor draft expired. Start again.')
            data = state['data']
            vendor = bst.preapprove(topic, data['telegram_user_id'], data, uid=uid)
            bst.conversation(uid, {})
            admin_vendor_card(uid, vendor)
        elif action in {'link', 'post', 'pin'}:
            topic = admin_topic(uid, parts[1])
            link = bst.topic_link(topic)
            if not link:
                raise bst.BSTError('Configure the Telegram bot username in GTM first.')
            if action == 'link':
                send(uid, f'{topic.name}\nApplication link:\n{link}', [[button('Post onboarding card', f'post:{topic.id}')],
                     [button('Post and pin onboarding card', f'pin:{topic.id}')], [button('Back', f'admin:{topic.id}')]])
            else:
                enabled = [label for key, (label, _) in bst.OPTIONS.items() if bst.options(topic)[key]]
                sent = send_telegram_interactive_message(topic.chat_id,
                    f'{topic.name}: vendor listings only. Apply and wait for approval before posting. Approval lasts until revoked.\n'
                    + '\n'.join(enabled), message_thread_id=topic.thread_id,
                    reply_markup={'inline_keyboard': [[{'text': 'Apply to Sell / My Application', 'url': link}]]})
                if not sent:
                    raise bst.BSTError('Unable to post the onboarding card. Check bot permissions.')
                if action == 'pin':
                    ok, _ = _telegram_api_post('pinChatMessage', {'chat_id': topic.chat_id, 'message_id': int(sent), 'disable_notification': True})
                    if not ok:
                        return 'Card posted, but pinning failed. Check the bot’s Pin Messages permission.'
                bst.event(topic, 'onboarding', uid=uid, details={'message_id': sent, 'pinned': action == 'pin'})
                db.session.commit()
        else:
            raise bst.BSTError('Unknown BST action.')
        return 'Updated.'
    except (bst.BSTError, ValueError, TypeError, IndexError, KeyError) as exc:
        db.session.rollback()
        return str(exc) or 'Invalid BST request. Reopen /bst or /bstadmin.'
