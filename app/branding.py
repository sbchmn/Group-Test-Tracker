"""Published customer identity shared by pages and notification workers."""
import html
import io
import re
import uuid

from flask import current_app, g, has_app_context, has_request_context, request, url_for
from flask_login import current_user
from sqlalchemy.exc import OperationalError, ProgrammingError

from . import db
from .models import BrandingAsset, BrandingState
from .version import APP_NAME

FONTS = {
    'system': ('System Sans', 'system-ui, -apple-system, "Segoe UI", sans-serif'),
    'figtree': ('Figtree', '"GTM Figtree", system-ui, sans-serif'),
    'lora': ('Lora', '"GTM Lora", Georgia, serif'),
}
DEFAULTS = {
    'enabled': False, 'name': APP_NAME, 'short_name': '',
    'tagline': 'Replaces manual spreadsheets',
    'intro': 'Professional web tool to manage group lab testing for purity, mass, endotoxin, sterility, and more.',
    'font': 'system', 'default_theme': 'light',
    'light_accent': '#0d6efd', 'light_nav': '#212529', 'light_surface': '#ffffff',
    'dark_accent': '#6ea8fe', 'dark_nav': '#16191d', 'dark_surface': '#212529',
    'logo': '', 'dark_logo': '', 'favicon': '',
    'support_email': '', 'user_help_url': '', 'admin_help_url': '',
    'operator_name': '', 'legal_email': '', 'mailing_address': '',
    'governing_law': '', 'effective_date': '',
}
TEXT_LIMITS = {'name': 80, 'short_name': 32, 'tagline': 160, 'intro': 600,
               'support_email': 120, 'user_help_url': 500, 'admin_help_url': 500,
               'operator_name': 160, 'legal_email': 120, 'mailing_address': 500,
               'governing_law': 160, 'effective_date': 80}
ASSET_KEYS = ('logo', 'dark_logo', 'favicon')
LEGAL_KEYS = {'operator_name': 'LEGAL_OPERATOR_NAME', 'legal_email': 'LEGAL_CONTACT_EMAIL',
              'mailing_address': 'LEGAL_MAILING_ADDRESS', 'governing_law': 'LEGAL_GOVERNING_LAW',
              'effective_date': 'LEGAL_EFFECTIVE_DATE'}


def get_state():
    return BrandingState.query.populate_existing().filter_by(id=1).first()


def published_settings():
    if not has_app_context():
        return dict(DEFAULTS)
    if has_request_context() and hasattr(g, 'branding_override'):
        return {**DEFAULTS, **g.branding_override}
    if has_request_context() and hasattr(g, 'branding_settings'):
        return g.branding_settings
    try:
        state = get_state()
        result = {**DEFAULTS, **(state.published if state else {})}
    except (OperationalError, ProgrammingError) as error:
        # Public health/legal pages also render before schema initialization in
        # tools/tests. Do not hide unrelated connection or SQL failures.
        message = str(error).lower()
        if 'branding_state' not in message or not any(token in message for token in ('no such table', 'does not exist', "doesn't exist", 'undefinedtable')):
            raise
        db.session.rollback()
        result = dict(DEFAULTS)
    if has_request_context():
        g.branding_settings = result
    return result


def effective_settings():
    saved = published_settings()
    if saved['enabled']:
        return saved
    return {**DEFAULTS, **{key: saved.get(key, '') for key in LEGAL_KEYS}}


def brand_name():
    return effective_settings()['name']


def brand_text(text):
    settings = effective_settings()
    if not settings['enabled']:
        return text
    return str(text).replace('Group Test Manager', settings['name']).replace('Group Test Tracker', settings['name'])


def bot_credit():
    return '\n\nPowered by GTM' if effective_settings()['enabled'] else ''


def template_variables():
    settings = effective_settings()
    return {'brand_name': settings['name'], 'brand_short_name': settings['short_name'] or settings['name'],
            'brand_tagline': settings['tagline'], 'brand_support_email': settings['support_email']}


