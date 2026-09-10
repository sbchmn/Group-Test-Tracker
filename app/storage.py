import io
import os
from datetime import datetime
from uuid import uuid4

from flask import current_app

from .models import NotificationConfig


class StorageConfigurationError(RuntimeError):
    """Raised when upload storage is disabled or not configured."""


class StorageUploadError(RuntimeError):
    """Raised when an upload fails validation or transport."""


_DEFAULT_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "PDF"}
_IMAGE_FORMAT_META = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
    "GIF": ("gif", "image/gif"),
}
_RESULT_FORMAT_META = {
    **_IMAGE_FORMAT_META,
    "PDF": ("pdf", "application/pdf"),
}


def _get_config_value(key, default=None):
    item = NotificationConfig.query.filter_by(key=key).first()
    if item is None:
        return default
    return item.value if item.value is not None else default


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_storage_settings():
    provider = str(_get_config_value("storage_provider", "aws") or "aws").strip().lower()
    region = str(_get_config_value("storage_region", "") or "").strip()
    endpoint_url = str(_get_config_value("storage_endpoint_url", "") or "").strip()
    bucket = str(_get_config_value("storage_bucket", "") or "").strip()
    access_key_id = str(_get_config_value("storage_access_key_id", "") or "").strip()
    secret_access_key = str(_get_config_value("storage_secret_access_key", "") or "").strip()
    path_prefix = str(_get_config_value("storage_path_prefix", "result-images") or "result-images").strip().strip("/")
    public_base_url = str(_get_config_value("storage_public_base_url", "") or "").strip().rstrip("/")
    make_public = _as_bool(_get_config_value("storage_make_public", "false"), default=False)
    force_path_style = _as_bool(_get_config_value("storage_force_path_style", "false"), default=False)
    enabled = _as_bool(_get_config_value("storage_enabled", "false"), default=False)

    signed_ttl_raw = _get_config_value("storage_signed_url_ttl_seconds", "60")
    try:
        signed_ttl_seconds = int(signed_ttl_raw)
    except (TypeError, ValueError):
        signed_ttl_seconds = 60
    signed_ttl_seconds = min(max(signed_ttl_seconds, 15), 900)

    max_upload_mb_raw = _get_config_value("storage_max_upload_size_mb", "8")
    try:
        max_upload_mb = float(max_upload_mb_raw)
    except (TypeError, ValueError):
        max_upload_mb = 8.0
    max_upload_mb = min(max(max_upload_mb, 1.0), 50.0)

    allowed_formats_raw = str(_get_config_value("storage_allowed_formats", "JPEG,PNG,WEBP,GIF,PDF") or "")
    allowed_formats = {
        token.strip().upper()
        for token in allowed_formats_raw.split(",")
        if token.strip()
    }
    if not allowed_formats:
        allowed_formats = set(_DEFAULT_ALLOWED_FORMATS)
    elif "PDF" not in allowed_formats:
        # Backward compatibility: legacy deployments may still have image-only
        # allowed formats saved before PDF support was introduced.
        allowed_formats.add("PDF")

    if provider not in {"aws", "do"}:
        provider = "aws"

    if provider == "do" and not endpoint_url and region:
        endpoint_url = f"https://{region}.digitaloceanspaces.com"

    return {
        "enabled": enabled,
        "provider": provider,
        "region": region,
        "endpoint_url": endpoint_url,
        "bucket": bucket,
        "access_key_id": access_key_id,
        "secret_access_key": secret_access_key,
        "path_prefix": path_prefix,
        "public_base_url": public_base_url,
        "make_public": make_public,
        "force_path_style": force_path_style,
        "signed_ttl_seconds": signed_ttl_seconds,
        "max_upload_size_mb": max_upload_mb,
        "allowed_formats": allowed_formats,
    }


def storage_is_ready():
    settings = get_storage_settings()
    return bool(
        settings["enabled"]
        and settings["bucket"]
        and settings["access_key_id"]
        and settings["secret_access_key"]
    )


def _build_client(settings):
    try:
        import boto3
        from botocore.client import Config
    except Exception as exc:
        raise StorageConfigurationError('Object storage libraries are not installed. Run pip install -r requirements.txt.') from exc

    return boto3.client(
        "s3",
        region_name=settings["region"] or None,
        endpoint_url=settings["endpoint_url"] or None,
        aws_access_key_id=settings["access_key_id"],
        aws_secret_access_key=settings["secret_access_key"],
        config=Config(s3={"addressing_style": "path" if settings["force_path_style"] else "virtual"}),
    )


def _assert_configured(settings):
    if not settings["enabled"]:
        raise StorageConfigurationError("Result image uploads are currently disabled.")

    missing = []
    if not settings["bucket"]:
        missing.append("bucket")
    if not settings["access_key_id"]:
        missing.append("access key id")
    if not settings["secret_access_key"]:
        missing.append("secret access key")

    if missing:
        missing_text = ", ".join(missing)
        raise StorageConfigurationError(f"Storage is not fully configured: missing {missing_text}.")


