"""Telegram presentation layer for reviewed Public Result analysis runs."""

from copy import deepcopy
from datetime import datetime

from . import db
from .models import NotificationConfig, PublicResult, ResultAnalysisRun, Tag
from .saas import managed_public_url
from .notifications import (
    delete_telegram_message,
    download_telegram_photo,
    edit_telegram_message,
    normalize_telegram_thread_id,
    send_telegram_interactive_message,
)
from .result_analysis.service import AnalysisConflict, apply_analysis_run
from .storage import (
    StorageConfigurationError,
    StorageUploadError,
    delete_result_image,
    get_storage_settings,
    upload_result_image,
)


def _config(key, default=''):
    row = NotificationConfig.query.filter_by(key=key).first()
    return row.value if row is not None else default


def _base_url():
    return managed_public_url() or str(_config('service_base_url')).strip().rstrip('/')


def _state(result):
    value = deepcopy(result.review_state_json or {})
    value.setdefault('selected', {})
    value.setdefault('values', {})
    saved_tag_ids = value.get('tag_ids', [tag.id for tag in result.tags])
    value.setdefault('draft_tag_ids', list(saved_tag_ids))
    value.setdefault('draft_results_link', result.results_link)
    value.setdefault('draft_results_image_key', result.results_image_key)
    value.setdefault('messages', [])
    value.setdefault('submission_messages', [])
    return value


def _review_location(result):
    configured_chat = str(_config('telegram_coa_review_chat_id')).strip()
    if configured_chat.lower() in {'none', 'null'}:
        configured_chat = ''
    if configured_chat:
        thread = normalize_telegram_thread_id(_config('telegram_coa_review_thread_id'))
        return configured_chat, thread
    return result.submission_chat_id, normalize_telegram_thread_id(result.submission_thread_id)


def _result_url(result):
    base = _base_url()
    return f'{base}/public-results/{result.id}' if base else f'/public-results/{result.id}'


def _keyboard(run, result):
    state = _state(result)
    selected = state['selected']
    selected_tag_ids = {int(tag_id) for tag_id in state.get('tag_ids', [tag.id for tag in result.tags]) if str(tag_id).isdigit()}
    rows = []
    for finding in run.findings:
        actionable = finding.proposed_action in {'fill', 'create'}
        checked = bool(selected.get(str(finding.id), finding.proposed_action == 'fill'))
        icon = '✅' if checked and actionable else ('⬜' if actionable else '🚫')
        row = [{'text': f'{icon} {finding.canonical_type or finding.source_label}'[:42], 'callback_data': f'ra:t:{run.id}:{finding.id}'}]
        if actionable:
            row.append({'text': '✏️', 'callback_data': f'ra:v:{run.id}:{finding.id}'})
        rows.append(row)
    rows.extend([
        [{'text': 'Set Result Name', 'callback_data': f'ra:n:{run.id}'}, {'text': 'View Evidence', 'callback_data': f'ra:e:{run.id}'}],
        [{'text': f'Tags ({len(selected_tag_ids)})', 'callback_data': f'ra:tags:{run.id}:0'}, {'text': 'Sources', 'callback_data': f'ra:source:{run.id}'}],
        [{'text': f'{"✅" if state.get("include_metadata") else "⬜"} Include Metadata', 'callback_data': f'ra:m:{run.id}'}],
        [{'text': 'Approve & Publish', 'callback_data': f'ra:a:{run.id}'}, {'text': 'Reject', 'callback_data': f'ra:r:{run.id}'}],
    ])
    return {'inline_keyboard': rows}