def luminance(color):
    values = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    values = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in values]
    return sum(value * weight for value, weight in zip(values, (.2126, .7152, .0722)))


def contrast(first, second):
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + .05) / (low + .05)


def foreground(color):
    return '#ffffff' if contrast(color, '#ffffff') >= contrast(color, '#000000') else '#000000'


def hover_color(color):
    target = '#000000' if foreground(color) == '#ffffff' else '#ffffff'
    return '#' + ''.join(f'{round(int(color[i:i+2], 16) * .88 + int(target[i:i+2], 16) * .12):02x}' for i in (1, 3, 5))


def link_color(accent, surface, mode):
    target = '#111111' if mode == 'light' else '#ffffff'
    page_background = '#f8f9fa' if mode == 'light' else '#2b3035'
    for step in range(11):
        ratio = step / 10
        result = '#' + ''.join(f'{round(int(accent[i:i+2], 16) * (1-ratio) + int(target[i:i+2], 16) * ratio):02x}' for i in (1, 3, 5))
        if min(contrast(result, surface), contrast(result, page_background)) >= 4.5:
            return result
    return target


def validate_settings(settings):
    from email_validator import validate_email, EmailNotValidError
    from .links import safe_http_url
    clean = {**DEFAULTS, **{key: value for key, value in settings.items() if key in DEFAULTS}}
    errors = {}
    clean['enabled'] = clean['enabled'] is True
    for key, limit in TEXT_LIMITS.items():
        value = str(clean[key] or '').strip()
        clean[key] = value
        allowed_controls = '\n\r\t' if key in ('intro', 'mailing_address') else ''
        if len(value) > limit or any(ord(char) < 32 and char not in allowed_controls for char in value):
            errors[key] = f'Use at most {limit} characters without control characters.'
    if not clean['name']:
        errors['name'] = 'Enter an application name.'
    for key in ('support_email', 'legal_email'):
        if clean[key]:
            try:
                validate_email(clean[key], check_deliverability=False)
            except EmailNotValidError:
                errors[key] = 'Enter a valid email address.'
    for key in ('user_help_url', 'admin_help_url'):
        if clean[key] and (not safe_http_url(clean[key]) or not clean[key].startswith('https://')):
            errors[key] = 'Enter a complete HTTPS address.'
    if clean['font'] not in FONTS:
        errors['font'] = 'Choose one of the available fonts.'
    if clean['default_theme'] not in ('light', 'dark', 'system'):
        errors['default_theme'] = 'Choose light, dark, or device preference.'
    for mode in ('light', 'dark'):
        for part in ('accent', 'nav', 'surface'):
            key = mode + '_' + part
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(clean[key])):
                errors[key] = 'Enter a six-digit hex color, such as #0d6efd.'
            else:
                clean[key] = clean[key].lower()
        key = mode + '_surface'
        text = '#212529' if mode == 'light' else '#dee2e6'
        if key not in errors and contrast(clean[key], text) < 4.5:
            errors[key] = f'Choose a surface with readable {mode}-theme text (contrast at least 4.5:1).'
    for key in ASSET_KEYS:
        if clean[key] and (not isinstance(clean[key], str) or not re.fullmatch(r'[a-f0-9]{32}', clean[key]) or db.session.get(BrandingAsset, clean[key]) is None):
            errors[key] = 'Upload an available branding image.'
    return clean, errors


