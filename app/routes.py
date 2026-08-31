"""
Main Blueprint - All Routes, Form Classes, and Business Logic
- Strict visibility enforcement per requirements.
- Cost calculations delegated to model (single source of truth, tested).
- Admin-only routes protected with helper decorator.
- Clean separation: forms defined here, templates consume them.
- All POSTs use CSRF (via Flask-WTF).
"""

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify, send_file, current_app
)
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, BooleanField, TextAreaField, 
    FloatField, DateField, SelectField, SelectMultipleField, SubmitField, FieldList, FormField
)
from wtforms.validators import DataRequired, Email, Length, Optional, NumberRange, EqualTo, URL
from datetime import datetime, date
from datetime import timedelta
from functools import wraps
from itertools import zip_longest
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
import secrets
import ipaddress
import html

from . import db, csrf
import os
import json

from .models import (
    User,
    GroupTest,
    Participation,
    NotificationTemplate,
    NotificationConfig,
    Tag,
    PublicResult,
    DashboardHiddenGroupTest,
    TelegramLinkToken,
    TelegramWebhookUpdate,
    TelegramStatusDigestEvent,
    UserDigestEvent,
    PaymentOption,
)
from .export import generate_test_export
from .notifications import (
    append_notification_log,
    read_notification_log,
    send_password_reset,
    send_group_test_notification,
    render_notification_template,
    send_notification_message,
    send_telegram_status_channel_message,
    send_telegram_chat_message,
    register_telegram_webhook,
    unregister_telegram_webhook,
)
from .storage import (
    StorageConfigurationError,
    StorageUploadError,
    delete_result_image,
    generate_result_image_presigned_url,
    get_storage_settings,
    upload_result_image,
)

main_bp = Blueprint('main', __name__)


# ==================== FORMS ====================

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember me')
    submit = SubmitField('Login')


class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    tg_username = StringField('Telegram Username (optional)', validators=[Optional(), Length(max=80)])
    submit = SubmitField('Register')


