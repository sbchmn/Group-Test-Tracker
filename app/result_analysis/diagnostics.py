import json
import os
import re
from datetime import datetime, timezone

from flask import current_app

try:
    import fcntl
except ImportError:  # pragma: no cover - production runs on Linux
    fcntl = None


DEFAULT_MAX_BYTES = 128 * 1024
MIN_MAX_BYTES = 4 * 1024
MAX_MAX_BYTES = 1024 * 1024
MAX_DETAIL_LENGTH = 500
MAX_FIELD_LENGTH = 160
_SECRET_REPLACEMENTS = (
    (re.compile(r'(?i)\b(?:sk|xai|ant)-[a-z0-9_-]{8,}\b'), '[REDACTED]'),
    (re.compile(r'(?i)(bearer\s+)[a-z0-9._~+/-]+=*'), r'\1[REDACTED]'),
    (re.compile(r'(?i)(api[_ -]?key\s*[:=]\s*)[^\s,;]+'), r'\1[REDACTED]'),
)


def _bounded_setting(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _diagnostic_log_path():
    configured = current_app.config.get('RESULT_ANALYSIS_DIAGNOSTIC_LOG_PATH')
    configured = configured or os.environ.get('RESULT_ANALYSIS_DIAGNOSTIC_LOG_PATH')
    if configured:
        path = os.path.abspath(str(configured))
    else:
        base_dir = os.path.abspath(os.path.join(current_app.root_path, os.pardir))
        path = os.path.join(base_dir, 'instance', 'result_analysis_diagnostics.log')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _diagnostic_max_bytes():
    configured = current_app.config.get('RESULT_ANALYSIS_DIAGNOSTIC_LOG_MAX_BYTES')
    configured = configured or os.environ.get('RESULT_ANALYSIS_DIAGNOSTIC_LOG_MAX_BYTES')
    return _bounded_setting(configured, DEFAULT_MAX_BYTES, MIN_MAX_BYTES, MAX_MAX_BYTES)


def _sanitize(value, limit=MAX_FIELD_LENGTH):
    if value is None:
        return None
    cleaned = ' '.join(str(value).split())
    for pattern, replacement in _SECRET_REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned[:limit] or None


def _exception_fields(exc):
    stored = getattr(exc, 'diagnostic', None)
    if isinstance(stored, dict):
        fields = dict(stored)
    else:
        fields = {}

    fields.setdefault('exception_type', exc.__class__.__name__)
    fields.setdefault('status_code', getattr(exc, 'status_code', None))
    fields.setdefault('request_id', getattr(exc, 'request_id', None))

    body = getattr(exc, 'body', None)
    if isinstance(body, dict):
        error = body.get('error', body)
        if isinstance(error, dict):
            fields.setdefault('error_code', error.get('code') or error.get('type'))
            fields.setdefault('error_param', error.get('param'))
            fields.setdefault('detail', error.get('message'))

    response = getattr(exc, 'response', None)
    headers = getattr(response, 'headers', None)
    if not fields.get('request_id') and hasattr(headers, 'get'):
        fields['request_id'] = headers.get('x-request-id')
    fields.setdefault('error_code', getattr(exc, 'code', None))
    fields.setdefault('detail', str(exc))
    return fields


def _lock(handle, exclusive=True):
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)


def _unlock(handle):
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _append_bounded_line(path, line, max_bytes):
    with open(path, 'a+', encoding='utf-8') as handle:
        _lock(handle)
        try:
            handle.write(line)
            handle.flush()
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size <= max_bytes:
                return

            keep_bytes = max(max_bytes // 2, MIN_MAX_BYTES)
            start = max(0, size - keep_bytes)
            handle.seek(start)
            tail = handle.read()
            if start:
                separator = tail.find('\n')
                tail = tail[separator + 1:] if separator >= 0 else ''
            handle.seek(0)
            handle.truncate(0)
            handle.write(tail)
            handle.flush()
        finally:
            _unlock(handle)


def append_provider_diagnostic(
        provider, operation, model, outcome, exception=None, request_id=None, run_id=None, include_detail=True):
    """Append one sanitized diagnostic entry without affecting the provider workflow."""
    try:
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
            'provider': _sanitize(provider, 32),
            'operation': _sanitize(operation, 48),
            'outcome': _sanitize(outcome, 24),
            'model': _sanitize(model, 120),
        }
        if run_id is not None:
            entry['run_id'] = int(run_id)
        if exception is not None:
            fields = _exception_fields(exception)
            entry.update({
                'exception_type': _sanitize(fields.get('exception_type'), 120),
                'status_code': fields.get('status_code') if isinstance(fields.get('status_code'), int) else None,
                'error_code': _sanitize(fields.get('error_code'), 120),
                'error_param': _sanitize(fields.get('error_param'), 120),
                'request_id': _sanitize(fields.get('request_id'), 160),
                'detail': _sanitize(fields.get('detail'), MAX_DETAIL_LENGTH) if include_detail else None,
            })
        elif request_id:
            entry['request_id'] = _sanitize(request_id, 160)

        entry = {key: value for key, value in entry.items() if value is not None}
        line = json.dumps(entry, ensure_ascii=True, separators=(',', ':')) + '\n'
        _append_bounded_line(_diagnostic_log_path(), line, _diagnostic_max_bytes())
    except (OSError, TypeError, ValueError):
        current_app.logger.warning('Unable to write the bounded result-analysis diagnostic log.')


def read_provider_diagnostics():
    """Return only the bounded recent tail for administrator display."""
    path = _diagnostic_log_path()
    if not os.path.exists(path):
        return ''
    max_bytes = _diagnostic_max_bytes()
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            _lock(handle, exclusive=False)
            try:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                start = max(0, size - max_bytes)
                handle.seek(start)
                contents = handle.read(max_bytes)
            finally:
                _unlock(handle)
        if start:
            separator = contents.find('\n')
            contents = contents[separator + 1:] if separator >= 0 else ''
        return contents
    except OSError:
        current_app.logger.warning('Unable to read the bounded result-analysis diagnostic log.')
        return ''
