"""Central guard for the reserved control-plane support account.

Per the control plane's "Reserved support-account invariant": the account is
identified only by its immutable ``system_account_key``, never by username or
email matching. No GTM web, bot, import, or ordinary application service path
may rename, edit, demote, reset, enable/disable, delete, or bot-link this
account; those mutations are reserved exclusively for the authenticated
``/internal/control-plane/v1/support`` operation in ``control_plane_routes``.
"""

from .models import RESERVED_SUPPORT_EMAIL, RESERVED_SUPPORT_USERNAME


class ProtectedAccountError(ValueError):
    """Raised when an ordinary mutation path targets the reserved support account."""


def is_reserved_identity(username=None, email=None):
    """True if the given username/email normalizes to the reserved support identity."""
    normalized_username = str(username or '').strip().lower()
    normalized_email = str(email or '').strip().lower()
    return (
        (normalized_username and normalized_username == RESERVED_SUPPORT_USERNAME.lower())
        or (normalized_email and normalized_email == RESERVED_SUPPORT_EMAIL.lower())
    )


def assert_mutable(user):
    """Raise ProtectedAccountError if ``user`` is the reserved support account."""
    if user is not None and getattr(user, 'is_reserved_support_account', False):
        raise ProtectedAccountError('This is a managed support account and cannot be edited here.')
