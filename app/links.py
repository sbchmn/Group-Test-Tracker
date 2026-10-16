"""Validation for user-supplied links that get rendered as hrefs or button URLs."""

from urllib.parse import urlsplit

from wtforms.validators import ValidationError

ALLOWED_LINK_SCHEMES = frozenset({'http', 'https'})

_EMPTY_LINK_SENTINELS = frozenset({'', '#', 'none', 'null', 'about:blank'})


def safe_http_url(value, max_length=None):
    """Return ``value`` stripped, or ``None`` unless it is a plain HTTP(S) URL."""
    candidate = str(value or '').strip()
    if candidate.lower() in _EMPTY_LINK_SENTINELS:
        return None
    if max_length is not None and len(candidate) > max_length:
        return None
    # Whitespace and control characters let `java\nscript:` style values slip past
    # a scheme check, so reject them outright rather than normalising them away.
    if any(character.isspace() or character < '\x20' for character in candidate):
        return None
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    if parsed.scheme.lower() not in ALLOWED_LINK_SCHEMES:
        return None
    if not parsed.hostname:
        return None
    return candidate


def validate_http_link(form, field):
    """WTForms validator: ``field`` must be empty or a plain HTTP(S) URL."""
    raw = str(field.data or '').strip()
    if not raw:
        return
    if safe_http_url(raw) is None:
        raise ValidationError(
            'Enter a full http:// or https:// link. Other address types are not allowed.'
        )


def http_link_for_template(value):
    """Jinja filter: neutralise anything unsafe before it reaches an ``href``.

    Stored rows predate write-time validation, so render-time filtering is a
    separate layer and not redundant with it.
    """
    return safe_http_url(value) or ''