def _validate_and_prepare_result_file(file_storage, settings):
    payload = file_storage.read() if file_storage else b""
    if not payload:
        raise StorageUploadError("No file data was received.")

    max_bytes = int(settings["max_upload_size_mb"] * 1024 * 1024)
    if len(payload) > max_bytes:
        raise StorageUploadError(f"File exceeds the configured upload limit ({settings['max_upload_size_mb']:.0f} MB).")

    filename = (getattr(file_storage, "filename", "") or "").strip().lower()
    is_pdf_upload = filename.endswith(".pdf") or payload.startswith(b"%PDF-")
    if is_pdf_upload:
        if not payload.startswith(b"%PDF-"):
            raise StorageUploadError("Uploaded PDF is invalid.")
        if "PDF" not in settings["allowed_formats"]:
            allowed = ", ".join(sorted(settings["allowed_formats"]))
            raise StorageUploadError(f"File format PDF is not allowed. Allowed formats: {allowed}.")
        ext, content_type = _RESULT_FORMAT_META["PDF"]
        return payload, ext, content_type

    try:
        from PIL import Image, UnidentifiedImageError
    except Exception as exc:
        raise StorageConfigurationError('Image processing library is not installed. Run pip install -r requirements.txt.') from exc

    try:
        with Image.open(io.BytesIO(payload)) as img:
            image_format = (img.format or "").upper()
            width, height = img.size
    except UnidentifiedImageError as exc:
        raise StorageUploadError("Uploaded file is not a supported image or PDF.") from exc
    except Exception as exc:
        raise StorageUploadError("Unable to process the uploaded image.") from exc

    if image_format not in _IMAGE_FORMAT_META:
        raise StorageUploadError("Unsupported image type. Allowed: JPEG, PNG, WEBP, GIF.")
    if image_format not in settings["allowed_formats"]:
        allowed = ", ".join(sorted(settings["allowed_formats"]))
        raise StorageUploadError(f"Image format {image_format} is not allowed. Allowed formats: {allowed}.")

    if width <= 0 or height <= 0 or width * height > 50_000_000:
        raise StorageUploadError("Image dimensions are invalid or too large.")

    ext, content_type = _RESULT_FORMAT_META[image_format]
    return payload, ext, content_type


def _build_object_key(settings, category, ext):
    safe_category = (category or "misc").strip().lower().replace(" ", "-")
    safe_category = "".join(ch for ch in safe_category if ch.isalnum() or ch in {"-", "_"}) or "misc"
    date_path = datetime.utcnow().strftime("%Y/%m/%d")
    token = uuid4().hex
    prefix = settings["path_prefix"].strip("/")
    return f"{prefix}/{safe_category}/{date_path}/{token}.{ext}" if prefix else f"{safe_category}/{date_path}/{token}.{ext}"


def upload_result_image(file_storage, category):
    settings = get_storage_settings()
    _assert_configured(settings)

    payload, ext, content_type = _validate_and_prepare_result_file(file_storage, settings)
    object_key = _build_object_key(settings, category, ext)

    client = _build_client(settings)
    put_kwargs = {
        "Bucket": settings["bucket"],
        "Key": object_key,
        "Body": payload,
        "ContentType": content_type,
        "CacheControl": "public, max-age=31536000",
    }
    if settings["make_public"]:
        put_kwargs["ACL"] = "public-read"

    try:
        client.put_object(**put_kwargs)
    except Exception as exc:
        current_app.logger.exception("Failed uploading result image to object storage")
        raise StorageUploadError("Image upload failed. Check storage credentials and bucket policy.") from exc

    return object_key


def upload_telegram_animation(file_storage, category):
    """Upload a Telegram "animation" attachment (GIF, sent as GIF or as a
    soundless MP4 loop) without routing it through PIL's still-image
    validation, which rejects MP4 payloads.
    """
    settings = get_storage_settings()
    _assert_configured(settings)

    payload = file_storage.read() if file_storage else b""
    if not payload:
        raise StorageUploadError("No file data was received.")

    max_bytes = int(settings["max_upload_size_mb"] * 1024 * 1024)
    if len(payload) > max_bytes:
        raise StorageUploadError(f"File exceeds the configured upload limit ({settings['max_upload_size_mb']:.0f} MB).")

    if payload.startswith(b"GIF87a") or payload.startswith(b"GIF89a"):
        ext, content_type = "gif", "image/gif"
    elif payload[4:8] == b"ftyp":
        ext, content_type = "mp4", "video/mp4"
    else:
        raise StorageUploadError("Uploaded animation is not a supported GIF or video format.")

    object_key = _build_object_key(settings, category, ext)

    client = _build_client(settings)
    put_kwargs = {
        "Bucket": settings["bucket"],
        "Key": object_key,
        "Body": payload,
        "ContentType": content_type,
        "CacheControl": "public, max-age=31536000",
    }
    if settings["make_public"]:
        put_kwargs["ACL"] = "public-read"

    try:
        client.put_object(**put_kwargs)
    except Exception as exc:
        current_app.logger.exception("Failed uploading animation to object storage")
        raise StorageUploadError("Animation upload failed. Check storage credentials and bucket policy.") from exc

    return object_key


def generate_result_image_presigned_url(object_key, expires_in=None):
    if not object_key:
        raise StorageConfigurationError("No result image is available.")

    settings = get_storage_settings()
    _assert_configured(settings)
    client = _build_client(settings)

    ttl_seconds = expires_in or settings.get("signed_ttl_seconds") or 60
    ttl_seconds = min(max(int(ttl_seconds), 15), 900)

    try:
        return client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": settings["bucket"], "Key": object_key},
            ExpiresIn=ttl_seconds,
        )
    except Exception as exc:
        current_app.logger.exception("Failed generating presigned result image URL")
        raise StorageUploadError("Unable to generate secure image URL.") from exc


def delete_result_image(object_key):
    if not object_key:
        return False

    settings = get_storage_settings()
    if not storage_is_ready():
        return False

    client = _build_client(settings)
    try:
        client.delete_object(Bucket=settings["bucket"], Key=object_key)
        return True
    except Exception:
        current_app.logger.exception("Failed deleting result image from object storage")
        return False