def create_asset(upload):
    from PIL import Image, ImageOps, UnidentifiedImageError
    data = upload.stream.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('Choose an image no larger than 2 MB.')
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ('PNG', 'JPEG', 'WEBP') or image.width * image.height > 16_000_000:
                raise ValueError('Use a PNG, JPEG, or WebP image of at most 16 megapixels.')
            if getattr(image, 'is_animated', False):
                raise ValueError('Choose a still image for branding.')
            image = ImageOps.exif_transpose(image).convert('RGBA')
            image.info.clear()
            image.thumbnail((1600, 800), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format='PNG')
            icon = ImageOps.contain(image, (32, 32), Image.Resampling.LANCZOS)
            canvas = Image.new('RGBA', (32, 32))
            canvas.paste(icon, ((32 - icon.width) // 2, (32 - icon.height) // 2))
            icon_output = io.BytesIO()
            canvas.save(icon_output, format='PNG')
            if len(output.getvalue()) > 4 * 1024 * 1024:
                raise ValueError('Choose a simpler or smaller image.')
            asset = BrandingAsset(id=uuid.uuid4().hex, data=output.getvalue(), icon_data=icon_output.getvalue(), width=image.width, height=image.height)
            db.session.add(asset)
            return asset
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError('Choose a valid PNG, JPEG, or WebP image.') from error


def asset_url(asset_id, icon=False, external=False):
    if not asset_id:
        return ''
    path = f'/branding/assets/{asset_id}/{"icon" if icon else "image"}.png'
    if not external:
        return url_for('branding.asset', asset_id=asset_id, variant='icon' if icon else 'image')
    if has_request_context() and getattr(g, 'branding_preview', False):
        return url_for('branding.asset', asset_id=asset_id, variant='icon' if icon else 'image', _external=True)
    from .saas import managed_public_url
    from .links import safe_http_url
    from .models import NotificationConfig
    config = NotificationConfig.query.filter_by(key='service_base_url').first()
    base = managed_public_url() or (config.value if config else '')
    return base.rstrip('/') + path if base and safe_http_url(base) else ''


def email_parts(body, settings=None):
    settings = effective_settings() if settings is None else settings
    if not settings['enabled']:
        return body, body
    name = html.escape(settings['name'])
    logo = asset_url(settings['logo'], external=True)
    logo_markup = f'<img src="{html.escape(logo, quote=True)}" alt="{name}" style="max-width:220px;max-height:80px" />' if logo else ''
    content = body if re.search(r'<[a-zA-Z][^>]*>', body or '') else html.escape(body or '').replace('\n', '<br>')
    markup = (f'<div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;color:#212529;background:#ffffff;padding:24px;overflow-wrap:anywhere;word-break:break-word;'
              f'border-top:4px solid {settings["light_accent"]}">{logo_markup}<h1 style="font-size:22px">{name}</h1>'
              f'{content}<hr><p style="font-size:12px;color:#595959">Powered by GTM</p></div>')
    return f'{settings["name"]}\n\n{body}\n\nPowered by GTM', markup


def context():
    settings = effective_settings()
    preference = getattr(current_user, 'theme_preference', 'site') if current_user.is_authenticated else request.cookies.get('gtm_theme', 'site')
    if preference not in ('site', 'light', 'dark', 'system'):
        preference = 'site'
    if has_request_context() and getattr(g, 'branding_preview', False):
        preference = getattr(g, 'branding_preview_theme', 'light')
    legal = {key: settings[key] or current_app.config.get(config, '') for key, config in LEGAL_KEYS.items()}
    return dict(
        branding=settings, branding_font=FONTS[settings['font']][1],
        branding_colors={mode: {part: settings[mode + '_' + part] for part in ('accent', 'nav', 'surface')} | {
            'accent_text': foreground(settings[mode + '_accent']), 'nav_text': foreground(settings[mode + '_nav']),
            'accent_hover': hover_color(settings[mode + '_accent']),
            'link': link_color(settings[mode + '_accent'], settings[mode + '_surface'], mode)
        } for mode in ('light', 'dark')},
        branding_theme_preference=preference,
        branding_preview=getattr(g, 'branding_preview', False),
        branding_preview_public=getattr(g, 'branding_preview_public', False),
        branding_asset_url=asset_url,
        brand_name=settings['name'],
        legal_operator_name=legal['operator_name'] or f'{settings["name"]} operator',
        legal_contact_email=legal['legal_email'], legal_mailing_address=legal['mailing_address'],
        legal_governing_law=legal['governing_law'], legal_effective_date=legal['effective_date'],
    )
