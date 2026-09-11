"""Telegram presentation layer for reviewed Public Result analysis runs."""

from copy import deepcopy
from datetime import datetime

from . import db
from .models import NotificationConfig, PublicResult, ResultAnalysisRun
from .notifications import delete_telegram_message, edit_telegram_message, send_telegram_interactive_message
from .result_analysis.service import AnalysisConflict, apply_analysis_run


def _config(key, default=''):
    row = NotificationConfig.query.filter_by(key=key).first()
    return row.value if row is not None else default


def _base_url():
    return str(_config('service_base_url')).strip().rstrip('/')


def _state(result):
    value = deepcopy(result.review_state_json or {})
    value.setdefault('selected', {})
    value.setdefault('values', {})
    value.setdefault('messages', [])
    value.setdefault('submission_messages', [])
    return value


def _review_location(result):
    configured_chat = str(_config('telegram_coa_review_chat_id')).strip()
    if configured_chat:
        thread = str(_config('telegram_coa_review_thread_id')).strip() or None
        return configured_chat, thread
    return result.submission_chat_id, result.submission_thread_id


def _result_url(result):
    base = _base_url()
    return f'{base}/public-results/{result.id}' if base else f'/public-results/{result.id}'


def _keyboard(run, result):
    state = _state(result)
    selected = state['selected']
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
        [{'text': f'{"✅" if state.get("include_metadata") else "⬜"} Include Metadata', 'callback_data': f'ra:m:{run.id}'}],
        [{'text': 'Approve & Publish', 'callback_data': f'ra:a:{run.id}'}, {'text': 'Reject', 'callback_data': f'ra:r:{run.id}'}],
    ])
    return {'inline_keyboard': rows}


def _body(run, result):
    state = _state(result)
    title = state.get('title') or 'Not set'
    lines = [f'COA Review #{result.id}', '', f'Result name: {title}', f'Analysis run: #{run.id}', '', 'Findings:']
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
    if str(chat_id) != str(expected_chat) or str(thread_id or '') != str(expected_thread or ''):
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
        result.publication_status = 'published' if action == 'a' else 'rejected'
        result.posted_at = datetime.utcnow()
        db.session.commit()
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
        if str(expected_chat) != str(chat_id) or str(expected_thread or '') != str(thread_id or ''):
            continue
        title = str(message.get('text') or '').strip()
        if not title or len(title) > 200:
            return False
        if str(state.get('pending_name_prompt') or '') == reply_id:
            state['title'] = title
            state.pop('pending_name_prompt', None)
        elif str((state.get('pending_value_prompt') or {}).get('message_id') or '') == reply_id:
            finding_id = str(state['pending_value_prompt']['finding_id'])
            state['values'][finding_id] = title[:500]
            state.pop('pending_value_prompt', None)
        else:
            continue
        state['messages'].append(str(message.get('message_id')))
        result.review_state_json = state
        db.session.commit()
        run = result.analysis_runs.filter_by(status='needs_review').order_by(ResultAnalysisRun.id.desc()).first()
        if run:
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