class GroupTestForm(FlaskForm):
    """Admin form for creating/editing a group test. Matches original spreadsheet closely."""
    title = StringField('Test Title', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Description / Notes', validators=[Optional()])
    start_date = DateField('Start Date', validators=[Optional()], default=date.today)
    
    vendor = StringField('Vendor', validators=[Optional(), Length(max=120)])
    batch_number = StringField('Batch Number', validators=[Optional(), Length(max=100)])
    compound = StringField('Compound', validators=[Optional(), Length(max=100)])
    size = StringField('Size / Vial Spec', validators=[Optional(), Length(max=50)])
    
    status = SelectField('Status', choices=[
        ('recruiting', 'Recruiting (Open for new requests)'),
        ('ready_for_payment', 'Ready for Payment (Collecting participant payments)'),
        ('testing', 'Testing (No new joins, visible to approved members)'),
        ('closed', 'Closed (Results link visible to approved members)')
    ], validators=[DataRequired()])
    
    lab_name = StringField('Lab / Provider', validators=[Optional(), Length(max=200)])
    total_lab_cost = FloatField('Total Lab Cost ($)', validators=[Optional(), NumberRange(min=0)], default=0.0)
    shipping_cost = FloatField('Shipping to Lab ($)', validators=[Optional(), NumberRange(min=0)], default=0.0)
    donor_shipping_cost = FloatField('Donor Shipping Cost ($)', validators=[Optional(), NumberRange(min=0)], default=0.0)
    donor_shipping_reimbursement = SelectField('Donor Shipping Reimbursement', choices=[
        ('credit', 'Credit to the donor'),
        ('participant', 'Covered by selected participant')
    ], default='credit', validators=[Optional()])
    donor_shipping_reimbursed_by_id = SelectField('Who covers it?', coerce=int, validators=[Optional()], choices=[])
    refund_per_donor = FloatField('Refund per Donor ($)', validators=[Optional(), NumberRange(min=0)], default=20.0)
    
    order_number = StringField('Order Number', validators=[Optional()])
    quote_number = StringField('Quote Number', validators=[Optional()])
    
    # results_link only relevant when closed; shown in template conditionally
    results_link = StringField('Results Link (URL - shown only to approved members when Closed)', 
                               validators=[Optional(), Length(max=500)])
    tag_names = StringField('Tags (comma-separated)', validators=[Optional(), Length(max=500)])
    payment_option_ids = SelectMultipleField('Available Payment Options', coerce=int, choices=[], validators=[Optional()])
    
    submit = SubmitField('Save Group Test')


class PublicResultForm(FlaskForm):
    title = StringField('Result Title', validators=[DataRequired(), Length(max=200)])
    summary = TextAreaField('Summary / Notes', validators=[Optional()])
    results_link = StringField('Results Link', validators=[DataRequired(), Length(max=500)])
    tag_names = StringField('Tags (comma-separated)', validators=[Optional(), Length(max=500)])
    submit = SubmitField('Save Public Result')


class ParticipationRequestForm(FlaskForm):
    """User-facing form to request joining a recruiting test."""
    name = StringField('Full Name', validators=[DataRequired(), Length(max=120)])
    tg_username = StringField('Telegram Username', validators=[Optional(), Length(max=80)])
    us_based = BooleanField('US Based?', default=True)
    state = StringField('State (if US)', validators=[Optional(), Length(max=50)])
    vial_donor = BooleanField('I can donate vial(s) for testing (recommended for lower cost)', default=False)
    notes = TextAreaField('Notes / Special Requests', validators=[Optional()])
    submit = SubmitField('Submit Participation Request')


class ParticipationEditForm(FlaskForm):
    """Admin form to update a participant's details and payment status."""
    name = StringField('Name', validators=[Optional()])
    tg_username = StringField('TG Username', validators=[Optional()])
    approved = BooleanField('Approved')
    verified = BooleanField('Identity Verified')
    active = BooleanField('Active', default=True)
    order_status = SelectField('Order Status', choices=[
        ('pending', 'Pending'), ('ordered', 'Ordered'), ('shipped', 'Shipped to Lab'),
        ('received', 'Received at Lab'), ('complete', 'Complete')
    ])
    us_based = BooleanField('US Based')
    vial_donor = BooleanField('Vial Donor')
    state = StringField('State')
    pay_vial_collector = BooleanField('Pays Vial Collector')
    pay_lab = BooleanField('Pays Lab Fees')
    paid_lab = BooleanField('Lab Fees Paid?')
    amount_paid = FloatField('Amount Paid ($)', validators=[Optional(), NumberRange(min=0)])
    notes = TextAreaField('Admin Notes')
    submit = SubmitField('Update Participant')


class AddParticipantForm(FlaskForm):
    user_id = SelectField('Select User', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Add to Test (Auto-Approved)')


class ParticipantStatusForm(FlaskForm):
    """Form for participants to update their own status (aligned with admin form)."""
    order_status = SelectField('Order Status', choices=[
        ('pending', 'Not Ordered Yet'),
        ('ordered_from_vendor', 'Ordered from Vendor'),
        ('received_from_vendor', 'Received from Vendor'),
        ('ready_to_ship', 'Ready to Ship to Lab')
    ])
    paid_lab = BooleanField('I have paid my lab fees')
    amount_paid = FloatField('Amount I have paid ($)', validators=[Optional(), NumberRange(min=0)])
    preferred_payment_option_id = SelectField('Preferred Payment Method', coerce=int, validators=[Optional()])
    notes = TextAreaField('Notes / Comments', validators=[Optional()])
    submit = SubmitField('Update My Status')


class UserForm(FlaskForm):
    """Form for admins to create/edit users."""
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    tg_username = StringField('Telegram Username', validators=[Optional(), Length(max=80)])
    is_admin = BooleanField('Administrator')
    is_active = BooleanField('Active', default=True)
    receive_group_test_notifications = BooleanField('Receive Group Test Notifications?', default=True)
    notification_channel = SelectField('Notify via', choices=[('email', 'Email'), ('telegram', 'Telegram')], default='email')
    digest_frequency = SelectField('Digest Email Frequency', choices=[('off', 'Off'), ('hourly', 'Hourly'), ('daily', 'Daily')], default='off')
    digest_hourly_minute_utc = FloatField('Digest Minute (UTC, hourly mode)', validators=[Optional(), NumberRange(min=0, max=59)], default=0)
    digest_daily_hour_utc = FloatField('Digest Hour (UTC, daily mode)', validators=[Optional(), NumberRange(min=0, max=23)], default=9)
    password = PasswordField('New Password (leave blank to keep current)', validators=[Optional(), Length(min=6)])
    submit = SubmitField('Save User')


class ProfileForm(FlaskForm):
    """Form for users to edit their own profile details."""
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    tg_username = StringField('Telegram Username', validators=[Optional(), Length(max=80)])
    receive_group_test_notifications = BooleanField('Receive Group Test Notifications?', default=True)
    notification_channel = SelectField('Notify via', choices=[('email', 'Email'), ('telegram', 'Telegram')], default='email')
    digest_frequency = SelectField('Digest Email Frequency', choices=[('off', 'Off'), ('hourly', 'Hourly'), ('daily', 'Daily')], default='off')
    digest_hourly_minute_utc = FloatField('Digest Minute (UTC, hourly mode)', validators=[Optional(), NumberRange(min=0, max=59)], default=0)
    digest_daily_hour_utc = FloatField('Digest Hour (UTC, daily mode)', validators=[Optional(), NumberRange(min=0, max=23)], default=9)
    password = PasswordField('New Password (leave blank to keep current)', validators=[Optional(), Length(min=6)])
    submit = SubmitField('Save Profile')


class NotificationTemplateForm(FlaskForm):
    name = StringField('Template Name', validators=[DataRequired(), Length(max=120)])
    description = TextAreaField('Description', validators=[Optional()])
    email_subject = StringField('Email Subject', validators=[Optional(), Length(max=200)])
    email_body = TextAreaField('Email Message (HTML)', validators=[Optional()])
    telegram_body = TextAreaField('Telegram Message', validators=[Optional()])
    hide_from_participant_notifications = BooleanField('Hide from "Notify Test Participants"')
    is_default_password_reset = BooleanField('Default Password Reset Template')
    is_default_registration_welcome = BooleanField('Default Registration Welcome Template')
    is_active = BooleanField('Active', default=True)
    submit = SubmitField('Save Template')


class NotificationConfigForm(FlaskForm):
    mailjet_api_key = StringField('Mailjet API Key', validators=[Optional()])
    mailjet_secret_key = StringField('Mailjet Secret Key', validators=[Optional()])
    mailjet_sender_email = StringField('Mailjet Sender Email', validators=[Optional(), Email()])
    telegram_bot_token = StringField('Telegram Bot Token', validators=[Optional()])
    telegram_bot_username = StringField('Telegram Bot Username', validators=[Optional(), Length(max=80)])
    telegram_webhook_url = StringField('Telegram Webhook URL (optional override)', validators=[Optional(), URL(require_tld=False), Length(max=500)])
    telegram_webhook_secret = PasswordField('Telegram Webhook Secret', validators=[Optional(), Length(max=200)])
    telegram_webhook_allowed_ips = StringField('Telegram Webhook Allowed IPs (comma-separated CIDRs)', validators=[Optional(), Length(max=500)])
    telegram_status_chat_id = StringField('Telegram Status Chat / Channel ID', validators=[Optional(), Length(max=120)])
    telegram_digest_enabled = BooleanField('Enable Telegram Digest Mode')
    telegram_digest_window_minutes = FloatField('Telegram Digest Window (minutes)', validators=[Optional(), NumberRange(min=1, max=120)], default=10)
    telegram_status_digest_header_template = TextAreaField('Telegram Status Digest Header Template', validators=[Optional(), Length(max=2000)])
    telegram_status_digest_line_template = TextAreaField('Telegram Status Digest Line Template', validators=[Optional(), Length(max=2000)])
    telegram_status_digest_participants_template = TextAreaField('Telegram Status Digest Participants Template', validators=[Optional(), Length(max=2000)])
    telegram_status_new_test_template = TextAreaField('Telegram New Test Message Template', validators=[Optional(), Length(max=2000)])
    telegram_status_user_no_request_template = TextAreaField('Telegram /status No Request Template', validators=[Optional(), Length(max=2000)])
    telegram_status_user_denied_template = TextAreaField('Telegram /status Denied Template', validators=[Optional(), Length(max=2000)])
    telegram_status_user_approved_template = TextAreaField('Telegram /status Approved Template', validators=[Optional(), Length(max=2000)])
    telegram_status_user_pending_template = TextAreaField('Telegram /status Pending Template', validators=[Optional(), Length(max=2000)])
    service_base_url = StringField('Service Base URL', validators=[Optional(), URL(require_tld=False)])
    notification_debug_enabled = BooleanField('Enable debug-level notification logs')
    submit = SubmitField('Save Configuration')


class StorageConfigForm(FlaskForm):
    storage_enabled = BooleanField('Enable object storage result file uploads')
    storage_provider = SelectField('Provider', choices=[('aws', 'AWS S3'), ('do', 'DigitalOcean Spaces')], validators=[DataRequired()])
    storage_bucket = StringField('Bucket / Space Name', validators=[Optional(), Length(max=120)])
    storage_region = StringField('Region', validators=[Optional(), Length(max=80)])
    storage_endpoint_url = StringField('Endpoint URL (optional)', validators=[Optional(), URL(require_tld=False)])
    storage_access_key_id = StringField('Access Key ID', validators=[Optional(), Length(max=200)])
    storage_secret_access_key = PasswordField('Secret Access Key', validators=[Optional(), Length(max=200)])
    storage_path_prefix = StringField('Object Path Prefix', validators=[Optional(), Length(max=120)])
    storage_public_base_url = StringField('Public Base URL (optional)', validators=[Optional(), URL(require_tld=False)])
    storage_make_public = BooleanField('Upload with public-read ACL')
    storage_force_path_style = BooleanField('Force path-style S3 addressing')
    storage_signed_url_ttl_seconds = FloatField('Signed URL TTL (seconds)', validators=[Optional(), NumberRange(min=15, max=900)], default=60)
    storage_max_upload_size_mb = FloatField('Max Upload Size (MB)', validators=[Optional(), NumberRange(min=1, max=50)])
    storage_allowed_formats = StringField('Allowed Formats (comma-separated)', validators=[Optional(), Length(max=200)])
    submit = SubmitField('Save Storage Configuration')


class PaymentOptionForm(FlaskForm):
    label = StringField('Display Label', validators=[DataRequired(), Length(max=120)])
    method_type = SelectField(
        'Method Type',
        choices=[
            ('venmo', 'Venmo'),
            ('cashapp', 'Cash App'),
            ('paypal', 'PayPal'),
            ('crypto', 'Crypto Wallet'),
            ('other', 'Other'),
        ],
        validators=[DataRequired()],
    )
    recipient_name = StringField('Recipient Name', validators=[Optional(), Length(max=120)])
    account_handle = StringField('App Handle / Username', validators=[Optional(), Length(max=200)])
    wallet_address = StringField('Wallet Address', validators=[Optional(), Length(max=255)])
    network = StringField('Network / Chain', validators=[Optional(), Length(max=120)])
    details = TextAreaField('Details / Notes', validators=[Optional()])
    qr_payload_override = StringField('QR Payload Override', validators=[Optional(), Length(max=500)])
    is_active = BooleanField('Active', default=True)
    submit = SubmitField('Save Payment Option')


class PasswordResetForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    notification_channel = SelectField('Notify via', choices=[('email', 'Email'), ('telegram', 'Telegram')], default='email')
    submit = SubmitField('Send Reset')


class NotifyParticipantsForm(FlaskForm):
    template_id = SelectField('Notification Template', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Send Notifications')


# ==================== DECORATORS ====================

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# ==================== ROUTES ====================


def populate_donor_shipping_choices(form):
    users = User.query.order_by(User.username).all()
    choices = [(0, 'Select a participant')]
    choices.extend([(user.id, user.username) for user in users])
    form.donor_shipping_reimbursed_by_id.choices = choices


def populate_payment_option_choices(form, include_ids=None):
    include_ids = include_ids or []
    active_options = PaymentOption.query.filter_by(is_active=True).order_by(PaymentOption.label, PaymentOption.recipient_name).all()
    options = list(active_options)
    if include_ids:
        existing = {option.id for option in active_options}
        extra_options = PaymentOption.query.filter(PaymentOption.id.in_(include_ids)).all()
        for option in extra_options:
            if option.id not in existing:
                options.append(option)
    options.sort(key=lambda option: ((option.label or '').lower(), (option.recipient_name or '').lower()))
    form.payment_option_ids.choices = [
        (option.id, option.display_title() + ('' if option.is_active else ' [inactive]'))
        for option in options
    ]


def _serialize_payment_option_snapshot(option):
    if option is None:
        return ''

    parts = [option.display_title()]
    if option.account_handle:
        parts.append(f"Handle: {option.account_handle}")
    if option.wallet_address:
        parts.append(f"Wallet: {option.wallet_address}")
    if option.network:
        parts.append(f"Network: {option.network}")
    return ' | '.join(parts)


def _result_file_kind(result_key):
    value = (result_key or '').strip().lower()
    if value.endswith('.pdf'):
        return 'pdf'
    return 'image'


def _build_payment_option_context(option):
    if option is None:
        return None

    profile = option.to_payment_profile()
    return {
        'id': option.id,
        'label': option.label,
        'title': option.display_title(),
        'method_type': option.method_type,
        'is_active': bool(option.is_active),
        'provider_name': profile.get('provider_name') or option.method_type,
        'icon_class': profile.get('icon_class') or 'bi bi-credit-card-2-front',
        'badge_class': profile.get('badge_class') or 'text-bg-secondary',
        'recipient_name': option.recipient_name,
        'account_handle': option.account_handle,
        'wallet_address': option.wallet_address,
        'network': option.network,
        'details': option.details,
        'destination_label': profile.get('destination_label') or 'Destination',
        'destination_value': profile.get('destination_value') or '',
        'payment_link': profile.get('payment_link') or '',
        'qr_payload': profile.get('qr_payload') or '',
    }


def _payment_method_matrix_rows():
    return [
        {
            'method_type': 'venmo',
            'provider_name': 'Venmo',
            'input_field': 'account_handle',
            'input_example': '@sampleuser',
            'destination_example': '@sampleuser',
            'link_example': 'https://venmo.com/sampleuser',
        },
        {
            'method_type': 'cashapp',
            'provider_name': 'Cash App',
            'input_field': 'account_handle',
            'input_example': '$sampleuser',
            'destination_example': '$sampleuser',
            'link_example': 'https://cash.app/$sampleuser',
        },
        {
            'method_type': 'paypal',
            'provider_name': 'PayPal',
            'input_field': 'account_handle',
            'input_example': 'sampleuser',
            'destination_example': 'sampleuser',
            'link_example': 'https://paypal.me/sampleuser',
        },
        {
            'method_type': 'crypto',
            'provider_name': 'Crypto Wallet',
            'input_field': 'wallet_address + network',
            'input_example': '0xabc... + ETH',
            'destination_example': 'wallet address',
            'link_example': 'ethereum:0xabc...',
        },
        {
            'method_type': 'other',
            'provider_name': 'Other',
            'input_field': 'account_handle or wallet_address',
            'input_example': 'https://pay.example.com/u/demo',
            'destination_example': 'destination value',
            'link_example': 'uses direct URL when provided',
        },
    ]


def _validate_payment_option_input(method_type, account_handle, wallet_address, qr_payload_override):
    method = str(method_type or '').strip().lower()
    handle = str(account_handle or '').strip()
    wallet = str(wallet_address or '').strip()
    override = str(qr_payload_override or '').strip()

    if override:
        return []

    if method in {'venmo', 'cashapp', 'paypal'} and not handle:
        return ['This method requires an app handle/username unless QR Payload Override is provided.']
    if method == 'crypto' and not wallet:
        return ['Crypto method requires a wallet address unless QR Payload Override is provided.']
    if method == 'other' and not (handle or wallet):
        return ['Other method requires a destination value unless QR Payload Override is provided.']
    return []


def _build_telegram_deep_link(token_value):
    bot_username = str(_config_values_map().get('telegram_bot_username') or '').strip().lstrip('@')
    if not bot_username or not token_value:
        return None
    return f"https://t.me/{bot_username}?start={token_value}"


def _resolve_telegram_webhook_url(config_map):
    explicit_url = str(config_map.get('telegram_webhook_url') or '').strip()
    if explicit_url:
        if explicit_url.endswith('/telegram/webhook'):
            return explicit_url
        return f"{explicit_url.rstrip('/')}{url_for('main.telegram_webhook')}"

    service_base = str(config_map.get('service_base_url') or '').strip()
    if service_base:
        return f"{service_base.rstrip('/')}{url_for('main.telegram_webhook')}"
    return f"{request.host_url.rstrip('/')}{url_for('main.telegram_webhook')}"


def _issue_telegram_link_token(user):
    if user is None:
        return None

    token_value = secrets.token_urlsafe(24)
    token = TelegramLinkToken(
        user_id=user.id,
        token=token_value,
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    db.session.add(token)
    return token


def _is_telegram_webhook_ip_allowed(source_ip, config_map):
    allowed = str(config_map.get('telegram_webhook_allowed_ips') or '').strip()
    if not allowed:
        return True

    if not source_ip:
        return False

    try:
        candidate_ip = ipaddress.ip_address(source_ip)
    except ValueError:
        return False

    for raw_entry in allowed.split(','):
        entry = raw_entry.strip()
        if not entry:
            continue
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if candidate_ip in network:
            return True
    return False


def _reserve_telegram_update(update_id, source_ip):
    if update_id is None:
        return True
    try:
        update_id = int(update_id)
    except (TypeError, ValueError):
        return False

    exists = TelegramWebhookUpdate.query.filter_by(update_id=update_id).first()
    if exists is not None:
        return False

    db.session.add(TelegramWebhookUpdate(update_id=update_id, source_ip=source_ip or None))
    try:
        db.session.flush()
    except IntegrityError:
        return False
    return True


def _send_status_update_to_telegram(test, previous_status):
    participants = test.participations.filter_by(approved=True, denied=False).all()
    for participant in participants:
        user = participant.user
        if user is None:
            continue
        if not user.receive_group_test_notifications:
            continue
        if (user.digest_frequency or 'off') not in {'hourly', 'daily'}:
            continue
        db.session.add(UserDigestEvent(
            user_id=user.id,
            test_id=test.id,
            test_title=test.title,
            old_status=previous_status,
            new_status=test.status,
        ))

    config_map = _config_values_map()
    target_chat = str(config_map.get('telegram_status_chat_id') or '').strip()
    if not target_chat:
        return

    mention_usernames = []
    mention_user_ids = []
    for participant in participants:
        if participant.user and participant.user.tg_username:
            username = participant.user.tg_username.strip().lstrip('@')
            if username:
                mention_usernames.append(username)
        if participant.user and participant.user.telegram_user_id:
            user_id = str(participant.user.telegram_user_id).strip()
            if user_id:
                mention_user_ids.append(user_id)

    digest_enabled = str(config_map.get('telegram_digest_enabled', 'false')).lower() == 'true'
    try:
        window_minutes = int(float(config_map.get('telegram_digest_window_minutes') or 10))
    except (TypeError, ValueError):
        window_minutes = 10
    window_minutes = max(1, min(window_minutes, 120))

    now = datetime.utcnow()
    bucket_seconds = window_minutes * 60
    bucket_index = int(now.timestamp() // bucket_seconds)
    window_bucket = f"{window_minutes}:{bucket_index}"
    event_key = f"{test.id}:{previous_status}:{test.status}"

    existing_event = TelegramStatusDigestEvent.query.filter_by(
        chat_id=target_chat,
        window_bucket=window_bucket,
        event_key=event_key,
    ).first()
    if existing_event is not None:
        append_notification_log(f"telegram: digest suppressed duplicate status update for test {test.id}")
        return

    event = TelegramStatusDigestEvent(
        chat_id=target_chat,
        window_bucket=window_bucket,
        event_key=event_key,
        test_id=test.id,
        test_title=test.title,
        old_status=previous_status,
        new_status=test.status,
        mention_usernames=','.join(sorted(set(mention_usernames))),
        mention_user_ids=','.join(sorted(set(mention_user_ids))),
    )
    try:
        with db.session.begin_nested():
            db.session.add(event)
            db.session.flush()
    except IntegrityError:
        # Another request inserted the same digest event in this window.
        append_notification_log(f"telegram: digest suppressed duplicate status update for test {test.id}")
        return

    pending_events = (
        TelegramStatusDigestEvent.query
        .filter_by(chat_id=target_chat, window_bucket=window_bucket, sent_at=None)
        .order_by(TelegramStatusDigestEvent.created_at.asc(), TelegramStatusDigestEvent.id.asc())
        .all()
    )
    if not pending_events:
        return

    if digest_enabled:
        should_send_digest = len(pending_events) > 1 or str(test.status or '').lower() == 'closed'
        if not should_send_digest:
            append_notification_log(f"telegram: digest queued event for test {test.id}", debug=True)
            return
    else:
        pending_events = [event]

    header_text = _render_telegram_status_template(
        config_map,
        'telegram_status_digest_header_template',
        'Group test status updates',
        {
            'test_id': test.id,
            'test_title': test.title,
            'old_status': previous_status,
            'old_status_label': _format_status_label(previous_status),
            'new_status': test.status,
            'new_status_label': _format_status_label(test.status),
            'new_status_phrase': _format_status_phrase(test.status),
        },
    )
    lines = [header_text, ""]
    mentioned_usernames = set()
    mentioned_user_ids = set()
    for item in pending_events:
        line_text = _render_telegram_status_template(
            config_map,
            'telegram_status_digest_line_template',
            '{{ test_title }} is now {{ new_status_phrase }}',
            {
                'test_id': item.test_id,
                'test_title': item.test_title,
                'old_status': item.old_status,
                'old_status_label': _format_status_label(item.old_status),
                'new_status': item.new_status,
                'new_status_label': _format_status_label(item.new_status),
                'new_status_phrase': _format_status_phrase(item.new_status),
            },
        )
        lines.append(f"- {line_text}")
        for username in (item.mention_usernames or '').split(','):
            username = username.strip().lstrip('@')
            if username:
                mentioned_usernames.add(username)
        for user_id in (item.mention_user_ids or '').split(','):
            user_id = user_id.strip()
            if user_id:
                mentioned_user_ids.add(user_id)

    mention_tokens = []
    for user_id in sorted(mentioned_user_ids):
        mention_tokens.append(f'<a href="tg://user?id={html.escape(user_id)}">user-{html.escape(user_id)}</a>')
    for username in sorted(mentioned_usernames):
        mention_tokens.append(f"@{username}")

    if mention_tokens:
        participants_line = _render_telegram_status_template(
            config_map,
            'telegram_status_digest_participants_template',
            'Participants: {{ mentions }}',
            {'mentions': ' '.join(mention_tokens)},
        )
        lines.extend(["", participants_line])

    digest_text = "\n".join(lines)
    sent = send_telegram_status_channel_message(digest_text, parse_mode='HTML')
    if sent:
        sent_at = datetime.utcnow()
        for item in pending_events:
            item.sent_at = sent_at
        db.session.add_all(pending_events)


def _send_new_test_created_to_telegram(test, test_url=None):
    config_map = _config_values_map()
    target_chat = str(config_map.get('telegram_status_chat_id') or '').strip()
    if not target_chat:
        return

    message_text = _render_telegram_status_template(
        config_map,
        'telegram_status_new_test_template',
        'New group test created\n\n- #{{ test_id }} {{ test_title }}\n- Status: {{ status_label }}\n- Link: {{ test_url }}',
        {
            'test_id': test.id,
            'test_title': test.title,
            'status': test.status or 'recruiting',
            'status_label': _format_status_label(test.status or 'recruiting'),
            'status_phrase': _format_status_phrase(test.status or 'recruiting'),
            'test_url': test_url or '',
        },
    )

    sent = send_telegram_status_channel_message(message_text)
    if not sent:
        append_notification_log(f'telegram: failed to send new test created message for test {test.id}')


def mask_secret(value, reveal_prefix=4, reveal_suffix=6):
    if not value:
        return ''
    value = str(value)
    if len(value) <= reveal_prefix + reveal_suffix:
        return value
    return f"{value[:reveal_prefix]}{'*' * (len(value) - reveal_prefix - reveal_suffix)}{value[-reveal_suffix:]}"


def _format_status_label(status_value):
    status_text = str(status_value or '').strip()
    if not status_text:
        return 'Unknown'
    return status_text.replace('_', ' ').title()


def _format_status_phrase(status_value):
    status_text = str(status_value or '').strip()
    if not status_text:
        return 'unknown'
    return status_text.replace('_', ' ').lower()


def _render_telegram_status_template(config_map, key, default_text, context):
    template_value = str(config_map.get(key) or '').strip()
    return render_notification_template(template_value or default_text, context)


def _clamp_int(value, default, low, high):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(low, min(high, parsed))


_STORAGE_CONFIG_KEYS = {
    'storage_enabled',
    'storage_provider',
    'storage_bucket',
    'storage_region',
    'storage_endpoint_url',
    'storage_access_key_id',
    'storage_secret_access_key',
    'storage_path_prefix',
    'storage_public_base_url',
    'storage_make_public',
    'storage_force_path_style',
    'storage_signed_url_ttl_seconds',
    'storage_max_upload_size_mb',
    'storage_allowed_formats',
}


def _config_values_map():
    return {cfg.key: cfg.value for cfg in NotificationConfig.query.all()}


def _save_config_value(key, value):
    config = NotificationConfig.query.filter_by(key=key).first() or NotificationConfig(key=key)
    config.value = value
    db.session.add(config)


def parse_tag_names(tag_text):
    if not tag_text:
        return []
    seen = set()
    tags = []
    for raw_tag in str(tag_text).replace('\n', ',').split(','):
        name = raw_tag.strip()
        if not name:
            continue
        normalized = name.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        tags.append(name)
    return tags


def get_or_create_tags(tag_text):
    tags = []
    for name in parse_tag_names(tag_text):
        normalized = name.lower()
        tag = Tag.query.filter_by(normalized_name=normalized).first()
        if tag is None:
            tag = Tag(name=name, normalized_name=normalized)
            db.session.add(tag)
            db.session.flush()
        tags.append(tag)
    return tags


def apply_tags_to_record(record, tag_text):
    record.set_tags(get_or_create_tags(tag_text))


def get_all_tag_names():
    return [tag.name for tag in Tag.query.order_by(Tag.name).all()]


def parse_item_results(names, results):
    items = []
    for item_name, result_text in zip_longest(names, results, fillvalue=''):
        item_name = (item_name or '').strip()
        result_text = (result_text or '').strip()
        if not item_name:
            continue
        item = {'name': item_name}
        if result_text:
            item['result'] = result_text
        items.append(item)
    return items


def get_group_test_sort_value(test, sort_by):
    if sort_by == 'title':
        return (test.title or '').lower()
    if sort_by == 'tags':
        return test.tag_names().lower()
    if sort_by == 'status':
        return (test.status or '').lower()
    return test.updated_at or datetime.min


def get_result_sort_value(result, sort_by):
    if sort_by == 'title':
        return (result['title'] or '').lower()
    if sort_by == 'tags':
        return result['tag_text'].lower()
    return result['posted_at'] or datetime.min


@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('index.html')  # Simple landing or redirect to login


@main_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash('Username already taken.', 'warning')
            return render_template('register.html', form=form)
        if User.query.filter_by(email=form.email.data).first():
            flash('Email already registered.', 'warning')
            return render_template('register.html', form=form)
        
        user = User(
            username=form.username.data,
            email=form.email.data,
            tg_username=form.tg_username.data or None
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        base_url = str(
            NotificationConfig.query.filter_by(key='service_base_url').first().value if NotificationConfig.query.filter_by(key='service_base_url').first() else ''
        ).strip()
        if not base_url:
            base_url = current_app.config.get('SERVER_NAME') or 'http://localhost'
        if not base_url.startswith(('http://', 'https://')):
            base_url = f'https://{base_url}'
        login_url = f"{base_url.rstrip('/')}/login"
        template = NotificationTemplate.query.filter_by(is_default_registration_welcome=True, is_active=True).first()
        subject = template.email_subject or 'Your account was created successfully' if template else 'Your account was created successfully'
        body = (
            render_notification_template(template.email_body or '', {'username': user.username, 'login_url': login_url})
            if template and template.email_body
            else (
                f"Hello {user.username},\n\n"
                f"Your account was created successfully.\n"
                f"Your username is: {user.username}\n"
                f"You can sign in here: {login_url}\n"
            )
        )
        send_notification_message(user, 'email', subject, body)

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('main.login'))
    return render_template('register.html', form=form)


@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            flash(f'Welcome back, {user.username}!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html', form=form)


@main_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('main.index'))


@main_bp.route('/password-reset', methods=['GET', 'POST'])
def password_reset():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    form = PasswordResetForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user:
            selected_channel = form.notification_channel.data or user.notification_channel or 'email'
            if selected_channel == 'telegram' and not (user.telegram_chat_id or '').strip():
                flash('To use Telegram reset, open the bot and press Start first, then try again.', 'warning')
                return render_template('password_reset.html', form=form)

            new_password = os.urandom(6).hex()
            user.set_password(new_password)
            user.notification_channel = selected_channel
            sent = send_password_reset(user, new_password)
            if sent:
                db.session.commit()
                flash('A password reset message has been sent.', 'success')
            else:
                db.session.rollback()
                flash('Reset message could not be delivered. Please try email or contact an admin.', 'danger')
        else:
            flash('No account matched that username.', 'warning')
        return redirect(url_for('main.login'))
    return render_template('password_reset.html', form=form)


@main_bp.route('/admin/users/<int:user_id>/send-password-reset', methods=['POST'])
@login_required
@admin_required
def send_password_reset_admin(user_id):
    user = User.query.get_or_404(user_id)
    new_password = os.urandom(6).hex()
    user.set_password(new_password)
    sent = send_password_reset(user, new_password)
    if sent:
        db.session.commit()
        flash(f'A password reset message was sent to {user.username}.', 'success')
    else:
        db.session.rollback()
        flash(f'Could not deliver password reset message to {user.username}.', 'danger')
    return redirect(url_for('main.manage_users'))


@main_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Allow users to update their own profile info and password."""
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        existing_username = User.query.filter(User.username == form.username.data, User.id != current_user.id).first()
        existing_email = User.query.filter(User.email == form.email.data, User.id != current_user.id).first()

        if existing_username:
            flash('Username already taken.', 'danger')
            return render_template('profile.html', form=form)
        if existing_email:
            flash('Email already registered.', 'danger')
            return render_template('profile.html', form=form)

        current_user.username = form.username.data
        current_user.email = form.email.data
        current_user.tg_username = form.tg_username.data or None
        current_user.receive_group_test_notifications = form.receive_group_test_notifications.data
        current_user.notification_channel = form.notification_channel.data or 'email'
        current_user.digest_frequency = (form.digest_frequency.data or 'off').strip().lower()
        current_user.digest_hourly_minute_utc = _clamp_int(form.digest_hourly_minute_utc.data, 0, 0, 59)
        current_user.digest_daily_hour_utc = _clamp_int(form.digest_daily_hour_utc.data, 9, 0, 23)

        if form.password.data:
            current_user.set_password(form.password.data)
            flash('Password updated.', 'success')

        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('main.profile'))

    active_token = (
        current_user.telegram_link_tokens
        .filter(TelegramLinkToken.used_at.is_(None), TelegramLinkToken.expires_at >= datetime.utcnow())
        .order_by(TelegramLinkToken.created_at.desc())
        .first()
    )
    telegram_link_token = active_token.token if active_token else None
    telegram_link_url = _build_telegram_deep_link(telegram_link_token) if telegram_link_token else None
    telegram_start_command = f"/start {telegram_link_token}" if telegram_link_token else None

    return render_template(
        'profile.html',
        form=form,
        telegram_link_url=telegram_link_url,
        telegram_link_token=telegram_link_token,
        telegram_start_command=telegram_start_command,
        telegram_chat_id=current_user.telegram_chat_id,
    )


@main_bp.route('/profile/telegram-link-token', methods=['POST'])
@login_required
def create_telegram_link_token():
    token = _issue_telegram_link_token(current_user)
    db.session.commit()

    deep_link = _build_telegram_deep_link(token.token)
    if deep_link:
        flash('Telegram link created. Open the bot link and press Start to complete setup.', 'success')
    else:
        flash('Token created, but Telegram bot username is not configured by admin yet.', 'warning')

    return redirect(url_for('main.profile'))


@main_bp.route('/dashboard')
@login_required
def dashboard():
    """
    Main user dashboard.
    - Admins: See ALL tests + quick links to manage/create.
    - Regular users: 
      * recruiting tests (can request)
      * testing/closed tests ONLY if they have an approved Participation.
    """
    group_by = request.args.get('group_by', 'status')
    sort_by = request.args.get('sort_by', 'updated_at')
    show_hidden = str(request.args.get('show_hidden', '0')).lower() in ('1', 'true', 'yes', 'on')

    if current_user.is_admin:
        tests = GroupTest.query.order_by(GroupTest.updated_at.desc()).all()
    else:
        # Efficient query: all recruiting OR (non-recruiting member-only statuses AND user has approved part.)
        recruiting = GroupTest.query.filter_by(status='recruiting').all()
        member_tests = (
            GroupTest.query
            .join(Participation)
            .filter(
                Participation.user_id == current_user.id,
                Participation.approved == True,
                GroupTest.status.in_(['testing', 'ready_for_payment', 'closed'])
            )
            .all()
        )
        # Dedup while preserving order preference
        seen = set()
        tests = []
        for t in recruiting + member_tests:
            if t.id not in seen:
                seen.add(t.id)
                tests.append(t)

    membership_map = {
        part.group_test_id: part
        for part in Participation.query.filter_by(user_id=current_user.id).all()
    }
    hidden_test_ids = {
        item.group_test_id
        for item in DashboardHiddenGroupTest.query.filter_by(user_id=current_user.id).all()
    }

    annotated_tests = []
    for test in tests:
        test.my_participation = membership_map.get(test.id)
        if test.my_participation and test.my_participation.denied:
            test.my_join_state = 'denied'
        elif test.my_participation and test.my_participation.approved:
            test.my_join_state = 'approved'
        elif test.my_participation:
            test.my_join_state = 'pending'
        else:
            test.my_join_state = 'not_joined'
        test.hidden_from_dashboard = test.id in hidden_test_ids
        if show_hidden or not test.hidden_from_dashboard:
            annotated_tests.append(test)

    def group_label(test):
        if group_by == 'title':
            return (test.title or 'Untitled').strip()[:1].upper() or '#'
        if group_by == 'compound':
            return (test.compound or 'Unspecified Compound').strip() or 'Unspecified Compound'
        if group_by == 'tags':
            return test.primary_tag() or 'Untagged'
        if group_by == 'join_state':
            if test.my_join_state == 'denied':
                return 'Denied'
            if test.my_join_state == 'approved':
                return 'Approved'
            if test.my_join_state == 'pending':
                return 'Pending'
            return 'Not Joined'
        if group_by == 'none':
            return 'All Tests'
        return _format_status_label(test.status)

    def group_sort_key(test):
        if sort_by == 'title':
            return (test.title or '').lower()
        if sort_by == 'compound':
            return (test.compound or '').lower()
        if sort_by == 'tags':
            return test.tag_names().lower()
        if sort_by == 'status':
            status_order = {'recruiting': 0, 'ready_for_payment': 1, 'testing': 2, 'closed': 3}
            return (status_order.get(test.status, 99), (test.title or '').lower())
        if sort_by == 'join_state':
            join_order = {'approved': 0, 'pending': 1, 'denied': 2, 'not_joined': 3}
            return (join_order.get(test.my_join_state, 99), (test.title or '').lower())
        return test.updated_at or datetime.min

    grouped_tests = []
    if group_by == 'none':
        grouped_tests.append({
            'label': 'All Tests',
            'key': 'all',
            'tests': sorted(annotated_tests, key=group_sort_key, reverse=sort_by == 'updated_at'),
        })
    else:
        grouped = {}
        for test in annotated_tests:
            grouped.setdefault(group_label(test), []).append(test)

        if group_by == 'status':
            group_order = {'Recruiting': 0, 'Ready For Payment': 1, 'Testing': 2, 'Closed': 3}
            group_names = sorted(grouped.keys(), key=lambda label: (group_order.get(label, 99), label.lower()))
        elif group_by == 'join_state':
            group_order = {'Approved': 0, 'Pending': 1, 'Denied': 2, 'Not Joined': 3}
            group_names = sorted(grouped.keys(), key=lambda label: (group_order.get(label, 99), label.lower()))
        else:
            group_names = sorted(grouped.keys(), key=str.lower)

        for label in group_names:
            grouped_tests.append({
                'label': label,
                'key': label.lower().replace(' ', '-'),
                'tests': sorted(grouped[label], key=group_sort_key, reverse=sort_by == 'updated_at'),
            })

    return render_template(
        'dashboard.html',
        tests=annotated_tests,
        grouped_tests=grouped_tests,
        current_user=current_user,
        group_by=group_by,
        sort_by=sort_by,
        show_hidden=show_hidden,
    )


@main_bp.route('/test/<int:test_id>/request-quick', methods=['POST'])
@login_required
def request_participation_quick(test_id):
    test = GroupTest.query.get_or_404(test_id)
    if test.status != 'recruiting':
        flash('This test is not currently open for new requests.', 'warning')
        return redirect(url_for('main.dashboard'))

    existing = Participation.query.filter_by(group_test_id=test_id, user_id=current_user.id).first()
    if existing:
        if existing.denied:
            reason_suffix = f" Reason: {existing.denied_reason}" if existing.denied_reason else ''
            flash(f'Your request for this test was denied by an admin.{reason_suffix}', 'warning')
        elif existing.approved:
            flash('You are already approved for this test.', 'info')
        else:
            flash('You have already submitted a request for this test.', 'info')
        return redirect(url_for('main.dashboard'))

    part = Participation(
        group_test_id=test_id,
        user_id=current_user.id,
        name=current_user.username,
        tg_username=current_user.tg_username,
        us_based=True,
        state=None,
        vial_donor=False,
        notes='Requested from dashboard',
        denied=False,
        denied_at=None,
        denied_reason=None,
        approved=False,
    )
    db.session.add(part)
    db.session.commit()

    admin_users = User.query.filter_by(is_admin=True, is_active=True).all()
    if admin_users:
        subject = f"New participation request for {test.title}"
        body = (
            f"A new participation request was submitted by {current_user.username} for the test \"{test.title}\".\n"
            f"Email: {current_user.email}\n"
            f"Telegram: {current_user.tg_username or 'Not provided'}\n"
            f"Review the request here: {request.host_url.rstrip('/')}{url_for('main.test_detail', test_id=test.id)}\n"
        )
        for admin_user in admin_users:
            send_notification_message(admin_user, admin_user.notification_channel or 'email', subject, body)

    flash('Participation request submitted successfully. Admin will review shortly.', 'success')
    return redirect(url_for('main.dashboard'))


@main_bp.route('/dashboard/hide/<int:test_id>', methods=['POST'])
@login_required
def toggle_dashboard_hidden(test_id):
    test = GroupTest.query.get_or_404(test_id)
    if not test.can_user_see(current_user):
        abort(403)

    hidden = DashboardHiddenGroupTest.query.filter_by(user_id=current_user.id, group_test_id=test.id).first()
    if hidden:
        db.session.delete(hidden)
        flash(f'"{test.title}" is visible on your dashboard again.', 'success')
    else:
        db.session.add(DashboardHiddenGroupTest(user_id=current_user.id, group_test_id=test.id))
        flash(f'"{test.title}" is now hidden from your dashboard.', 'info')

    db.session.commit()
    return redirect(url_for(
        'main.dashboard',
        group_by=request.form.get('group_by', 'status'),
        sort_by=request.form.get('sort_by', 'updated_at'),
        show_hidden=request.form.get('show_hidden', '0'),
    ))


def _can_user_view_group_test_result_image(test, user):
    if not user.is_authenticated:
        return False
    if user.is_admin:
        return True
    if test.status != 'closed':
        return False

    part = Participation.query.filter_by(
        group_test_id=test.id,
        user_id=user.id,
        approved=True,
        denied=False,
    ).first()
    return bool(part and part.paid_lab)


def _can_user_view_group_test_results(test, user):
    """Gate full group-test result visibility (link, item values, and image)."""
    return _can_user_view_group_test_result_image(test, user)


def _telegram_help_message():
    return (
        "Group Test Manager bot commands:\n"
        "/tests - list tests you can see\n"
        "/status <test_id> - view your request/approval status\n"
        "/join <test_id> - submit a join request for recruiting tests\n"
        "/help - show this help message"
    )


def _telegram_user_visible_tests(user):
    if user.is_admin:
        return GroupTest.query.order_by(GroupTest.updated_at.desc()).limit(20).all()

    recruiting = GroupTest.query.filter_by(status='recruiting').all()
    member_tests = (
        GroupTest.query
        .join(Participation)
        .filter(
            Participation.user_id == user.id,
            Participation.approved == True,
            Participation.denied == False,
            GroupTest.status.in_(['testing', 'ready_for_payment', 'closed'])
        )
        .all()
    )
    seen = set()
    tests = []
    for test in recruiting + member_tests:
        if test.id in seen:
            continue
        seen.add(test.id)
        tests.append(test)
    return tests[:20]


def _telegram_status_summary_for_user(user, test):
    part = Participation.query.filter_by(group_test_id=test.id, user_id=user.id).first()
    config_map = _config_values_map()
    base_context = {
        'test_id': test.id,
        'test_title': test.title,
    }
    if part is None:
        return _render_telegram_status_template(
            config_map,
            'telegram_status_user_no_request_template',
            'You have no request for #{{ test_id }} {{ test_title }}.',
            base_context,
        )
    if part.denied:
        denied_context = {
            **base_context,
            'denied_reason': part.denied_reason or '',
        }
        return _render_telegram_status_template(
            config_map,
            'telegram_status_user_denied_template',
            '#{{ test_id }} {{ test_title }}: Denied. {{ denied_reason }}',
            denied_context,
        ).strip()
    if part.approved:
        approved_context = {
            **base_context,
            'order_status': part.order_status or 'pending',
            'amount_owed': f"{(part.amount_owed or 0):.2f}",
            'amount_paid': f"{(part.amount_paid or 0):.2f}",
        }
        return _render_telegram_status_template(
            config_map,
            'telegram_status_user_approved_template',
            '#{{ test_id }} {{ test_title }}: Approved. Order status: {{ order_status }}. Amount owed: ${{ amount_owed }}. Paid: ${{ amount_paid }}.',
            approved_context,
        )
    return _render_telegram_status_template(
        config_map,
        'telegram_status_user_pending_template',
        '#{{ test_id }} {{ test_title }}: Pending admin review.',
        base_context,
    )


def _telegram_join_test_for_user(user, test):
    if test.status != 'recruiting':
        return f"#{test.id} {test.title} is not accepting new requests right now."

    existing = Participation.query.filter_by(group_test_id=test.id, user_id=user.id).first()
    if existing:
        if existing.denied:
            reason_suffix = f" Reason: {existing.denied_reason}" if existing.denied_reason else ""
            return f"Your request for #{test.id} was denied.{reason_suffix}"
        if existing.approved:
            return f"You are already approved for #{test.id} {test.title}."
        return f"You already have a pending request for #{test.id} {test.title}."

    part = Participation(
        group_test_id=test.id,
        user_id=user.id,
        name=user.username,
        tg_username=user.tg_username,
        us_based=True,
        vial_donor=False,
        notes='Requested from Telegram bot',
        denied=False,
        approved=False,
    )
    db.session.add(part)
    db.session.commit()
    return f"Request submitted for #{test.id} {test.title}. An admin will review shortly."


@main_bp.route('/telegram/webhook', methods=['POST'])
@csrf.exempt
def telegram_webhook():
    config_map = _config_values_map()
    source_ip = (request.remote_addr or '').strip()
    if not _is_telegram_webhook_ip_allowed(source_ip, config_map):
        return jsonify({'ok': False}), 403

    secret = str(config_map.get('telegram_webhook_secret') or '').strip()
    provided_secret = str(request.headers.get('X-Telegram-Bot-Api-Secret-Token') or '').strip()
    if secret and not (provided_secret and secrets.compare_digest(secret, provided_secret)):
        return jsonify({'ok': False}), 403

    if not request.is_json:
        return jsonify({'ok': False}), 415

    payload = request.get_json(silent=True) or {}
    update_id = payload.get('update_id')
    if update_id is not None:
        try:
            update_id = int(update_id)
        except (TypeError, ValueError):
            return jsonify({'ok': False}), 400

        if not _reserve_telegram_update(update_id, source_ip):
            append_notification_log(f"telegram: duplicate webhook update ignored ({update_id})", debug=True)
            db.session.rollback()
            return jsonify({'ok': True})

    message = payload.get('message') or payload.get('edited_message') or {}
    if not isinstance(message, dict):
        db.session.commit()
        return jsonify({'ok': True})

    chat = message.get('chat') or {}
    from_user = message.get('from') or {}
    chat_id_raw = chat.get('id')
    telegram_user_id_raw = from_user.get('id')
    incoming_username = str(from_user.get('username') or '').strip().lstrip('@')
    chat_id = str(chat_id_raw).strip() if chat_id_raw is not None else ''
    telegram_user_id = str(telegram_user_id_raw).strip() if telegram_user_id_raw is not None else ''
    text = (message.get('text') or '').strip()
    if not chat_id or not text:
        db.session.commit()
        return jsonify({'ok': True})

    if text.lower().startswith('/start'):
        token_value = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ''
        if not token_value:
            if incoming_username:
                matched_users = User.query.filter(User.tg_username.ilike(incoming_username)).all()
                if len(matched_users) == 1:
                    send_telegram_chat_message(chat_id, 'We found a possible profile match by username. For security, generate a link token from your profile and use /start <token> to confirm.')
                    db.session.commit()
                    return jsonify({'ok': True})
            send_telegram_chat_message(chat_id, 'Welcome. To link this Telegram chat, open your profile in Group Test Manager and generate a link token.')
            db.session.commit()
            return jsonify({'ok': True})

        token = TelegramLinkToken.query.filter_by(token=token_value).first()
        if token is None or token.used_at is not None or token.expires_at < datetime.utcnow():
            send_telegram_chat_message(chat_id, 'This link token is invalid or expired. Please generate a new link token from your profile.')
            db.session.commit()
            return jsonify({'ok': True})

        if telegram_user_id:
            existing_owner = User.query.filter_by(telegram_user_id=telegram_user_id).first()
            if existing_owner is not None and existing_owner.id != token.user_id:
                send_telegram_chat_message(chat_id, 'This Telegram account is already linked to a different user. Contact an admin for relink support.')
                db.session.commit()
                return jsonify({'ok': True})

        token.user.telegram_chat_id = chat_id
        if telegram_user_id:
            token.user.telegram_user_id = telegram_user_id
        if incoming_username:
            token.user.tg_username = incoming_username
        token.used_at = datetime.utcnow()
        db.session.commit()
        send_telegram_chat_message(chat_id, 'Your Telegram account is now linked. Use /help to see available commands.')
        return jsonify({'ok': True})

    linked_user = None
    if telegram_user_id:
        linked_user = User.query.filter_by(telegram_user_id=telegram_user_id).first()
    if linked_user is None:
        linked_user = User.query.filter_by(telegram_chat_id=chat_id).first()
    if linked_user is None:
        send_telegram_chat_message(chat_id, 'Your Telegram chat is not linked yet. Open Group Test Manager profile and generate a bot link token first.')
        db.session.commit()
        return jsonify({'ok': True})

    if telegram_user_id and not linked_user.telegram_user_id:
        linked_user.telegram_user_id = telegram_user_id
    if incoming_username and incoming_username != (linked_user.tg_username or '').strip().lstrip('@'):
        linked_user.tg_username = incoming_username
    if chat_id != (linked_user.telegram_chat_id or '').strip():
        linked_user.telegram_chat_id = chat_id
    db.session.commit()

    lower = text.lower()
    if lower == '/help':
        send_telegram_chat_message(chat_id, _telegram_help_message())
        return jsonify({'ok': True})

    if lower == '/tests':
        tests = _telegram_user_visible_tests(linked_user)
        if not tests:
            send_telegram_chat_message(chat_id, 'No eligible tests found right now.')
            return jsonify({'ok': True})
        lines = [f"#{test.id} {test.title} [{test.status}]" for test in tests]
        send_telegram_chat_message(chat_id, 'Eligible tests:\n' + '\n'.join(lines))
        return jsonify({'ok': True})

    if lower.startswith('/status'):
        parts = text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            send_telegram_chat_message(chat_id, 'Usage: /status <test_id>')
            return jsonify({'ok': True})
        test = GroupTest.query.get(int(parts[1]))
        if test is None or not test.can_user_see(linked_user):
            send_telegram_chat_message(chat_id, 'Test not found or not visible to your account.')
            return jsonify({'ok': True})
        send_telegram_chat_message(chat_id, _telegram_status_summary_for_user(linked_user, test))
        return jsonify({'ok': True})

    if lower.startswith('/join'):
        parts = text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            send_telegram_chat_message(chat_id, 'Usage: /join <test_id>')
            return jsonify({'ok': True})
        test = GroupTest.query.get(int(parts[1]))
        if test is None or not test.can_user_see(linked_user):
            send_telegram_chat_message(chat_id, 'Test not found or not visible to your account.')
            return jsonify({'ok': True})
        send_telegram_chat_message(chat_id, _telegram_join_test_for_user(linked_user, test))
        return jsonify({'ok': True})

    send_telegram_chat_message(chat_id, _telegram_help_message())
    return jsonify({'ok': True})


@main_bp.route('/result-image/group-test/<int:test_id>')
@login_required
def serve_group_test_result_image(test_id):
    test = GroupTest.query.get_or_404(test_id)
    if not test.results_image_key:
        abort(404)
    if not _can_user_view_group_test_result_image(test, current_user):
        abort(403)

    try:
        secure_url = generate_result_image_presigned_url(test.results_image_key)
    except (StorageConfigurationError, StorageUploadError):
        abort(503)
    return redirect(secure_url)


@main_bp.route('/result-image/public/<int:result_id>')
@login_required
def serve_public_result_image(result_id):
    result = PublicResult.query.get_or_404(result_id)
    if not result.results_image_key:
        abort(404)

    try:
        secure_url = generate_result_image_presigned_url(result.results_image_key)
    except (StorageConfigurationError, StorageUploadError):
        abort(503)
    return redirect(secure_url)


@main_bp.route('/test/<int:test_id>', methods=['GET', 'POST'])
@login_required
def test_detail(test_id):
    test = GroupTest.query.get_or_404(test_id)
    if not test.can_user_see(current_user):
        abort(403)
    
    costs = test.calculate_costs()
    reimbursed_by_user = None
    if test.donor_shipping_reimbursement == 'participant' and test.donor_shipping_reimbursed_by_id:
        reimbursed_by_user = User.query.get(test.donor_shipping_reimbursed_by_id)
    
    # Current user's participation (if any)
    my_part = Participation.query.filter_by(
        group_test_id=test_id, user_id=current_user.id
    ).first()
    
    # Show full participant list (approved + pending) to admins + approved members
    show_participant_list = current_user.is_admin or (my_part is not None and my_part.approved)
    
    if show_participant_list:
        parts = (
            test.participations
            .filter(Participation.denied == False)
            .order_by(Participation.approved.desc(), Participation.requested_at)
            .all()
        )
    else:
        parts = []

    form = NotifyParticipantsForm()
    templates = NotificationTemplate.query.filter_by(is_active=True, hide_from_participant_notifications=False).order_by(NotificationTemplate.name).all()
    form.template_id.choices = [(template.id, template.name) for template in templates]
    can_view_results = _can_user_view_group_test_results(test, current_user)
    payment_option_contexts = [_build_payment_option_context(option) for option in test.payment_options if option.is_active]
    selected_payment_option = None
    if my_part and my_part.preferred_payment_option_id:
        selected_payment_option = _build_payment_option_context(my_part.preferred_payment_option)

    if current_user.is_admin and form.validate_on_submit():
        template = NotificationTemplate.query.get_or_404(form.template_id.data)
        sent = 0
        for part in parts:
            if part.user_id and part.user and part.approved and part.user.receive_group_test_notifications:
                amount_owed = part.amount_owed
                if amount_owed is None:
                    amount_owed = costs.get('donor_pays' if part.vial_donor else 'non_donor_pays', 0)
                send_group_test_notification(test, part.user, template, amount_owed=amount_owed)
                sent += 1
        flash(f'Sent notifications to {sent} participant(s).', 'success')
        return redirect(url_for('main.test_detail', test_id=test_id))
    
    return render_template(
        'group_test_detail.html',
        test=test,
        test_results_image_url=(
            url_for('main.serve_group_test_result_image', test_id=test.id)
            if test.results_image_key and _can_user_view_group_test_result_image(test, current_user)
            else None
        ),
        test_results_file_kind=_result_file_kind(test.results_image_key) if test.results_image_key else None,
        can_view_results=can_view_results,
        costs=costs,
        participations=parts,
        my_part=my_part,
        show_participant_list=show_participant_list,
        reimbursed_by_user=reimbursed_by_user,
        notify_form=form,
        notification_templates=templates,
        payment_options=payment_option_contexts,
        selected_payment_option=selected_payment_option,
    )


@main_bp.route('/my-results')
@login_required
def my_results():
    group_by = request.args.get('group_by', 'none')
    sort_by = request.args.get('sort_by', 'posted_at')
    sort_dir = request.args.get('sort_dir', 'desc')
    query = (request.args.get('q') or '').strip().lower()

    group_results = []
    if current_user.is_admin:
        member_tests = (
            GroupTest.query
            .filter(
                GroupTest.status == 'closed',
                GroupTest.results_link.isnot(None),
            )
            .all()
        )
    else:
        member_tests = (
            GroupTest.query
            .join(Participation)
            .filter(
                Participation.user_id == current_user.id,
                Participation.approved == True,
                Participation.denied == False,
                Participation.paid_lab == True,
                GroupTest.status == 'closed',
                GroupTest.results_link.isnot(None),
            )
            .all()
        )
    for test in member_tests:
        if not _can_user_view_group_test_results(test, current_user):
            continue

        group_results.append({
            'kind': 'group_test',
            'title': test.title,
            'summary': test.description or '',
            'results_link': test.results_link,
            'results_image_url': (
                url_for('main.serve_group_test_result_image', test_id=test.id)
                    if test.results_image_key and _can_user_view_group_test_result_image(test, current_user)
                else None
            ),
            'results_file_kind': _result_file_kind(test.results_image_key) if test.results_image_key else None,
            'posted_at': test.results_posted_at or test.updated_at or test.created_at,
            'source_label': 'Group Test',
            'lab_item_results': [
                {
                    'name': item.get('name') or '',
                    'result': item.get('result') or '',
                }
                for item in (test.lab_test_details or [])
                if item.get('result')
            ],
            'tags': [tag.name for tag in test.tags],
            'tag_text': test.tag_names(),
            'search_text': ' '.join([
                test.title or '',
                test.description or '',
                test.results_link or '',
                test.tag_names(),
            ]),
        })

    public_results = PublicResult.query.order_by(PublicResult.posted_at.desc()).all()
    for result in public_results:
        group_results.append({
            'kind': 'public_result',
            'title': result.title,
            'summary': result.summary or '',
            'results_link': result.results_link,
            'results_image_url': url_for('main.serve_public_result_image', result_id=result.id) if result.results_image_key else None,
            'results_file_kind': _result_file_kind(result.results_image_key) if result.results_image_key else None,
            'posted_at': result.posted_at,
            'source_label': 'Public Result',
            'lab_item_results': [
                {
                    'name': item.get('name') or '',
                    'result': item.get('result') or '',
                }
                for item in (result.item_results or [])
                if item.get('name')
            ],
            'tags': [tag.name for tag in result.tags],
            'tag_text': result.tag_names(),
            'search_text': ' '.join([
                result.title or '',
                result.summary or '',
                result.results_link or '',
                result.tag_names(),
            ]),
        })

    if query:
        group_results = [item for item in group_results if query in item['search_text'].lower()]

    reverse = str(sort_dir).lower() != 'asc'
    if sort_by == 'title':
        group_results.sort(key=lambda item: (item['title'] or '').lower(), reverse=reverse)
    elif sort_by == 'tags':
        group_results.sort(key=lambda item: item['tag_text'].lower(), reverse=reverse)
    else:
        group_results.sort(key=lambda item: item['posted_at'] or datetime.min, reverse=reverse)

    grouped_results = []
    if group_by == 'none':
        grouped_results.append({
            'label': 'All Results',
            'results': group_results,
        })
    else:
        grouped = {}
        for item in group_results:
            if group_by == 'tags':
                tags = item['tags'] or ['Untagged']
                for tag in tags:
                    grouped.setdefault(tag, []).append(item)
            elif group_by == 'date':
                label = item['posted_at'].strftime('%Y-%m-%d') if item['posted_at'] else 'Unknown Date'
                grouped.setdefault(label, []).append(item)
            elif group_by == 'source':
                grouped.setdefault(item['source_label'] or 'Other', []).append(item)
            else:
                grouped.setdefault((item['title'] or 'Untitled')[0].upper(), []).append(item)

        if group_by == 'date':
            group_names = sorted(grouped.keys(), reverse=reverse)
        else:
            group_names = sorted(grouped.keys(), key=str.lower)

        for label in group_names:
            grouped_results.append({
                'label': label,
                'results': grouped[label],
            })

    return render_template(
        'my_results.html',
        results=group_results,
        grouped_results=grouped_results,
        group_by=group_by,
        sort_by=sort_by,
        sort_dir=sort_dir,
        query=query,
    )


@main_bp.route('/test/<int:test_id>/my-status', methods=['GET', 'POST'])
@login_required
def update_my_participant_status(test_id):
    """Allow approved participants to update their vendor order status and self-report payment."""
    test = GroupTest.query.get_or_404(test_id)
    part = Participation.query.filter_by(group_test_id=test_id, user_id=current_user.id, approved=True).first()

    if not part:
        flash("You are not an approved participant in this test.", "warning")
        return redirect(url_for('main.test_detail', test_id=test_id))

    form = ParticipantStatusForm(obj=part)
    available_options = [option for option in test.payment_options if option.is_active]
    form.preferred_payment_option_id.choices = [(0, 'No preference selected')] + [
        (option.id, option.display_title()) for option in available_options
    ]
    if not form.is_submitted():
        form.preferred_payment_option_id.data = part.preferred_payment_option_id or 0

    if form.validate_on_submit():
        part.order_status = form.order_status.data
        part.paid_lab = form.paid_lab.data
        if form.amount_paid.data is not None:
            part.amount_paid = form.amount_paid.data
        part.notes = form.notes.data or part.notes

        selected_id = int(form.preferred_payment_option_id.data or 0)
        if test.status in ('testing', 'ready_for_payment') and selected_id > 0:
            selected_option = next((opt for opt in available_options if opt.id == selected_id), None)
            if selected_option:
                part.preferred_payment_option_id = selected_option.id
                part.preferred_payment_snapshot = _serialize_payment_option_snapshot(selected_option)
        elif selected_id == 0:
            part.preferred_payment_option_id = None
            part.preferred_payment_snapshot = None

        db.session.commit()
        flash("Your status has been updated.", "success")
        return redirect(url_for('main.test_detail', test_id=test_id))

    selected_option = next((opt for opt in available_options if opt.id == (form.preferred_payment_option_id.data or 0)), None)
    return render_template(
        'participant_update_status.html',
        form=form,
        test=test,
        part=part,
        available_payment_options=[_build_payment_option_context(option) for option in available_options],
        selected_payment_option=_build_payment_option_context(selected_option),
    )


@main_bp.route('/test/<int:test_id>/request', methods=['GET', 'POST'])
@login_required
def request_participation(test_id):
    test = GroupTest.query.get_or_404(test_id)
    if test.status != 'recruiting':
        flash('This test is not currently open for new requests.', 'warning')
        return redirect(url_for('main.test_detail', test_id=test_id))
    
    # Check if already requested
    existing = Participation.query.filter_by(
        group_test_id=test_id, user_id=current_user.id
    ).first()
    if existing:
        if existing.denied:
            reason_suffix = f" Reason: {existing.denied_reason}" if existing.denied_reason else ''
            flash(f'Your request for this test was denied by an admin.{reason_suffix}', 'warning')
        elif existing.approved:
            flash('You are already approved for this test.', 'info')
        else:
            flash('You have already submitted a request for this test.', 'info')
        return redirect(url_for('main.test_detail', test_id=test_id))
    
    form = ParticipationRequestForm()
    # Prefill from user profile
    if not form.is_submitted():
        form.name.data = current_user.username  # or add full_name field later
        form.tg_username.data = current_user.tg_username
    
    if form.validate_on_submit():
        part = Participation(
            group_test_id=test_id,
            user_id=current_user.id,
            name=form.name.data,
            tg_username=form.tg_username.data,
            us_based=form.us_based.data,
            state=form.state.data,
            vial_donor=form.vial_donor.data,
            notes=form.notes.data,
            denied=False,
            denied_at=None,
            denied_reason=None,
            approved=False  # Admin must approve
        )
        db.session.add(part)
        db.session.commit()

        admin_users = User.query.filter_by(is_admin=True, is_active=True).all()
        if admin_users:
            subject = f"New participation request for {test.title}"
            body = (
                f"A new participation request was submitted by {current_user.username} for the test \"{test.title}\".\n"
                f"Email: {current_user.email}\n"
                f"Telegram: {current_user.tg_username or 'Not provided'}\n"
                f"Review the request here: {request.host_url.rstrip('/')}{url_for('main.test_detail', test_id=test.id)}\n"
            )
            for admin_user in admin_users:
                send_notification_message(admin_user, admin_user.notification_channel or 'email', subject, body)

        flash('Participation request submitted successfully. Admin will review shortly.', 'success')
        return redirect(url_for('main.dashboard'))
    
    return render_template('request_participation.html', test=test, form=form)


@main_bp.route('/test/<int:test_id>/reapply', methods=['POST'])
@login_required
def reapply_participation(test_id):
    test = GroupTest.query.get_or_404(test_id)
    if test.status != 'recruiting':
        flash('This test is not currently open for re-requests.', 'warning')
        return redirect(url_for('main.test_detail', test_id=test_id))

    part = Participation.query.filter_by(group_test_id=test_id, user_id=current_user.id).first()
    if not part:
        flash('No prior request found. Submit a new participation request instead.', 'info')
        return redirect(url_for('main.request_participation', test_id=test_id))

    if part.approved:
        flash('You are already approved for this test.', 'info')
        return redirect(url_for('main.test_detail', test_id=test_id))

    if not part.denied:
        flash('Your request is already pending admin review.', 'info')
        return redirect(url_for('main.test_detail', test_id=test_id))

    part.denied = False
    part.denied_at = None
    part.denied_reason = None
    part.approved = False
    part.approved_at = None
    part.requested_at = datetime.utcnow()
    db.session.commit()

    admin_users = User.query.filter_by(is_admin=True, is_active=True).all()
    if admin_users:
        subject = f"Reapply request for {test.title}"
        body = (
            f"{current_user.username} has re-applied for the test \"{test.title}\".\n"
            f"Email: {current_user.email}\n"
            f"Telegram: {current_user.tg_username or 'Not provided'}\n"
            f"Review the request here: {request.host_url.rstrip('/')}{url_for('main.test_detail', test_id=test.id)}\n"
        )
        for admin_user in admin_users:
            send_notification_message(admin_user, admin_user.notification_channel or 'email', subject, body)

    flash('Your request has been re-submitted for admin review.', 'success')
    return redirect(url_for('main.test_detail', test_id=test_id))


# ==================== ADMIN ROUTES ====================

@main_bp.route('/admin/create-test', methods=['GET', 'POST'])
@login_required
@admin_required
def create_test():
    form = GroupTestForm()
    populate_donor_shipping_choices(form)
    populate_payment_option_choices(form)
    if not form.is_submitted():
        form.tag_names.data = ''
        form.payment_option_ids.data = []
    if form.validate_on_submit():
        lab_items = []
        names = request.form.getlist('lab_item_name')
        prices = request.form.getlist('lab_item_price')
        vials = request.form.getlist('lab_item_vials')
        results = request.form.getlist('lab_item_result')
        for name, price, vial_count, result_text in zip_longest(names, prices, vials, results, fillvalue=''):
            name = (name or '').strip()
            if not name:
                continue
            try:
                price_value = float(price or 0)
            except ValueError:
                price_value = 0.0
            try:
                vial_value = int(vial_count or 0)
            except ValueError:
                vial_value = 0
            item = {
                'name': name,
                'price': round(price_value, 2),
                'vials_needed': vial_value,
            }
            result_text = (result_text or '').strip()
            if result_text:
                item['result'] = result_text
            lab_items.append(item)

        uploaded_image_key = None
        upload_file = request.files.get('results_image')
        if upload_file and upload_file.filename:
            try:
                uploaded_image_key = upload_result_image(upload_file, 'group-tests')
            except (StorageConfigurationError, StorageUploadError) as exc:
                flash(str(exc), 'danger')
                return render_template('admin/create_test.html', form=form, tag_suggestions=get_all_tag_names(), storage_settings=get_storage_settings())

        test = GroupTest(
            title=form.title.data,
            description=form.description.data,
            start_date=form.start_date.data,
            vendor=form.vendor.data,
            batch_number=form.batch_number.data,
            compound=form.compound.data,
            size=form.size.data,
            status=form.status.data,
            lab_name=form.lab_name.data or None,
            lab_test_details=lab_items,
            total_lab_cost=form.total_lab_cost.data or 0.0,
            shipping_cost=form.shipping_cost.data or 0.0,
            donor_shipping_cost=form.donor_shipping_cost.data or 0.0,
            donor_shipping_reimbursement=form.donor_shipping_reimbursement.data or 'credit',
            donor_shipping_reimbursed_by_id=form.donor_shipping_reimbursed_by_id.data or None,
            refund_per_donor=form.refund_per_donor.data or 20.0,
            order_number=form.order_number.data,
            quote_number=form.quote_number.data,
            results_link=form.results_link.data if form.status.data == 'closed' else None,
            results_image_key=uploaded_image_key,
            results_posted_at=datetime.utcnow() if form.status.data == 'closed' and form.results_link.data else None,
            created_by=current_user.id
        )
        selected_payment_ids = form.payment_option_ids.data or []
        if selected_payment_ids:
            test.payment_options = PaymentOption.query.filter(PaymentOption.id.in_(selected_payment_ids)).all()
        db.session.add(test)
        db.session.flush()
        apply_tags_to_record(test, form.tag_names.data)
        db.session.commit()
        try:
            test_url = f"{request.host_url.rstrip('/')}{url_for('main.test_detail', test_id=test.id)}"
            _send_new_test_created_to_telegram(test, test_url=test_url)
        except Exception as exc:
            append_notification_log(f'telegram: exception sending new test created message for test {test.id}: {exc}')
        flash(f'Group test "{test.title}" created successfully.', 'success')
        return redirect(url_for('main.test_detail', test_id=test.id))
    return render_template('admin/create_test.html', form=form, tag_suggestions=get_all_tag_names(), storage_settings=get_storage_settings())


@main_bp.route('/admin/edit-test/<int:test_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_test(test_id):
    test = GroupTest.query.get_or_404(test_id)
    form = GroupTestForm(obj=test)  # Pre-populate
    populate_donor_shipping_choices(form)
    populate_payment_option_choices(form, include_ids=[option.id for option in test.payment_options])
    if not form.is_submitted():
        form.tag_names.data = test.tag_names()
        form.payment_option_ids.data = [option.id for option in test.payment_options if option.is_active]
    if form.donor_shipping_reimbursed_by_id.data in (None, '') and test.donor_shipping_reimbursed_by_id:
        form.donor_shipping_reimbursed_by_id.data = test.donor_shipping_reimbursed_by_id
    elif form.donor_shipping_reimbursed_by_id.data is None:
        form.donor_shipping_reimbursed_by_id.data = 0
    
    if form.validate_on_submit():
        previous_status = test.status
        form.populate_obj(test)
        lab_items = []
        names = request.form.getlist('lab_item_name')
        prices = request.form.getlist('lab_item_price')
        vials = request.form.getlist('lab_item_vials')
        results = request.form.getlist('lab_item_result')
        for name, price, vial_count, result_text in zip_longest(names, prices, vials, results, fillvalue=''):
            name = (name or '').strip()
            if not name:
                continue
            try:
                price_value = float(price or 0)
            except ValueError:
                price_value = 0.0
            try:
                vial_value = int(vial_count or 0)
            except ValueError:
                vial_value = 0
            item = {
                'name': name,
                'price': round(price_value, 2),
                'vials_needed': vial_value,
            }
            result_text = (result_text or '').strip()
            if result_text:
                item['result'] = result_text
            lab_items.append(item)
        test.lab_name = form.lab_name.data or None
        test.lab_test_details = lab_items
        test.total_lab_cost = form.total_lab_cost.data or 0.0
        test.donor_shipping_cost = form.donor_shipping_cost.data or 0.0
        test.donor_shipping_reimbursement = form.donor_shipping_reimbursement.data or 'credit'
        test.donor_shipping_reimbursed_by_id = form.donor_shipping_reimbursed_by_id.data or None

        clear_existing_image = (request.form.get('clear_results_image') or '').lower() in {'1', 'true', 'on', 'yes'}
        upload_file = request.files.get('results_image')
        has_new_upload = bool(upload_file and upload_file.filename)
        if has_new_upload:
            try:
                new_key = upload_result_image(upload_file, 'group-tests')
            except (StorageConfigurationError, StorageUploadError) as exc:
                flash(str(exc), 'danger')
                return render_template(
                    'admin/edit_test.html',
                    form=form,
                    test=test,
                    tag_suggestions=get_all_tag_names(),
                    storage_settings=get_storage_settings(),
                    existing_results_image_url=url_for('main.serve_group_test_result_image', test_id=test.id) if test.results_image_key else None,
                )

            old_key = test.results_image_key
            test.results_image_key = new_key
            if old_key and old_key != new_key:
                delete_result_image(old_key)
        elif clear_existing_image and test.results_image_key:
            old_key = test.results_image_key
            test.results_image_key = None
            delete_result_image(old_key)

        apply_tags_to_record(test, form.tag_names.data)
        selected_payment_ids = form.payment_option_ids.data or []
        if selected_payment_ids:
            test.payment_options = PaymentOption.query.filter(PaymentOption.id.in_(selected_payment_ids)).all()
        else:
            test.payment_options = []
        if test.status != 'closed':
            test.results_link = None  # Clear if not closed
            if test.results_image_key:
                delete_result_image(test.results_image_key)
            test.results_image_key = None
            test.results_posted_at = None
        elif test.results_link and not test.results_posted_at:
            test.results_posted_at = datetime.utcnow()

        if previous_status != test.status:
            _send_status_update_to_telegram(test, previous_status)

        db.session.commit()
        flash('Group test updated.', 'success')
        return redirect(url_for('main.test_detail', test_id=test_id))
    
    return render_template(
        'admin/edit_test.html',
        form=form,
        test=test,
        tag_suggestions=get_all_tag_names(),
        storage_settings=get_storage_settings(),
        existing_results_image_url=url_for('main.serve_group_test_result_image', test_id=test.id) if test.results_image_key else None,
    )


@main_bp.route('/admin/manage-participants/<int:test_id>')
@login_required
@admin_required
def manage_participants(test_id):
    test = GroupTest.query.get_or_404(test_id)
    parts = test.participations.order_by(Participation.approved.desc(), Participation.requested_at).all()
    costs = test.calculate_costs()

    # Calculate live "Current Fair Share" for display (always accurate)
    for p in parts:
        if p.vial_donor:
            p.current_fair_share = costs.get('donor_pays', 0)
        else:
            p.current_fair_share = costs.get('non_donor_pays', 0)

    return render_template('admin/manage_participants.html', test=test, participations=parts, costs=costs)


def _recalculate_approved_amounts_for_test(test):
    """Keep approved participant balances consistent after approval changes."""
    costs = test.calculate_costs()
    for approved_part in test.participations.filter_by(approved=True).all():
        approved_part.update_amount_owed(costs)


def _approve_participation_record(part):
    part.approved = True
    part.approved_at = datetime.utcnow()
    part.denied = False
    part.denied_at = None
    part.denied_reason = None


def _deny_participation_record(part, reason):
    part.denied = True
    part.denied_at = datetime.utcnow()
    part.denied_reason = reason
    part.approved = False
    part.approved_at = None


def _reopen_participation_record(part):
    part.denied = False
    part.denied_at = None
    part.denied_reason = None
    part.approved = False
    part.approved_at = None
    part.requested_at = datetime.utcnow()


def _parse_participation_ids(raw_ids):
    valid_ids = []
    for raw_id in raw_ids:
        try:
            value = int(raw_id)
        except (TypeError, ValueError):
            continue
        if value > 0:
            valid_ids.append(value)
    return valid_ids


def _build_pending_queue_query(status_filter, search):
    pending_query = (
        Participation.query
        .join(GroupTest, Participation.group_test_id == GroupTest.id)
        .join(User, Participation.user_id == User.id)
        .filter(Participation.approved == False, Participation.denied == False)
    )

    if status_filter != 'all':
        pending_query = pending_query.filter(GroupTest.status == status_filter)

    if search:
        like_term = f"%{search}%"
        pending_query = pending_query.filter(
            or_(
                GroupTest.title.ilike(like_term),
                GroupTest.compound.ilike(like_term),
                Participation.name.ilike(like_term),
                User.username.ilike(like_term),
                User.email.ilike(like_term),
            )
        )

    return pending_query


def _queue_redirect_params():
    return {
        'status': (request.form.get('status') or request.args.get('status') or 'all').strip().lower(),
        'q': (request.form.get('q') or request.args.get('q') or '').strip(),
        'page': request.form.get('page') or request.args.get('page') or 1,
    }


@main_bp.route('/admin/action-queue')
@login_required
@admin_required
def action_queue():
    status_filter = (request.args.get('status') or 'all').strip().lower()
    search = (request.args.get('q') or '').strip()
    page = request.args.get('page', default=1, type=int) or 1
    per_page = 25
    if status_filter not in {'all', 'recruiting', 'testing', 'closed'}:
        status_filter = 'all'
    if page < 1:
        page = 1

    pending_query = _build_pending_queue_query(status_filter, search)
    pending_parts_pagination = pending_query.order_by(Participation.requested_at.asc(), GroupTest.start_date.asc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    return render_template(
        'admin/action_queue.html',
        pending_parts=pending_parts_pagination.items,
        pending_parts_pagination=pending_parts_pagination,
        status_filter=status_filter,
        search=search,
        page=page,
    )


@main_bp.route('/admin/action-queue/approve/<int:part_id>', methods=['POST'])
@login_required
@admin_required
def approve_from_queue(part_id):
    part = Participation.query.get_or_404(part_id)
    if part.approved:
        flash('Participant is already approved.', 'info')
        return redirect(url_for('main.action_queue', **_queue_redirect_params()))

    _approve_participation_record(part)
    _recalculate_approved_amounts_for_test(part.group_test)
    db.session.commit()
    flash(f'Approved {part.name or part.user.username}.', 'success')
    return redirect(url_for('main.action_queue', **_queue_redirect_params()))


@main_bp.route('/admin/action-queue/approve-selected', methods=['POST'])
@login_required
@admin_required
def approve_selected_from_queue():
    part_ids = request.form.getlist('part_ids')
    if not part_ids:
        flash('Select at least one pending participant to approve.', 'warning')
        return redirect(url_for('main.action_queue', **_queue_redirect_params()))

    valid_ids = _parse_participation_ids(part_ids)

    if not valid_ids:
        flash('No valid participants were selected.', 'warning')
        return redirect(url_for('main.action_queue', **_queue_redirect_params()))

    pending_parts = (
        Participation.query
        .filter(Participation.id.in_(valid_ids), Participation.approved == False, Participation.denied == False)
        .all()
    )

    if not pending_parts:
        flash('Selected participants were already approved or unavailable.', 'info')
        return redirect(url_for('main.action_queue', **_queue_redirect_params()))

    affected_test_ids = set()
    for part in pending_parts:
        _approve_participation_record(part)
        affected_test_ids.add(part.group_test_id)

    for test_id in affected_test_ids:
        test = GroupTest.query.get(test_id)
        if test:
            _recalculate_approved_amounts_for_test(test)

    db.session.commit()
    flash(f'Approved {len(pending_parts)} pending participant(s) across {len(affected_test_ids)} test(s).', 'success')
    return redirect(url_for('main.action_queue', **_queue_redirect_params()))


@main_bp.route('/admin/action-queue/approve-filtered', methods=['POST'])
@login_required
@admin_required
def approve_filtered_from_queue():
    status_filter = (request.form.get('status') or 'all').strip().lower()
    search = (request.form.get('q') or '').strip()
    confirm_text = (request.form.get('confirm_text') or '').strip()
    if status_filter not in {'all', 'recruiting', 'testing', 'closed'}:
        status_filter = 'all'

    if confirm_text != 'APPROVE FILTERED':
        flash('Bulk approve canceled. Type APPROVE FILTERED to continue.', 'warning')
        return redirect(url_for('main.action_queue', **_queue_redirect_params()))

    pending_parts = _build_pending_queue_query(status_filter, search).all()
    if not pending_parts:
        flash('No pending requests matched your current filters.', 'info')
        return redirect(url_for('main.action_queue', **_queue_redirect_params()))

    affected_test_ids = set()
    for part in pending_parts:
        _approve_participation_record(part)
        affected_test_ids.add(part.group_test_id)

    for test_id in affected_test_ids:
        test = GroupTest.query.get(test_id)
        if test:
            _recalculate_approved_amounts_for_test(test)

    db.session.commit()
    flash(
        f'Approved all filtered pending requests: {len(pending_parts)} participant(s) across {len(affected_test_ids)} test(s).',
        'success',
    )
    return redirect(url_for('main.action_queue', status=status_filter, q=search, page=1))


@main_bp.route('/admin/action-queue/deny/<int:part_id>', methods=['POST'])
@login_required
@admin_required
def deny_from_queue(part_id):
    part = Participation.query.get_or_404(part_id)
    if part.approved:
        flash('Approved participants cannot be denied from this queue.', 'warning')
        return redirect(url_for('main.action_queue', **_queue_redirect_params()))
    if part.denied:
        flash('This request is already denied.', 'info')
        return redirect(url_for('main.action_queue', **_queue_redirect_params()))

    deny_reason = (request.form.get('deny_reason') or '').strip()
    if not deny_reason:
        flash('A denial reason is required.', 'warning')
        return redirect(url_for('main.action_queue', **_queue_redirect_params()))

    name = part.name or part.user.username
    _deny_participation_record(part, deny_reason)
    db.session.commit()
    flash(f'Denied request for {name}.', 'success')
    return redirect(url_for('main.action_queue', **_queue_redirect_params()))


@main_bp.route('/admin/action-queue/deny-selected', methods=['POST'])
@login_required
@admin_required
def deny_selected_from_queue():
    part_ids = request.form.getlist('part_ids')
    if not part_ids:
        flash('Select at least one pending participant to deny.', 'warning')
        return redirect(url_for('main.action_queue', **_queue_redirect_params()))

    valid_ids = _parse_participation_ids(part_ids)
    if not valid_ids:
        flash('No valid participants were selected.', 'warning')
        return redirect(url_for('main.action_queue', **_queue_redirect_params()))

    deny_reason = (request.form.get('deny_reason') or '').strip()
    if not deny_reason:
        flash('A denial reason is required.', 'warning')
        return redirect(url_for('main.action_queue', **_queue_redirect_params()))

    pending_parts = Participation.query.filter(
        Participation.id.in_(valid_ids),
        Participation.approved == False,
        Participation.denied == False,
    ).all()
    if not pending_parts:
        flash('Selected participants were already approved or unavailable.', 'info')
        return redirect(url_for('main.action_queue', **_queue_redirect_params()))

    denied_count = len(pending_parts)
    for part in pending_parts:
        _deny_participation_record(part, deny_reason)

    db.session.commit()
    flash(f'Denied {denied_count} pending participant request(s).', 'success')
    return redirect(url_for('main.action_queue', **_queue_redirect_params()))


@main_bp.route('/admin/update-participant/<int:part_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def update_participant(part_id):
    part = Participation.query.get_or_404(part_id)
    test = part.group_test
    form = ParticipationEditForm(obj=part)
    
    if form.validate_on_submit():
        form.populate_obj(part)
        if form.approved.data and not part.approved:
            _approve_participation_record(part)
            # Auto-calculate owed on approval
            costs = test.calculate_costs()
            part.update_amount_owed(costs)
        elif not form.approved.data:
            part.approved = False
            part.approved_at = None
        
        db.session.commit()
        flash('Participant updated successfully.', 'success')
        return redirect(url_for('main.manage_participants', test_id=test.id))
    
    return render_template('admin/update_participant.html', form=form, part=part, test=test)


@main_bp.route('/admin/approve-request/<int:part_id>', methods=['POST'])
@login_required
@admin_required
def approve_request(part_id):
    """Quick approve endpoint (can be called from manage page)."""
    part = Participation.query.get_or_404(part_id)
    if not part.approved:
        _approve_participation_record(part)
        costs = part.group_test.calculate_costs()
        part.update_amount_owed(costs)
        db.session.commit()
        flash(f'Approved {part.name or part.user.username} for test.', 'success')
    return redirect(url_for('main.manage_participants', test_id=part.group_test_id))


@main_bp.route('/admin/manage-participants/<int:test_id>/deny/<int:part_id>', methods=['POST'])
@login_required
@admin_required
def deny_participant_from_manage(test_id, part_id):
    test = GroupTest.query.get_or_404(test_id)
    part = Participation.query.get_or_404(part_id)
    if part.group_test_id != test.id:
        abort(404)
    if part.approved:
        flash('Approved participants cannot be denied directly. Unapprove first if needed.', 'warning')
        return redirect(url_for('main.manage_participants', test_id=test.id))
    if part.denied:
        flash('This request is already denied.', 'info')
        return redirect(url_for('main.manage_participants', test_id=test.id))

    deny_reason = (request.form.get('deny_reason') or '').strip()
    if not deny_reason:
        flash('A denial reason is required.', 'warning')
        return redirect(url_for('main.manage_participants', test_id=test.id))

    _deny_participation_record(part, deny_reason)
    db.session.commit()
    flash(f'Denied request for {part.name or part.user.username}.', 'success')
    return redirect(url_for('main.manage_participants', test_id=test.id))


@main_bp.route('/admin/manage-participants/<int:test_id>/reopen/<int:part_id>', methods=['POST'])
@login_required
@admin_required
def reopen_participant_from_manage(test_id, part_id):
    test = GroupTest.query.get_or_404(test_id)
    part = Participation.query.get_or_404(part_id)
    if part.group_test_id != test.id:
        abort(404)
    if not part.denied:
        flash('Only denied requests can be reopened.', 'info')
        return redirect(url_for('main.manage_participants', test_id=test.id))

    _reopen_participation_record(part)
    db.session.commit()
    flash(f'Reopened request for {part.name or part.user.username}.', 'success')
    return redirect(url_for('main.manage_participants', test_id=test.id))


@main_bp.route('/admin/remove-participant/<int:part_id>', methods=['POST'])
@login_required
@admin_required
def remove_participant(part_id):
    """Remove a participant from a test when they should not be included."""
    part = Participation.query.get_or_404(part_id)
    test = part.group_test
    db.session.delete(part)
    db.session.commit()
    flash(f'Removed {part.name or part.user.username} from the test.', 'success')
    return redirect(url_for('main.manage_participants', test_id=test.id))


@main_bp.route('/admin/recalculate-costs/<int:test_id>', methods=['POST'])
@login_required
@admin_required
def recalculate_all_costs(test_id):
    """Recalculate and update amount_owed for all approved participants."""
    test = GroupTest.query.get_or_404(test_id)
    costs = test.calculate_costs()

    updated_count = 0
    for part in test.participations.filter_by(approved=True):
        if part.vial_donor:
            part.amount_owed = costs.get('donor_pays', 0)
        else:
            part.amount_owed = costs.get('non_donor_pays', 0)
        updated_count += 1

    db.session.commit()
    flash(f'Recalculated costs for {updated_count} approved participants.', 'success')
    return redirect(url_for('main.manage_participants', test_id=test_id))


@main_bp.route('/admin/add-participant/<int:test_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def add_participant_to_test(test_id):
    """Admin can add any existing user to a test (auto-approved)."""
    test = GroupTest.query.get_or_404(test_id)
    form = AddParticipantForm()

    # Users with active (not denied) records are already represented in this test.
    # Denied records remain eligible so admins can manually add/approve them later.
    existing_participant_ids = [
        p.user_id
        for p in test.participations.filter(Participation.denied == False).all()
    ]
    available_users = User.query.filter(User.id.notin_(existing_participant_ids)).all()

    form.user_id.choices = [(u.id, f"{u.username} ({u.email})") for u in available_users]

    if form.validate_on_submit():
        user = User.query.get(form.user_id.data)
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('main.add_participant_to_test', test_id=test_id))

        part = Participation.query.filter_by(group_test_id=test.id, user_id=user.id).first()
        if part:
            # Reuse prior denied row to preserve request history while restoring access.
            part.name = user.username
            part.tg_username = user.tg_username
            part.active = True
            part.approved = True
            part.approved_at = datetime.utcnow()
            part.denied = False
            part.denied_at = None
            part.denied_reason = None
        else:
            # Create participation with auto-approval
            part = Participation(
                group_test_id=test.id,
                user_id=user.id,
                name=user.username,
                tg_username=user.tg_username,
                approved=True,
                approved_at=datetime.utcnow(),
                denied=False,
                active=True
            )
            db.session.add(part)

        # Calculate initial owed amount
        costs = test.calculate_costs()
        part.update_amount_owed(costs)
        db.session.commit()
        flash(f'Added {user.username} to the test (auto-approved).', 'success')
        return redirect(url_for('main.manage_participants', test_id=test.id))

    return render_template('admin/add_participant.html', form=form, test=test)


# ==================== USER MANAGEMENT (Admin) ====================

@main_bp.route('/admin/notification-templates', methods=['GET', 'POST'])
@login_required
@admin_required
def notification_templates():
    form = NotificationTemplateForm()
    if form.validate_on_submit():
        template = NotificationTemplate(
            name=form.name.data,
            description=form.description.data,
            email_subject=form.email_subject.data,
            email_body=form.email_body.data,
            telegram_body=form.telegram_body.data,
            hide_from_participant_notifications=form.hide_from_participant_notifications.data,
            is_default_password_reset=form.is_default_password_reset.data,
            is_default_registration_welcome=form.is_default_registration_welcome.data,
            is_active=form.is_active.data,
        )
        db.session.add(template)
        db.session.commit()
        flash('Notification template created.', 'success')
        return redirect(url_for('main.notification_templates'))
    templates = NotificationTemplate.query.order_by(NotificationTemplate.name).all()
    return render_template('admin/notification_templates.html', form=form, templates=templates, editing_template=None)


@main_bp.route('/admin/notification-templates/<int:template_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_notification_template(template_id):
    template = NotificationTemplate.query.get_or_404(template_id)
    form = NotificationTemplateForm(obj=template)
    form.submit.label.text = 'Save Changes'

    if form.validate_on_submit():
        template.name = form.name.data
        template.description = form.description.data
        template.email_subject = form.email_subject.data
        template.email_body = form.email_body.data
        template.telegram_body = form.telegram_body.data
        template.hide_from_participant_notifications = form.hide_from_participant_notifications.data
        template.is_default_password_reset = form.is_default_password_reset.data
        template.is_default_registration_welcome = form.is_default_registration_welcome.data
        template.is_active = form.is_active.data
        db.session.commit()
        flash('Notification template updated.', 'success')
        return redirect(url_for('main.notification_templates'))

    templates = NotificationTemplate.query.order_by(NotificationTemplate.name).all()
    return render_template('admin/notification_templates.html', form=form, templates=templates, editing_template=template)


@main_bp.route('/admin/notification-config', methods=['GET', 'POST'])
@login_required
@admin_required
def notification_config():
    form = NotificationConfigForm()
    configs = {cfg.key: cfg.value for cfg in NotificationConfig.query.all()}
    existing_webhook_secret = str(configs.get('telegram_webhook_secret') or '').strip()
    existing_mailjet_api_key = str(configs.get('mailjet_api_key') or '').strip()
    existing_mailjet_secret_key = str(configs.get('mailjet_secret_key') or '').strip()
    existing_telegram_bot_token = str(configs.get('telegram_bot_token') or '').strip()

    if form.validate_on_submit():
        webhook_secret = (form.telegram_webhook_secret.data or '').strip()

        submitted_mailjet_api_key = (form.mailjet_api_key.data or '').strip()
        submitted_mailjet_secret_key = (form.mailjet_secret_key.data or '').strip()
        submitted_telegram_bot_token = (form.telegram_bot_token.data or '').strip()

        # Protect against masked placeholders being re-saved as real credentials.
        if submitted_mailjet_api_key == mask_secret(existing_mailjet_api_key):
            submitted_mailjet_api_key = existing_mailjet_api_key
        if submitted_mailjet_secret_key == mask_secret(existing_mailjet_secret_key):
            submitted_mailjet_secret_key = existing_mailjet_secret_key
        if submitted_telegram_bot_token == mask_secret(existing_telegram_bot_token):
            submitted_telegram_bot_token = existing_telegram_bot_token

        for key, value in {
            'mailjet_api_key': submitted_mailjet_api_key,
            'mailjet_secret_key': submitted_mailjet_secret_key,
            'mailjet_sender_email': form.mailjet_sender_email.data,
            'telegram_bot_token': submitted_telegram_bot_token,
            'telegram_bot_username': form.telegram_bot_username.data,
            'telegram_webhook_url': form.telegram_webhook_url.data,
            'telegram_webhook_allowed_ips': form.telegram_webhook_allowed_ips.data,
            'telegram_status_chat_id': form.telegram_status_chat_id.data,
            'telegram_digest_enabled': 'true' if form.telegram_digest_enabled.data else 'false',
            'telegram_digest_window_minutes': str(int(form.telegram_digest_window_minutes.data or 10)),
            'telegram_status_digest_header_template': form.telegram_status_digest_header_template.data,
            'telegram_status_digest_line_template': form.telegram_status_digest_line_template.data,
            'telegram_status_digest_participants_template': form.telegram_status_digest_participants_template.data,
            'telegram_status_new_test_template': form.telegram_status_new_test_template.data,
            'telegram_status_user_no_request_template': form.telegram_status_user_no_request_template.data,
            'telegram_status_user_denied_template': form.telegram_status_user_denied_template.data,
            'telegram_status_user_approved_template': form.telegram_status_user_approved_template.data,
            'telegram_status_user_pending_template': form.telegram_status_user_pending_template.data,
            'service_base_url': form.service_base_url.data,
            'notification_debug_enabled': 'true' if form.notification_debug_enabled.data else 'false',
        }.items():
            config = NotificationConfig.query.filter_by(key=key).first() or NotificationConfig(key=key)
            config.value = value or None
            db.session.add(config)

        if webhook_secret:
            config = NotificationConfig.query.filter_by(key='telegram_webhook_secret').first() or NotificationConfig(key='telegram_webhook_secret')
            config.value = webhook_secret
            db.session.add(config)
        elif not existing_webhook_secret:
            config = NotificationConfig.query.filter_by(key='telegram_webhook_secret').first() or NotificationConfig(key='telegram_webhook_secret')
            config.value = None
            db.session.add(config)

        db.session.commit()
        append_notification_log('configuration: credentials updated')
        flash('Notification configuration saved.', 'success')
        return redirect(url_for('main.notification_config'))

    if not form.is_submitted():
        form.mailjet_api_key.data = mask_secret(configs.get('mailjet_api_key'))
        form.mailjet_secret_key.data = mask_secret(configs.get('mailjet_secret_key'))
        form.mailjet_sender_email.data = configs.get('mailjet_sender_email')
        form.telegram_bot_token.data = mask_secret(configs.get('telegram_bot_token'))
        form.telegram_bot_username.data = configs.get('telegram_bot_username')
        form.telegram_webhook_url.data = configs.get('telegram_webhook_url')
        form.telegram_webhook_secret.data = ''
        form.telegram_webhook_allowed_ips.data = configs.get('telegram_webhook_allowed_ips')
        form.telegram_status_chat_id.data = configs.get('telegram_status_chat_id')
        form.telegram_digest_enabled.data = str(configs.get('telegram_digest_enabled', 'false')).lower() == 'true'
        try:
            form.telegram_digest_window_minutes.data = float(configs.get('telegram_digest_window_minutes') or 10)
        except (TypeError, ValueError):
            form.telegram_digest_window_minutes.data = 10
        form.telegram_status_digest_header_template.data = configs.get('telegram_status_digest_header_template')
        form.telegram_status_digest_line_template.data = configs.get('telegram_status_digest_line_template')
        form.telegram_status_digest_participants_template.data = configs.get('telegram_status_digest_participants_template')
        form.telegram_status_new_test_template.data = configs.get('telegram_status_new_test_template')
        form.telegram_status_user_no_request_template.data = configs.get('telegram_status_user_no_request_template')
        form.telegram_status_user_denied_template.data = configs.get('telegram_status_user_denied_template')
        form.telegram_status_user_approved_template.data = configs.get('telegram_status_user_approved_template')
        form.telegram_status_user_pending_template.data = configs.get('telegram_status_user_pending_template')
        form.service_base_url.data = configs.get('service_base_url')
        form.notification_debug_enabled.data = str(configs.get('notification_debug_enabled', 'false')).lower() == 'true'
    log_contents = read_notification_log()
    return render_template(
        'admin/notification_config.html',
        form=form,
        log_contents=log_contents,
        webhook_secret_mask=mask_secret(existing_webhook_secret),
        effective_telegram_webhook_url=_resolve_telegram_webhook_url(configs),
    )


@main_bp.route('/admin/notification-config/telegram-webhook/register', methods=['POST'])
@login_required
@admin_required
def register_telegram_webhook_action():
    configs = _config_values_map()
    bot_token = str(configs.get('telegram_bot_token') or '').strip()
    if not bot_token:
        flash('Telegram bot token is required before webhook registration.', 'danger')
        return redirect(url_for('main.notification_config'))

    webhook_url = _resolve_telegram_webhook_url(configs)
    if not webhook_url.lower().startswith('https://'):
        flash('Webhook URL must use https:// for Telegram to accept it.', 'danger')
        return redirect(url_for('main.notification_config'))

    secret = str(configs.get('telegram_webhook_secret') or '').strip() or None
    ok, response = register_telegram_webhook(webhook_url, secret_token=secret, drop_pending_updates=False)
    description = str((response or {}).get('description') or '')
    if ok:
        append_notification_log(f'telegram: webhook registered url={webhook_url}')
        flash('Telegram webhook registered successfully.', 'success')
    else:
        append_notification_log(f'telegram: webhook registration failed url={webhook_url} detail={description}')
        if '404' in description and 'Not Found' in description:
            flash('Telegram webhook registration failed: bot token appears invalid. Re-enter the full token from BotFather and save configuration, then retry.', 'danger')
        else:
            flash(f'Telegram webhook registration failed: {description or "Unknown error"}', 'danger')
    return redirect(url_for('main.notification_config'))


@main_bp.route('/admin/notification-config/telegram-webhook/unregister', methods=['POST'])
@login_required
@admin_required
def unregister_telegram_webhook_action():
    configs = _config_values_map()
    bot_token = str(configs.get('telegram_bot_token') or '').strip()
    if not bot_token:
        flash('Telegram bot token is required before webhook removal.', 'danger')
        return redirect(url_for('main.notification_config'))

    ok, response = unregister_telegram_webhook(drop_pending_updates=False)
    description = str((response or {}).get('description') or '')
    if ok:
        append_notification_log('telegram: webhook unregistered')
        flash('Telegram webhook unregistered successfully.', 'success')
    else:
        append_notification_log(f'telegram: webhook unregister failed detail={description}')
        flash(f'Telegram webhook removal failed: {description or "Unknown error"}', 'danger')
    return redirect(url_for('main.notification_config'))


@main_bp.route('/admin/payment-options', methods=['GET', 'POST'])
@login_required
@admin_required
def payment_options():
    form = PaymentOptionForm()
    if form.validate_on_submit():
        input_errors = _validate_payment_option_input(
            form.method_type.data,
            form.account_handle.data,
            form.wallet_address.data,
            form.qr_payload_override.data,
        )
        if input_errors:
            for err in input_errors:
                flash(err, 'danger')
            options = PaymentOption.query.order_by(PaymentOption.is_active.desc(), PaymentOption.label.asc(), PaymentOption.recipient_name.asc()).all()
            option_contexts = [_build_payment_option_context(option) for option in options]
            return render_template('admin/payment_options.html', form=form, options=options, option_contexts=option_contexts, matrix_rows=_payment_method_matrix_rows())

        option = PaymentOption(
            label=form.label.data,
            method_type=form.method_type.data,
            recipient_name=form.recipient_name.data or None,
            account_handle=form.account_handle.data or None,
            wallet_address=form.wallet_address.data or None,
            network=form.network.data or None,
            details=form.details.data or None,
            qr_payload_override=form.qr_payload_override.data or None,
            is_active=bool(form.is_active.data),
        )
        db.session.add(option)
        db.session.commit()
        flash('Payment option saved.', 'success')
        return redirect(url_for('main.payment_options'))

    options = PaymentOption.query.order_by(PaymentOption.is_active.desc(), PaymentOption.label.asc(), PaymentOption.recipient_name.asc()).all()
    option_contexts = [_build_payment_option_context(option) for option in options]
    return render_template(
        'admin/payment_options.html',
        form=form,
        options=options,
        option_contexts=option_contexts,
        matrix_rows=_payment_method_matrix_rows(),
    )


@main_bp.route('/admin/payment-options/<int:option_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_payment_option(option_id):
    option = PaymentOption.query.get_or_404(option_id)
    form = PaymentOptionForm(obj=option)
    form.submit.label.text = 'Save Changes'

    if form.validate_on_submit():
        input_errors = _validate_payment_option_input(
            form.method_type.data,
            form.account_handle.data,
            form.wallet_address.data,
            form.qr_payload_override.data,
        )
        if input_errors:
            for err in input_errors:
                flash(err, 'danger')
            return render_template('admin/edit_payment_option.html', form=form, option=option, matrix_rows=_payment_method_matrix_rows(), option_context=_build_payment_option_context(option))

        option.label = form.label.data
        option.method_type = form.method_type.data
        option.recipient_name = form.recipient_name.data or None
        option.account_handle = form.account_handle.data or None
        option.wallet_address = form.wallet_address.data or None
        option.network = form.network.data or None
        option.details = form.details.data or None
        option.qr_payload_override = form.qr_payload_override.data or None
        option.is_active = bool(form.is_active.data)
        db.session.commit()
        flash('Payment option updated.', 'success')
        return redirect(url_for('main.payment_options'))

    return render_template(
        'admin/edit_payment_option.html',
        form=form,
        option=option,
        matrix_rows=_payment_method_matrix_rows(),
        option_context=_build_payment_option_context(option),
    )


@main_bp.route('/admin/payment-options/<int:option_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_payment_option(option_id):
    option = PaymentOption.query.get_or_404(option_id)

    assigned_test_count = GroupTest.query.join(GroupTest.payment_options).filter(PaymentOption.id == option.id).count()
    participant_pref_count = Participation.query.filter_by(preferred_payment_option_id=option.id).count()

    if assigned_test_count > 0 or participant_pref_count > 0:
        option.is_active = False
        db.session.commit()
        flash(
            f'Payment option "{option.display_title()}" is in use and cannot be deleted. It was set inactive instead.',
            'warning',
        )
        return redirect(url_for('main.payment_options'))

    title = option.display_title()
    db.session.delete(option)
    db.session.commit()
    flash(f'Payment option "{title}" was deleted.', 'success')
    return redirect(url_for('main.payment_options'))


@main_bp.route('/admin/payment-options/<int:option_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_payment_option(option_id):
    option = PaymentOption.query.get_or_404(option_id)
    option.is_active = not option.is_active
    db.session.commit()
    flash(f'Payment option "{option.display_title()}" updated.', 'success')
    return redirect(url_for('main.payment_options'))


@main_bp.route('/admin/storage-config', methods=['GET', 'POST'])
@login_required
@admin_required
def storage_config():
    form = StorageConfigForm()
    configs = _config_values_map()

    existing_secret = str(configs.get('storage_secret_access_key') or '').strip()

    if form.validate_on_submit():
        enabled = bool(form.storage_enabled.data)
        provider = (form.storage_provider.data or 'aws').strip().lower()
        bucket = (form.storage_bucket.data or '').strip()
        access_key_id = (form.storage_access_key_id.data or '').strip()
        secret_access_key = (form.storage_secret_access_key.data or '').strip()
        region = (form.storage_region.data or '').strip()

        errors = []
        if enabled:
            if provider not in {'aws', 'do'}:
                errors.append('Provider must be AWS S3 or DigitalOcean Spaces.')
            if not bucket:
                errors.append('Bucket / Space name is required when storage is enabled.')
            if not region:
                errors.append('Region is required when storage is enabled.')
            if not access_key_id:
                errors.append('Access Key ID is required when storage is enabled.')
            if not secret_access_key and not existing_secret:
                errors.append('Secret Access Key is required when storage is enabled.')

        if errors:
            for err in errors:
                flash(err, 'danger')
        else:
            updates = {
                'storage_enabled': 'true' if enabled else 'false',
                'storage_provider': provider,
                'storage_bucket': bucket or None,
                'storage_region': region or None,
                'storage_endpoint_url': (form.storage_endpoint_url.data or '').strip() or None,
                'storage_access_key_id': access_key_id or None,
                'storage_path_prefix': (form.storage_path_prefix.data or 'result-images').strip() or 'result-images',
                'storage_public_base_url': (form.storage_public_base_url.data or '').strip() or None,
                'storage_make_public': 'true' if form.storage_make_public.data else 'false',
                'storage_force_path_style': 'true' if form.storage_force_path_style.data else 'false',
                'storage_signed_url_ttl_seconds': str(int(form.storage_signed_url_ttl_seconds.data or 60)),
                'storage_max_upload_size_mb': str(form.storage_max_upload_size_mb.data or 8),
                'storage_allowed_formats': (form.storage_allowed_formats.data or 'JPEG,PNG,WEBP,GIF,PDF').strip(),
            }
            for key, value in updates.items():
                _save_config_value(key, value)

            if secret_access_key:
                _save_config_value('storage_secret_access_key', secret_access_key)

            db.session.commit()
            flash('Storage configuration saved.', 'success')
            return redirect(url_for('main.storage_config'))

    if not form.is_submitted():
        form.storage_enabled.data = str(configs.get('storage_enabled', 'false')).lower() == 'true'
        form.storage_provider.data = (configs.get('storage_provider') or 'aws').lower()
        form.storage_bucket.data = configs.get('storage_bucket')
        form.storage_region.data = configs.get('storage_region')
        form.storage_endpoint_url.data = configs.get('storage_endpoint_url')
        form.storage_access_key_id.data = configs.get('storage_access_key_id')
        form.storage_secret_access_key.data = ''
        form.storage_path_prefix.data = configs.get('storage_path_prefix') or 'result-images'
        form.storage_public_base_url.data = configs.get('storage_public_base_url')
        form.storage_make_public.data = str(configs.get('storage_make_public', 'false')).lower() == 'true'
        form.storage_force_path_style.data = str(configs.get('storage_force_path_style', 'false')).lower() == 'true'
        try:
            form.storage_signed_url_ttl_seconds.data = float(configs.get('storage_signed_url_ttl_seconds') or 60)
        except (TypeError, ValueError):
            form.storage_signed_url_ttl_seconds.data = 60
        try:
            form.storage_max_upload_size_mb.data = float(configs.get('storage_max_upload_size_mb') or 8)
        except (TypeError, ValueError):
            form.storage_max_upload_size_mb.data = 8
        form.storage_allowed_formats.data = configs.get('storage_allowed_formats') or 'JPEG,PNG,WEBP,GIF,PDF'

    secret_mask = mask_secret(existing_secret)
    effective_settings = get_storage_settings()
    return render_template(
        'admin/storage_config.html',
        form=form,
        secret_mask=secret_mask,
        storage_enabled=effective_settings.get('enabled', False),
    )


@main_bp.route('/admin/users')
@login_required
@admin_required
def manage_users():
    """Admin page to view all users."""
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/manage_users.html', users=users)


@main_bp.route('/admin/users/new', methods=['GET', 'POST'])
@login_required
@admin_required
def create_user():
    """Admin creates a new user."""
    form = UserForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash('Username already exists.', 'danger')
            return render_template('admin/create_user.html', form=form)
        if User.query.filter_by(email=form.email.data).first():
            flash('Email already exists.', 'danger')
            return render_template('admin/create_user.html', form=form)

        user = User(
            username=form.username.data,
            email=form.email.data,
            tg_username=form.tg_username.data,
            is_admin=form.is_admin.data,
            is_active=form.is_active.data,
            receive_group_test_notifications=form.receive_group_test_notifications.data,
            notification_channel=form.notification_channel.data or 'email',
            digest_frequency=(form.digest_frequency.data or 'off').strip().lower(),
            digest_hourly_minute_utc=_clamp_int(form.digest_hourly_minute_utc.data, 0, 0, 59),
            digest_daily_hour_utc=_clamp_int(form.digest_daily_hour_utc.data, 9, 0, 23),
        )
        if form.password.data:
            user.set_password(form.password.data)
        else:
            import secrets
            temp_pass = secrets.token_urlsafe(12)
            user.set_password(temp_pass)
            flash('A temporary password was generated for the new user. Share it securely through a trusted channel.', 'warning')

        db.session.add(user)
        db.session.commit()
        flash(f'User "{user.username}" created successfully.', 'success')
        return redirect(url_for('main.manage_users'))

    return render_template('admin/create_user.html', form=form)


@main_bp.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    """Admin edits an existing user."""
    user = User.query.get_or_404(user_id)
    form = UserForm(obj=user)
    form.password.validators = [Optional(), Length(min=6)]

    if form.validate_on_submit():
        existing_username = User.query.filter(User.username == form.username.data, User.id != user_id).first()
        existing_email = User.query.filter(User.email == form.email.data, User.id != user_id).first()

        if existing_username:
            flash('Username already taken.', 'danger')
            return render_template('admin/edit_user.html', form=form, user=user)
        if existing_email:
            flash('Email already taken.', 'danger')
            return render_template('admin/edit_user.html', form=form, user=user)

        user.username = form.username.data
        user.email = form.email.data
        user.tg_username = form.tg_username.data
        user.is_admin = form.is_admin.data
        user.is_active = form.is_active.data
        user.receive_group_test_notifications = form.receive_group_test_notifications.data
        user.notification_channel = form.notification_channel.data or 'email'
        user.digest_frequency = (form.digest_frequency.data or 'off').strip().lower()
        user.digest_hourly_minute_utc = _clamp_int(form.digest_hourly_minute_utc.data, 0, 0, 59)
        user.digest_daily_hour_utc = _clamp_int(form.digest_daily_hour_utc.data, 9, 0, 23)

        if form.password.data:
            user.set_password(form.password.data)
            flash('Password updated.', 'success')

        db.session.commit()
        flash(f'User "{user.username}" updated.', 'success')
        return redirect(url_for('main.manage_users'))

    return render_template('admin/edit_user.html', form=form, user=user)


@main_bp.route('/admin/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def toggle_user_active(user_id):
    """Quick toggle active/inactive."""
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    status = "activated" if user.is_active else "deactivated"
    flash(f'User "{user.username}" {status}.', 'success')
    return redirect(url_for('main.manage_users'))


@main_bp.route('/admin/set-results/<int:test_id>', methods=['POST'])
@login_required
@admin_required
def set_results_link(test_id):
    """Quick update for results link when closing test."""
    test = GroupTest.query.get_or_404(test_id)
    previous_status = test.status
    link = request.form.get('results_link', '').strip()
    test.results_link = link if link else None
    if test.status != 'closed':
        test.status = 'closed'
    if test.results_link and not test.results_posted_at:
        test.results_posted_at = datetime.utcnow()

    if previous_status != test.status:
        _send_status_update_to_telegram(test, previous_status)

    db.session.commit()
    flash('Results link updated and test marked closed (if needed). Visible only to approved members.', 'success')
    return redirect(url_for('main.test_detail', test_id=test_id))


@main_bp.route('/admin/delete-test/<int:test_id>', methods=['POST'])
@login_required
@admin_required
def delete_test(test_id):
    test = GroupTest.query.get_or_404(test_id)
    title = test.title
    db.session.delete(test)
    db.session.commit()
    flash(f'Group test "{title}" was deleted.', 'warning')
    return redirect(url_for('main.dashboard'))


@main_bp.route('/admin/public-results', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_public_results():
    form = PublicResultForm()
    if form.validate_on_submit():
        item_results = parse_item_results(
            request.form.getlist('result_item_name'),
            request.form.getlist('result_item_value'),
        )
        uploaded_image_key = None
        upload_file = request.files.get('results_image')
        if upload_file and upload_file.filename:
            try:
                uploaded_image_key = upload_result_image(upload_file, 'public-results')
            except (StorageConfigurationError, StorageUploadError) as exc:
                flash(str(exc), 'danger')
                public_results = PublicResult.query.order_by(PublicResult.posted_at.desc()).all()
                return render_template(
                    'admin/public_results.html',
                    form=form,
                    public_results=public_results,
                    tag_suggestions=get_all_tag_names(),
                    storage_settings=get_storage_settings(),
                )

        result = PublicResult(
            title=form.title.data,
            summary=form.summary.data,
            results_link=form.results_link.data.strip(),
            results_image_key=uploaded_image_key,
            item_results=item_results,
            created_by=current_user.id,
        )
        db.session.add(result)
        db.session.flush()
        apply_tags_to_record(result, form.tag_names.data)
        db.session.commit()
        flash('Public result created.', 'success')
        return redirect(url_for('main.manage_public_results'))

    public_results = PublicResult.query.order_by(PublicResult.posted_at.desc()).all()
    return render_template(
        'admin/public_results.html',
        form=form,
        public_results=public_results,
        tag_suggestions=get_all_tag_names(),
        storage_settings=get_storage_settings(),
    )


@main_bp.route('/admin/public-results/<int:result_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_public_result(result_id):
    result = PublicResult.query.get_or_404(result_id)
    form = PublicResultForm(obj=result)
    form.submit.label.text = 'Save Changes'
    if not form.is_submitted():
        form.tag_names.data = result.tag_names()

    if form.validate_on_submit():
        result.item_results = parse_item_results(
            request.form.getlist('result_item_name'),
            request.form.getlist('result_item_value'),
        )
        result.title = form.title.data
        result.summary = form.summary.data
        result.results_link = form.results_link.data.strip()

        clear_existing_image = (request.form.get('clear_results_image') or '').lower() in {'1', 'true', 'on', 'yes'}
        upload_file = request.files.get('results_image')
        has_new_upload = bool(upload_file and upload_file.filename)
        if has_new_upload:
            try:
                new_key = upload_result_image(upload_file, 'public-results')
            except (StorageConfigurationError, StorageUploadError) as exc:
                flash(str(exc), 'danger')
                public_results = PublicResult.query.order_by(PublicResult.posted_at.desc()).all()
                return render_template(
                    'admin/public_results.html',
                    form=form,
                    public_results=public_results,
                    editing_result=result,
                    tag_suggestions=get_all_tag_names(),
                    storage_settings=get_storage_settings(),
                    editing_result_image_url=url_for('main.serve_public_result_image', result_id=result.id) if result.results_image_key else None,
                )

            old_key = result.results_image_key
            result.results_image_key = new_key
            if old_key and old_key != new_key:
                delete_result_image(old_key)
        elif clear_existing_image and result.results_image_key:
            old_key = result.results_image_key
            result.results_image_key = None
            delete_result_image(old_key)

        apply_tags_to_record(result, form.tag_names.data)
        db.session.commit()
        flash('Public result updated.', 'success')
        return redirect(url_for('main.manage_public_results'))

    public_results = PublicResult.query.order_by(PublicResult.posted_at.desc()).all()
    return render_template(
        'admin/public_results.html',
        form=form,
        public_results=public_results,
        editing_result=result,
        tag_suggestions=get_all_tag_names(),
        storage_settings=get_storage_settings(),
        editing_result_image_url=url_for('main.serve_public_result_image', result_id=result.id) if result.results_image_key else None,
    )


@main_bp.route('/admin/public-results/<int:result_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_public_result(result_id):
    result = PublicResult.query.get_or_404(result_id)
    title = result.title
    if result.results_image_key:
        delete_result_image(result.results_image_key)
    db.session.delete(result)
    db.session.commit()
    flash(f'Public result "{title}" was deleted.', 'warning')
    return redirect(url_for('main.manage_public_results'))


# ==================== API-ish for future (minimal) ====================

@main_bp.route('/api/test/<int:test_id>/costs')
@login_required
def api_costs(test_id):
    test = GroupTest.query.get_or_404(test_id)
    if not test.can_user_see(current_user):
        return jsonify({'error': 'forbidden'}), 403
    return jsonify(test.calculate_costs())


# ==================== EXPORT / BACKUP ====================

@main_bp.route('/test/<int:test_id>/export')
@login_required
def export_test(test_id):
    """Export full test data as .xlsx formatted like the original spreadsheet.
    Available to admins always. Available to approved members when test is closed.
    """
    test = GroupTest.query.get_or_404(test_id)
    is_member = test.participations.filter_by(user_id=current_user.id, approved=True).first() is not None

    if not (current_user.is_admin or (test.status == 'closed' and is_member)):
        abort(403)

    output = generate_test_export(test)
    filename = f"group_test_{test.id}_{test.compound or 'backup'}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )