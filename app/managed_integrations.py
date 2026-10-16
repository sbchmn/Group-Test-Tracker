"""Owner-supplied per-tenant settings for managed deployments.

GTT_MANAGED_INTEGRATIONS is a JSON object of existing NotificationConfig keys.
It is injected as a runtime secret by the control plane, never a public value.
"""
import json
import os

INTEGRATION_KEYS = frozenset((
    "mailjet_api_key", "mailjet_secret_key", "mailjet_sender_email",
    "storage_enabled", "storage_provider", "storage_region", "storage_endpoint_url",
    "storage_bucket", "storage_access_key_id", "storage_secret_access_key",
    "storage_path_prefix", "storage_public_base_url", "storage_make_public",
    "storage_force_path_style", "storage_signed_url_ttl_seconds",
    "storage_max_upload_size_mb", "storage_allowed_formats",
))


def managed_integration_value(key):
    """Return (configured, value); leave standalone database behavior intact."""
    if os.environ.get("GTT_DEPLOYMENT_MODE", "standalone").strip().lower() != "managed":
        return False, None
    if key not in INTEGRATION_KEYS:
        return False, None
    raw = os.environ.get("GTT_MANAGED_INTEGRATIONS", "")
    if not raw:
        return False, None
    try:
        values = json.loads(raw)
    except (TypeError, ValueError):
        raise RuntimeError("Managed integration configuration is invalid") from None
    if not isinstance(values, dict) or any(k not in INTEGRATION_KEYS or not isinstance(v, str) for k, v in values.items()):
        raise RuntimeError("Managed integration configuration is invalid")
    return (True, values[key]) if key in values else (False, None)