def _tag_keyboard(run, state, page):
    tags = Tag.query.order_by(Tag.name).all()
    page_size = 10
    total_pages = max(1, (len(tags) + page_size - 1) // page_size)
    page = min(max(int(page), 0), total_pages - 1)
    selected = {int(tag_id) for tag_id in state.get('draft_tag_ids', []) if str(tag_id).isdigit()}
    rows = []
    for tag in tags[page * page_size:(page + 1) * page_size]:
        marker = '✅ ' if tag.id in selected else ''
        rows.append([{'text': f'{marker}{tag.name}'[:64], 'callback_data': f'ra:tag:{run.id}:{page}:{tag.id}'}])
    navigation = []
    if page > 0:
        navigation.append({'text': 'Previous', 'callback_data': f'ra:tags:{run.id}:{page - 1}'})
    navigation.append({'text': f'Page {page + 1}/{total_pages}', 'callback_data': f'ra:tags:{run.id}:{page}'})
    if page + 1 < total_pages:
        navigation.append({'text': 'Next', 'callback_data': f'ra:tags:{run.id}:{page + 1}'})
    rows.append(navigation)
    rows.append([
        {'text': 'Save Tags', 'callback_data': f'ra:tagsave:{run.id}'},
        {'text': 'Cancel', 'callback_data': f'ra:tagcancel:{run.id}'},
    ])
    return {'inline_keyboard': rows}


def _source_keyboard(run, state):
    link = state.get('draft_results_link')
    image_key = state.get('draft_results_image_key')
    rows = [
        [{'text': 'Add/Change Link', 'callback_data': f'ra:link:{run.id}'}, {'text': 'Add/Change Image/PDF', 'callback_data': f'ra:file:{run.id}'}],
        [{'text': 'Remove Link', 'callback_data': f'ra:unlink:{run.id}'}, {'text': 'Remove Image/PDF', 'callback_data': f'ra:unfile:{run.id}'}],
        [{'text': 'Save Sources', 'callback_data': f'ra:sourcesave:{run.id}'}, {'text': 'Cancel', 'callback_data': f'ra:sourcecancel:{run.id}'}],
    ]
    rows.insert(0, [{'text': f'Link: {"set" if link else "not set"}', 'callback_data': f'ra:source:{run.id}'}, {'text': f'File: {"set" if image_key else "not set"}', 'callback_data': f'ra:source:{run.id}'}])
    if link:
        rows.insert(1, [{'text': 'Open Current Link', 'url': link}])
    return {'inline_keyboard': rows}


def _discard_draft_file(result, state):
    draft_key = state.get('draft_results_image_key')
    if draft_key and draft_key != result.results_image_key:
        delete_result_image(draft_key)


def _body(run, result):
    state = _state(result)
    title = state.get('title') or 'Not set'
    source_parts = []
    if state.get('draft_results_image_key') or result.results_image_key:
        source_parts.append('uploaded image/PDF')
    if state.get('draft_results_link') or result.results_link:
        source_parts.append('submitted link')
    source = ' + '.join(source_parts) or 'unknown'
    saved_tag_ids = state.get('tag_ids', [tag.id for tag in result.tags])
    selected_tags = [tag.name for tag in Tag.query.filter(Tag.id.in_(saved_tag_ids)).order_by(Tag.name).all()] if saved_tag_ids else []
    lines = [f'COA Review #{result.id}', '', f'Result name: {title}', f'Source: {source}', f'Tags: {", ".join(selected_tags) if selected_tags else "None"}', f'Analysis run: #{run.id}', '', 'Findings:']
    selected = state['selected']
    for finding in run.findings:
        actionable = finding.proposed_action in {'fill', 'create'}
        checked = bool(selected.get(str(finding.id), finding.proposed_action == 'fill'))
        icon = '✅' if checked and actionable else ('⬜' if actionable else '🚫')
        value = state['values'].get(str(finding.id), finding.reviewed_value or finding.reported_value)
        lines.append(f'{icon} {finding.canonical_type or finding.source_label}: {value}')
    return '\n'.join(lines)[:4096]


def notify_review_ready(run):
    result = run.public_result
    if not result or result.publication_status != 'needs_review' or result.submission_platform != 'telegram':
        return False
    chat_id, thread_id = _review_location(result)
    if not chat_id:
        return False
    message_id = send_telegram_interactive_message(chat_id, _body(run, result), thread_id, _keyboard(run, result))
    if not message_id:
        return False
    result.review_message_id = message_id
    state = _state(result)
    state['messages'] = list(dict.fromkeys([*state['messages'], message_id]))
    result.review_state_json = state
    db.session.commit()
    return True


def handle_review_callback(user, chat_id, thread_id, data):
    if user is None or not user.is_active or not user.is_admin:
        return False, 'Administrator permission is required.'
    parts = str(data or '').split(':')
    if len(parts) < 3 or parts[0] != 'ra':
        return False, 'Invalid review action.'
    try:
        run = ResultAnalysisRun.query.get(int(parts[2]))
    except (TypeError, ValueError):
        run = None
    result = run.public_result if run else None
    if not result or result.publication_status != 'needs_review' or run.status != 'needs_review':
        return False, 'This review is no longer active.'
    expected_chat, expected_thread = _review_location(result)
    incoming_thread = normalize_telegram_thread_id(thread_id)
    if str(chat_id) != str(expected_chat) or incoming_thread != expected_thread:
        return False, 'This review belongs to a different chat or thread.'
    state = _state(result)
    action = parts[1]
    if action == 't' and len(parts) == 4:
        finding = next((item for item in run.findings if str(item.id) == parts[3]), None)
        if not finding or finding.proposed_action not in {'fill', 'create'}:
            return False, 'That finding cannot be selected.'
        key = str(finding.id)
        state['selected'][key] = not bool(state['selected'].get(key, finding.proposed_action == 'fill'))
        result.review_state_json = state
        db.session.commit()
        edit_telegram_message(chat_id, result.review_message_id, _body(run, result), _keyboard(run, result))
        return True, 'Selection updated.'
    if action == 'tags' and len(parts) == 4:
        try:
            page = int(parts[3])
        except (TypeError, ValueError):
            return False, 'Invalid tag page.'
        edit_telegram_message(chat_id, result.review_message_id, 'Select tags for this Public Result, then save or cancel.', _tag_keyboard(run, state, page))
        return True, 'Tag selection opened.'
    if action == 'tag' and len(parts) == 5:
        try:
            page = int(parts[3])
            tag_id = int(parts[4])
        except (TypeError, ValueError):
            return False, 'Invalid tag selection.'
        if Tag.query.get(tag_id) is None:
            return False, 'That tag no longer exists.'
        tag_ids = {int(value) for value in state.get('draft_tag_ids', []) if str(value).isdigit()}
        if tag_id in tag_ids:
            tag_ids.remove(tag_id)
        else:
            tag_ids.add(tag_id)
        state['draft_tag_ids'] = sorted(tag_ids)
        result.review_state_json = state
        db.session.commit()
        edit_telegram_message(chat_id, result.review_message_id, 'Select tags for this Public Result, then save or cancel.', _tag_keyboard(run, state, page))
        return True, 'Tag selection updated.'
    if action == 'tagsave' and len(parts) == 3:
        state['tag_ids'] = list(state.get('draft_tag_ids', []))
        result.review_state_json = state
        db.session.commit()
        edit_telegram_message(chat_id, result.review_message_id, _body(run, result), _keyboard(run, result))
        return True, 'Tags saved.'
    if action == 'tagcancel' and len(parts) == 3:
        state['draft_tag_ids'] = list(state.get('tag_ids', []))
        result.review_state_json = state
        db.session.commit()
        edit_telegram_message(chat_id, result.review_message_id, _body(run, result), _keyboard(run, result))
        return True, 'Tag changes canceled.'
    if action == 'source' and len(parts) == 3:
        edit_telegram_message(chat_id, result.review_message_id, 'Manage the COA link and attached image/PDF, then save or cancel.', _source_keyboard(run, state))
        return True, 'Source selection opened.'
    if action == 'link' and len(parts) == 3:
        prompt_id = send_telegram_interactive_message(chat_id, 'Reply with the public HTTP/HTTPS COA link.', thread_id, {'force_reply': True, 'selective': True}, result.review_message_id)
        if not prompt_id:
            return False, 'Unable to request a COA link.'
        state['pending_source_link_prompt'] = prompt_id
        state['messages'].append(prompt_id)
        result.review_state_json = state
        db.session.commit()
        return True, 'Send the COA link as a reply.'
    if action == 'file' and len(parts) == 3:
        prompt_id = send_telegram_interactive_message(chat_id, 'Reply with the COA PDF or image attachment.', thread_id, {'force_reply': True, 'selective': True}, result.review_message_id)
        if not prompt_id:
            return False, 'Unable to request a COA attachment.'
        state['pending_source_file_prompt'] = prompt_id
        state['messages'].append(prompt_id)
        result.review_state_json = state
        db.session.commit()
        return True, 'Send the COA attachment as a reply.'
    if action == 'unlink' and len(parts) == 3:
        state['draft_results_link'] = None
        result.review_state_json = state
        db.session.commit()
        edit_telegram_message(chat_id, result.review_message_id, 'Manage the COA link and attached image/PDF, then save or cancel.', _source_keyboard(run, state))
        return True, 'Link removed from the draft.'
    if action == 'unfile' and len(parts) == 3:
        _discard_draft_file(result, state)
        state['draft_results_image_key'] = None
        result.review_state_json = state
        db.session.commit()
        edit_telegram_message(chat_id, result.review_message_id, 'Manage the COA link and attached image/PDF, then save or cancel.', _source_keyboard(run, state))
        return True, 'Attachment removed from the draft.'
    if action == 'sourcesave' and len(parts) == 3:
        result.review_state_json = state
        db.session.commit()
        edit_telegram_message(chat_id, result.review_message_id, _body(run, result), _keyboard(run, result))
        return True, 'Sources saved.'
    if action == 'sourcecancel' and len(parts) == 3:
        _discard_draft_file(result, state)
        state['draft_results_link'] = result.results_link
        state['draft_results_image_key'] = result.results_image_key
        result.review_state_json = state
        db.session.commit()
        edit_telegram_message(chat_id, result.review_message_id, _body(run, result), _keyboard(run, result))
        return True, 'Source changes canceled.'
    if action == 'n':
        prompt_id = send_telegram_interactive_message(
            chat_id, 'Reply to this message with the Public Result name.', thread_id,
            {'force_reply': True, 'selective': True}, result.review_message_id,
        )
        if not prompt_id:
            return False, 'Unable to request a result name.'
        state['pending_name_prompt'] = prompt_id
        state['messages'].append(prompt_id)
        result.review_state_json = state
        db.session.commit()
        return True, 'Send the result name as a reply.'
    if action == 'v' and len(parts) == 4:
        finding = next((item for item in run.findings if str(item.id) == parts[3]), None)
        if not finding or finding.proposed_action not in {'fill', 'create'}:
            return False, 'That finding cannot be edited.'
        prompt_id = send_telegram_interactive_message(
            chat_id,
            f'Reply to this message with the corrected value for {finding.canonical_type}.',
            thread_id,
            {'force_reply': True, 'selective': True},
            result.review_message_id,
        )
        if not prompt_id:
            return False, 'Unable to request a corrected value.'
        state['pending_value_prompt'] = {'message_id': prompt_id, 'finding_id': finding.id}
        state['messages'].append(prompt_id)
        result.review_state_json = state
        db.session.commit()
        return True, 'Send the corrected value as a reply.'
    if action == 'm':
        state['include_metadata'] = not bool(state.get('include_metadata'))
        result.review_state_json = state
        db.session.commit()
        edit_telegram_message(chat_id, result.review_message_id, _body(run, result), _keyboard(run, result))
        return True, 'Metadata selection updated.'
    if action == 'e':
        evidence = '\n\n'.join(
            f'{item.canonical_type or item.source_label} (page {item.page_number or "?"}):\n{item.evidence_text}'
            for item in run.findings
        )[:4000]
        message_id = send_telegram_interactive_message(chat_id, evidence or 'No evidence was extracted.', thread_id)
        if message_id:
            state['messages'].append(message_id)
            result.review_state_json = state
            db.session.commit()
        return bool(message_id), 'Evidence displayed.'
    if action in {'a', 'r'}:
        if action == 'a' and not str(state.get('title') or '').strip():
            return False, 'Set the Result name before publishing.'
        decisions = {
            finding.id: {
                'accepted': action == 'a' and bool(state['selected'].get(str(finding.id), finding.proposed_action == 'fill')),
                'value': state.get('values', {}).get(str(finding.id), finding.reported_value),
            }
            for finding in run.findings
        }
        try:
            apply_analysis_run(
                run, decisions, user.id,
                include_metadata=bool(state.get('include_metadata')),
                commit=False,
            )
        except AnalysisConflict as exc:
            db.session.rollback()
            return False, str(exc)
        result.title = str(state.get('title') or result.title).strip()[:200]
        selected_tag_ids = {int(tag_id) for tag_id in state.get('tag_ids', []) if str(tag_id).isdigit()}
        if action == 'a':
            result.tags = Tag.query.filter(Tag.id.in_(selected_tag_ids)).order_by(Tag.name).all() if selected_tag_ids else []
        old_image_key = result.results_image_key
        draft_image_key = state.get('draft_results_image_key')
        if action == 'a':
            result.results_link = state.get('draft_results_link')
            result.results_image_key = draft_image_key
        result.publication_status = 'published' if action == 'a' else 'rejected'
        result.posted_at = datetime.utcnow()
        db.session.commit()
        if action == 'a' and old_image_key and old_image_key != result.results_image_key:
            delete_result_image(old_image_key)
        if action == 'r' and draft_image_key and draft_image_key != old_image_key:
            delete_result_image(draft_image_key)
        _complete_review(result, run, user, published=action == 'a')
        return True, 'Review complete.'
    return False, 'Invalid review action.'


def handle_review_reply(user, chat_id, thread_id, message):
    if user is None or not user.is_active or not user.is_admin:
        return False
    reply_id = str(((message.get('reply_to_message') or {}).get('message_id')) or '')
    if not reply_id:
        return False
    candidates = PublicResult.query.filter_by(
        publication_status='needs_review', submission_platform='telegram',
    ).all()
    for result in candidates:
        expected_chat, expected_thread = _review_location(result)
        state = _state(result)
        incoming_thread = normalize_telegram_thread_id(thread_id)
        if str(expected_chat) != str(chat_id) or incoming_thread != expected_thread:
            continue
        prompt_id = str(state.get('pending_name_prompt') or '')
        review_id = str(result.review_message_id or '')
        source_link_prompt = str(state.get('pending_source_link_prompt') or '')
        source_file_prompt = str(state.get('pending_source_file_prompt') or '')
        reply_text = str(message.get('text') or '').strip()
        attachment = message.get('document') or {}
        photos = message.get('photo') or []
        attachment = attachment or (photos[-1] if photos else {})
        is_source_reply = False
        if source_link_prompt and reply_id == source_link_prompt:
            if not reply_text.startswith(('http://', 'https://')) or len(reply_text) > 500:
                return False
            state['draft_results_link'] = reply_text
            state.pop('pending_source_link_prompt', None)
            is_source_reply = True
        elif source_file_prompt and reply_id == source_file_prompt:
            max_bytes = int(get_storage_settings()['max_upload_size_mb'] * 1024 * 1024)
            upload = download_telegram_photo(attachment.get('file_id'), max_bytes=max_bytes) if attachment else None
            if upload is None:
                return False
            upload.filename = str((message.get('document') or {}).get('file_name') or upload.filename or 'telegram-coa')
            try:
                new_key = upload_result_image(upload, 'public-results')
            except (StorageConfigurationError, StorageUploadError):
                return False
            _discard_draft_file(result, state)
            state['draft_results_image_key'] = new_key
            state.pop('pending_source_file_prompt', None)
            is_source_reply = True
        elif reply_id in {prompt_id, review_id} and prompt_id:
            if not reply_text or len(reply_text) > 200:
                return False
            state['title'] = reply_text
            state.pop('pending_name_prompt', None)
        elif reply_id in {
            str((state.get('pending_value_prompt') or {}).get('message_id') or ''),
            review_id,
        } and state.get('pending_value_prompt'):
            if not reply_text or len(reply_text) > 200:
                return False
            finding_id = str(state['pending_value_prompt']['finding_id'])
            state['values'][finding_id] = reply_text[:500]
            state.pop('pending_value_prompt', None)
        else:
            continue
        state['messages'].append(str(message.get('message_id')))
        result.review_state_json = state
        db.session.commit()
        run = result.analysis_runs.filter_by(status='needs_review').order_by(ResultAnalysisRun.id.desc()).first()
        if run:
            if is_source_reply:
                edit_telegram_message(chat_id, result.review_message_id, 'Manage the COA link and attached image/PDF, then save or cancel.', _source_keyboard(run, state))
            else:
                edit_telegram_message(chat_id, result.review_message_id, _body(run, result), _keyboard(run, result))
        return True
    return False


def _complete_review(result, run, user, published):
    chat_id, _ = _review_location(result)
    state = _state(result)
    accepted = [item for item in run.findings if item.review_decision == 'accepted']
    lines = ['Review Complete', '', f'Result: {result.title}', f'Reviewed by: {user.username}']
    if published:
        lines.extend(['', 'Published results:'])
        lines.extend(f'• {item.canonical_type}: {item.reviewed_value}' for item in accepted)
        result_url = _result_url(result)
        markup = {'inline_keyboard': [[{'text': 'View Result', 'url': result_url}]]} if result_url.startswith('http') else {'inline_keyboard': []}
    else:
        lines.extend(['', 'Submission rejected. No Public Result was published.'])
        markup = {'inline_keyboard': []}
    for message_id in set(state.get('messages', [])):
        if str(message_id) != str(result.review_message_id):
            delete_telegram_message(chat_id, message_id)
    if result.submission_message_id:
        delete_telegram_message(result.submission_chat_id, result.submission_message_id)
    for message_id in set(state.get('submission_messages', [])):
        delete_telegram_message(result.submission_chat_id, message_id)
    edit_telegram_message(chat_id, result.review_message_id, '\n'.join(lines)[:4096], markup)
