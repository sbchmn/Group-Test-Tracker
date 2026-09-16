"""
SQLAlchemy Models for Group Test Manager
- Clean relationships and constraints.
- Properties for dashboard visibility and cost calculations (no magic numbers).
- Password security via Werkzeug.
- JSON field for flexible lab_test_details (matches original spreadsheet's multiple tests).
"""

from datetime import datetime
from flask_login import UserMixin
from . import db
import json
from urllib.parse import quote


group_test_tags = db.Table(
    'group_test_tags',
    db.Column('group_test_id', db.Integer, db.ForeignKey('group_tests.id', ondelete='CASCADE'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True),
)


public_result_tags = db.Table(
    'public_result_tags',
    db.Column('public_result_id', db.Integer, db.ForeignKey('public_results.id', ondelete='CASCADE'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True),
)


group_test_payment_options = db.Table(
    'group_test_payment_options',
    db.Column('group_test_id', db.Integer, db.ForeignKey('group_tests.id', ondelete='CASCADE'), primary_key=True),
    db.Column('payment_option_id', db.Integer, db.ForeignKey('payment_options.id', ondelete='CASCADE'), primary_key=True),
)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    tg_username = db.Column(db.String(80), nullable=True, index=True)
    discord_username = db.Column(db.String(80), nullable=True, index=True)
    telegram_user_id = db.Column(db.String(40), nullable=True, unique=True, index=True)
    telegram_chat_id = db.Column(db.String(80), nullable=True, index=True)
    discord_user_id = db.Column(db.String(40), nullable=True, unique=True, index=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    receive_group_test_notifications = db.Column(db.Boolean, default=True, nullable=False)
    notification_channel = db.Column(db.String(20), default='email', nullable=False)
    digest_frequency = db.Column(db.String(20), default='off', nullable=False)
    digest_hourly_minute_utc = db.Column(db.Integer, default=0, nullable=False)
    digest_daily_hour_utc = db.Column(db.Integer, default=9, nullable=False)
    digest_last_sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    participations = db.relationship(
        'Participation', 
        backref='user', 
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    hidden_dashboard_tests = db.relationship(
        'DashboardHiddenGroupTest',
        backref='user',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    telegram_link_tokens = db.relationship(
        'TelegramLinkToken',
        backref='user',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    discord_link_tokens = db.relationship(
        'DiscordLinkToken',
        backref='user',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    digest_events = db.relationship(
        'UserDigestEvent',
        backref='user',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    
    def set_password(self, password: str):
        """Hash password using Werkzeug (scrypt or pbkdf2, strong defaults)."""
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password, method='scrypt', salt_length=16)
    
    def check_password(self, password: str) -> bool:
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'


class Tag(db.Model):
    __tablename__ = 'tags'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True, index=True)
    normalized_name = db.Column(db.String(120), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<Tag {self.name}>'


class DashboardHiddenGroupTest(db.Model):
    __tablename__ = 'dashboard_hidden_group_tests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    group_test_id = db.Column(db.Integer, db.ForeignKey('group_tests.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'group_test_id', name='_dashboard_hidden_user_test_uc'),
    )


class PublicResult(db.Model):
    __tablename__ = 'public_results'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    summary = db.Column(db.Text, nullable=True)
    results_link = db.Column(db.String(500), nullable=True)
    results_image_key = db.Column(db.String(500), nullable=True)
    item_results = db.Column(db.JSON, nullable=True)
    posted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    publication_status = db.Column(db.String(20), nullable=False, default='published', index=True)
    submission_platform = db.Column(db.String(20), nullable=True)
    submission_chat_id = db.Column(db.String(120), nullable=True)
    submission_thread_id = db.Column(db.String(80), nullable=True)
    submission_message_id = db.Column(db.String(80), nullable=True)
    review_message_id = db.Column(db.String(80), nullable=True)
    review_state_json = db.Column(db.JSON, nullable=True)

    tags = db.relationship(
        'Tag',
        secondary=public_result_tags,
        lazy='select',
        order_by='Tag.name',
    )

    def set_tags(self, tags):
        self.tags = tags

    def tag_names(self):
        return ', '.join(tag.name for tag in self.tags)

    def __repr__(self):
        return f'<PublicResult {self.title}>'


class ResultAnalysisRun(db.Model):
    __tablename__ = 'result_analysis_runs'

    id = db.Column(db.Integer, primary_key=True)
    group_test_id = db.Column(db.Integer, db.ForeignKey('group_tests.id', ondelete='CASCADE'), nullable=True, index=True)
    public_result_id = db.Column(db.Integer, db.ForeignKey('public_results.id', ondelete='CASCADE'), nullable=True, index=True)
    source_kind = db.Column(db.String(20), nullable=False)
    source_reference = db.Column(db.String(500), nullable=False)
    source_sha256 = db.Column(db.String(64), nullable=True, index=True)
    source_content_type = db.Column(db.String(100), nullable=True)
    source_size_bytes = db.Column(db.Integer, nullable=True)
    provider = db.Column(db.String(20), nullable=False)
    provider_model = db.Column(db.String(120), nullable=False)
    schema_version = db.Column(db.String(20), nullable=False, default='1')
    bypass_duplicate_check = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(30), nullable=False, default='queued', index=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    next_attempt_at = db.Column(db.DateTime, nullable=True, index=True)
    lease_token = db.Column(db.String(64), nullable=True, index=True)
    lease_expires_at = db.Column(db.DateTime, nullable=True, index=True)
    error_code = db.Column(db.String(60), nullable=True)
    error_message = db.Column(db.String(500), nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)
    usage_json = db.Column(db.JSON, nullable=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    queued_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    findings = db.relationship(
        'ResultAnalysisFinding',
        backref='run',
        lazy='select',
        cascade='all, delete-orphan',
        order_by='ResultAnalysisFinding.id',
    )
    group_test = db.relationship('GroupTest', backref=db.backref('analysis_runs', lazy='dynamic', cascade='all, delete-orphan'))
    public_result = db.relationship('PublicResult', backref=db.backref('analysis_runs', lazy='dynamic', cascade='all, delete-orphan'))
    requested_by = db.relationship('User', foreign_keys=[requested_by_id])
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id])

    __table_args__ = (
        db.CheckConstraint(
            '(group_test_id IS NOT NULL AND public_result_id IS NULL) OR '
            '(group_test_id IS NULL AND public_result_id IS NOT NULL)',
            name='ck_result_analysis_exactly_one_target',
        ),
        db.CheckConstraint("source_kind IN ('upload', 'link')", name='ck_result_analysis_source_kind'),
        db.CheckConstraint(
            "status IN ('queued', 'analyzing', 'needs_review', 'applied', 'failed', 'superseded')",
            name='ck_result_analysis_status',
        ),
        db.CheckConstraint("provider IN ('openai', 'xai', 'anthropic')", name='ck_result_analysis_provider'),
        db.Index('ix_result_analysis_status_queue', 'status', 'next_attempt_at', 'queued_at'),
    )

    @property
    def target(self):
        return self.group_test or self.public_result


class ResultAnalysisFinding(db.Model):
    __tablename__ = 'result_analysis_findings'

    id = db.Column(db.Integer, primary_key=True)
    analysis_run_id = db.Column(db.Integer, db.ForeignKey('result_analysis_runs.id', ondelete='CASCADE'), nullable=False, index=True)
    canonical_type = db.Column(db.String(80), nullable=True, index=True)
    source_label = db.Column(db.String(200), nullable=False)
    reported_value = db.Column(db.String(500), nullable=False)
    evidence_text = db.Column(db.String(1000), nullable=False)
    page_number = db.Column(db.Integer, nullable=True)
    confidence = db.Column(db.Float, nullable=False)
    is_reported_aggregate = db.Column(db.Boolean, nullable=False, default=False)
    proposed_action = db.Column(db.String(20), nullable=False)
    target_row_key = db.Column(db.String(120), nullable=True)
    review_decision = db.Column(db.String(20), nullable=False, default='pending')
    reviewed_value = db.Column(db.String(500), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.CheckConstraint(
            "proposed_action IN ('fill', 'create', 'conflict', 'unrecognized')",
            name='ck_result_analysis_finding_action',
        ),
        db.CheckConstraint(
            "review_decision IN ('pending', 'accepted', 'rejected')",
            name='ck_result_analysis_finding_review',
        ),
        db.CheckConstraint('confidence >= 0 AND confidence <= 1', name='ck_result_analysis_confidence'),
    )


class NotificationTemplate(db.Model):
    __tablename__ = 'notification_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)
    email_subject = db.Column(db.String(200), nullable=True)
    email_body = db.Column(db.Text, nullable=True)
    telegram_body = db.Column(db.Text, nullable=True)
    hide_from_participant_notifications = db.Column(db.Boolean, default=False, nullable=False)
    is_default_password_reset = db.Column(db.Boolean, default=False, nullable=False)
    is_default_registration_welcome = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class TelegramCommandTemplate(db.Model):
    __tablename__ = 'telegram_command_templates'

    id = db.Column(db.Integer, primary_key=True)
    command = db.Column(db.String(40), nullable=False, unique=True, index=True)
    category = db.Column(db.String(80), nullable=True, index=True)
    description = db.Column(db.Text, nullable=True)
    reply_text = db.Column(db.Text, nullable=False)
    response_image_key = db.Column(db.String(500), nullable=True)
    allow_admin_bot_updates = db.Column(db.Boolean, default=False, nullable=False)
    args_policy = db.Column(db.String(20), nullable=False, default='any')
    args_regex = db.Column(db.String(500), nullable=True)
    args_help_text = db.Column(db.Text, nullable=True)
    rate_limit_window_seconds = db.Column(db.Integer, nullable=True)
    rate_limit_max_calls = db.Column(db.Integer, nullable=True)
    rate_limit_message = db.Column(db.Text, nullable=True)
    allow_non_private = db.Column(db.Boolean, default=False, nullable=False)
    allowed_chat_ids = db.Column(db.Text, nullable=True)
    allowed_thread_ids = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    invocations = db.relationship(
        'TelegramCommandInvocation',
        backref='template',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )


class BotCommandMessage(db.Model):
    __tablename__ = 'bot_command_messages'

    id = db.Column(db.Integer, primary_key=True)
    command_template_id = db.Column(db.Integer, db.ForeignKey('telegram_command_templates.id', ondelete='CASCADE'), nullable=False, index=True)
    provider = db.Column(db.String(30), nullable=False, index=True)
    chat_id = db.Column(db.String(120), nullable=False, index=True)
    message_id = db.Column(db.String(120), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint('provider', 'chat_id', 'message_id', name='_bot_command_provider_message_uc'),
    )


class TelegramCommandInvocation(db.Model):
    __tablename__ = 'telegram_command_invocations'

    id = db.Column(db.Integer, primary_key=True)
    command_template_id = db.Column(db.Integer, db.ForeignKey('telegram_command_templates.id', ondelete='CASCADE'), nullable=False, index=True)
    chat_id = db.Column(db.String(80), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class DiscordCommandInvocation(db.Model):
    __tablename__ = 'discord_command_invocations'

    id = db.Column(db.Integer, primary_key=True)
    command_template_id = db.Column(db.Integer, db.ForeignKey('telegram_command_templates.id', ondelete='CASCADE'), nullable=False, index=True)
    channel_id = db.Column(db.String(80), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class NotificationConfig(db.Model):
    __tablename__ = 'notification_configs'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), nullable=False, unique=True, index=True)
    value = db.Column(db.Text, nullable=True)


class TelegramLinkToken(db.Model):
    __tablename__ = 'telegram_link_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    token = db.Column(db.String(120), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def is_active(self):
        return self.used_at is None and self.expires_at >= datetime.utcnow()


class DiscordLinkToken(db.Model):
    __tablename__ = 'discord_link_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    token = db.Column(db.String(120), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def is_active(self):
        return self.used_at is None and self.expires_at >= datetime.utcnow()


class TelegramWebhookUpdate(db.Model):
    __tablename__ = 'telegram_webhook_updates'

    id = db.Column(db.Integer, primary_key=True)
    update_id = db.Column(db.BigInteger, nullable=False, unique=True, index=True)
    source_ip = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ControlPlaneNonce(db.Model):
    """Replay defense for signed SaaS control-plane requests (cp_to_instance)."""
    __tablename__ = 'control_plane_nonces'

    id = db.Column(db.Integer, primary_key=True)
    nonce_digest = db.Column(db.String(64), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ControlPlaneOperationReceipt(db.Model):
    """Idempotency record so a retried control-plane operation is not reapplied."""
    __tablename__ = 'control_plane_operation_receipts'

    id = db.Column(db.Integer, primary_key=True)
    operation_id = db.Column(db.String(160), nullable=False, unique=True, index=True)
    payload_digest = db.Column(db.String(64), nullable=False)
    response_code = db.Column(db.Integer, nullable=False)
    response_body = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class TelegramStatusDigestEvent(db.Model):
    __tablename__ = 'telegram_status_digest_events'

    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(120), nullable=False, index=True)
    window_bucket = db.Column(db.String(32), nullable=False, index=True)
    event_key = db.Column(db.String(120), nullable=False, index=True)
    test_id = db.Column(db.Integer, nullable=False, index=True)
    test_title = db.Column(db.String(200), nullable=False)
    old_status = db.Column(db.String(20), nullable=False)
    new_status = db.Column(db.String(20), nullable=False)
    mention_usernames = db.Column(db.Text, nullable=True)
    mention_user_ids = db.Column(db.Text, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('chat_id', 'window_bucket', 'event_key', name='_tg_digest_chat_window_event_uc'),
    )


class UserDigestEvent(db.Model):
    __tablename__ = 'user_digest_events'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    test_id = db.Column(db.Integer, nullable=False, index=True)
    test_title = db.Column(db.String(200), nullable=False)
    old_status = db.Column(db.String(20), nullable=False)
    new_status = db.Column(db.String(20), nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class PaymentOption(db.Model):
    __tablename__ = 'payment_options'

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(120), nullable=False)
    method_type = db.Column(db.String(40), nullable=False, index=True)
    recipient_name = db.Column(db.String(120), nullable=True)
    account_handle = db.Column(db.String(200), nullable=True)
    wallet_address = db.Column(db.String(255), nullable=True)
    network = db.Column(db.String(120), nullable=True)
    details = db.Column(db.Text, nullable=True)
    qr_payload_override = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def display_title(self):
        if self.recipient_name:
            return f"{self.label} ({self.recipient_name})"
        return self.label

    @staticmethod
    def _brand_for_method(method):
        method = (method or '').strip().lower()
        brands = {
            'venmo': {
                'provider_name': 'Venmo',
                'icon_class': 'bi bi-wallet2',
                'badge_class': 'text-bg-primary',
            },
            'cashapp': {
                'provider_name': 'Cash App',
                'icon_class': 'bi bi-cash-coin',
                'badge_class': 'text-bg-success',
            },
            'paypal': {
                'provider_name': 'PayPal',
                'icon_class': 'bi bi-paypal',
                'badge_class': 'text-bg-info',
            },
            'crypto': {
                'provider_name': 'Crypto Wallet',
                'icon_class': 'bi bi-currency-bitcoin',
                'badge_class': 'text-bg-warning',
            },
            'other': {
                'provider_name': 'Other',
                'icon_class': 'bi bi-credit-card-2-front',
                'badge_class': 'text-bg-secondary',
            },
        }
        return brands.get(method, brands['other'])

    @staticmethod
    def _crypto_scheme_for_network(network):
        network_key = str(network or '').strip().lower().replace('-', '').replace('_', '').replace(' ', '')
        mapping = {
            'btc': 'bitcoin',
            'bitcoin': 'bitcoin',
            'ltc': 'litecoin',
            'litecoin': 'litecoin',
            'bch': 'bitcoincash',
            'bitcoincash': 'bitcoincash',
            'eth': 'ethereum',
            'ethereum': 'ethereum',
            'erc20': 'ethereum',
            'arbitrum': 'ethereum',
            'optimism': 'ethereum',
            'base': 'ethereum',
            'polygon': 'ethereum',
            'matic': 'ethereum',
            'sol': 'solana',
            'solana': 'solana',
            'trx': 'tron',
            'tron': 'tron',
            'bnb': 'binance',
            'binance': 'binance',
        }
        return mapping.get(network_key, 'crypto')

    def to_payment_profile(self):
        method = (self.method_type or '').strip().lower()
        handle = (self.account_handle or '').strip()
        wallet = (self.wallet_address or '').strip()
        network = (self.network or '').strip()
        override = (self.qr_payload_override or '').strip()

        brand = self._brand_for_method(method)
        profile = {
            'provider_name': brand['provider_name'],
            'icon_class': brand['icon_class'],
            'badge_class': brand['badge_class'],
            'destination_label': 'Destination',
            'destination_value': '',
            'payment_link': '',
            'qr_payload': '',
            'link_type': 'none',
            'mobile_action_label': 'Open payment app',
            'desktop_action_label': 'Open payment page',
            'copy_value': '',
        }

        if method == 'venmo':
            normalized = handle.lstrip('@').strip()
            if normalized:
                encoded = quote(normalized, safe='._-')
                profile['destination_label'] = 'Venmo Handle'
                profile['destination_value'] = f"@{normalized}"
                profile['payment_link'] = f"https://venmo.com/{encoded}"
                profile['qr_payload'] = profile['payment_link']
                profile['link_type'] = 'web'

        elif method == 'cashapp':
            normalized = handle.lstrip('@$').strip()
            if normalized:
                encoded = quote(normalized, safe='._-')
                profile['destination_label'] = 'Cash App Cashtag'
                profile['destination_value'] = f"${normalized}"
                profile['payment_link'] = f"https://cash.app/${encoded}"
                profile['qr_payload'] = profile['payment_link']
                profile['link_type'] = 'web'

        elif method == 'paypal':
            normalized = handle.strip('/').strip()
            if normalized:
                encoded = quote(normalized, safe='._-')
                profile['destination_label'] = 'PayPal Username'
                profile['destination_value'] = normalized
                profile['payment_link'] = f"https://paypal.me/{encoded}"
                profile['qr_payload'] = profile['payment_link']
                profile['link_type'] = 'web'

        elif method == 'crypto':
            if wallet:
                scheme = self._crypto_scheme_for_network(network)
                profile['destination_label'] = 'Wallet Address'
                profile['destination_value'] = wallet
                if scheme == 'crypto':
                    profile['payment_link'] = f"crypto:{wallet}"
                else:
                    profile['payment_link'] = f"{scheme}:{wallet}"
                profile['qr_payload'] = profile['payment_link']
                profile['link_type'] = 'uri'
                profile['mobile_action_label'] = 'Open wallet'
                profile['desktop_action_label'] = 'Copy wallet URI'

        else:
            candidate = handle or wallet
            if candidate:
                profile['destination_label'] = 'Destination'
                profile['destination_value'] = candidate
                if candidate.lower().startswith(('http://', 'https://')):
                    profile['payment_link'] = candidate
                    profile['qr_payload'] = candidate
                    profile['link_type'] = 'web'
                else:
                    profile['qr_payload'] = candidate

        if override:
            profile['qr_payload'] = override
            if not profile['payment_link'] and override.lower().startswith(('http://', 'https://', 'bitcoin:', 'ethereum:', 'solana:', 'tron:', 'litecoin:', 'bitcoincash:', 'binance:', 'crypto:')):
                profile['payment_link'] = override
                profile['link_type'] = 'web' if override.lower().startswith(('http://', 'https://')) else 'uri'

        if not profile['destination_value']:
            profile['destination_value'] = handle or wallet
        profile['copy_value'] = profile['payment_link'] or profile['destination_value'] or profile['qr_payload']

        return profile

    def to_qr_payload(self):
        return self.to_payment_profile().get('qr_payload') or ''

    def __repr__(self):
        return f'<PaymentOption {self.id} {self.label}>'


class GroupTest(db.Model):
    __tablename__ = 'group_tests'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    
    # Original spreadsheet fields
    vendor = db.Column(db.String(120), nullable=True)
    batch_number = db.Column(db.String(100), nullable=True)
    compound = db.Column(db.String(100), nullable=True)
    size = db.Column(db.String(50), nullable=True)  # e.g. "10x 10mg vials"
    
    status = db.Column(db.String(20), default='recruiting', nullable=False, index=True)
    # Allowed: recruiting, testing, ready_for_payment, closed
    
    # Lab testing costs and provider details
    lab_name = db.Column(db.String(200), nullable=True)
    # Example: [{"name": "MASS, PURITY + ID", "price": 360.0, "vials_needed": 1}, {"name": "STERILITY", "price": 290.0, "vials_needed": 0}]
    lab_test_details = db.Column(db.JSON, nullable=True)
    total_lab_cost = db.Column(db.Float, default=0.0, nullable=False)
    shipping_cost = db.Column(db.Float, default=0.0, nullable=False)  # Shipment to lab
    donor_shipping_cost = db.Column(db.Float, default=0.0, nullable=False)  # Shipment from donor(s) to organizer
    donor_shipping_reimbursement = db.Column(db.String(40), default='credit', nullable=False)  # credit or participant
    donor_shipping_reimbursed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Admin tracking
    order_number = db.Column(db.String(100), nullable=True)
    quote_number = db.Column(db.String(100), nullable=True)
    
    # Results - only shown to approved participants when status == 'closed'
    results_link = db.Column(db.String(500), nullable=True)
    results_image_key = db.Column(db.String(500), nullable=True)
    results_posted_at = db.Column(db.DateTime, nullable=True)
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Configurable refund (from original INPUTS row)
    refund_per_donor = db.Column(db.Float, default=20.0, nullable=False)
    
    # Relationships
    participations = db.relationship(
        'Participation', 
        backref='group_test', 
        lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='Participation.requested_at'
    )
    tags = db.relationship(
        'Tag',
        secondary=group_test_tags,
        lazy='select',
        order_by='Tag.name',
    )
    payment_options = db.relationship(
        'PaymentOption',
        secondary=group_test_payment_options,
        lazy='select',
        order_by='PaymentOption.label',
    )

    def set_tags(self, tags):
        self.tags = tags

    def tag_names(self):
        return ', '.join(tag.name for tag in self.tags)

    def primary_tag(self):
        return self.tags[0].name if self.tags else ''
    
    @property
    def approved_participations(self):
        """Query helper for approved only."""
        return self.participations.filter_by(approved=True)
    
    @property
    def num_approved(self) -> int:
        return self.approved_participations.count()
    
    @property
    def num_donors(self) -> int:
        return self.approved_participations.filter_by(vial_donor=True).count()
    
    @property
    def num_non_donors(self) -> int:
        return self.num_approved - self.num_donors
    
    def calculate_costs(self):
        """
        Rigorous cost calculation logic matching & improving on original spreadsheet.
        
        Assumptions (documented for transparency & auditability):
        - Total fixed costs = lab + shipping.
        - Donors (vial providers) receive a fixed refund_per_donor credit (admin configurable, default $20).
        - To keep pool fair: non-donors pay a small uplift to fund the donor refunds.
        - Edge cases handled: 0 participants, 0 donors, 0 non-donors.
        
        Returns dict with all values for templates + admin views.
        """
        n_part = self.num_approved
        n_donors = self.num_donors
        n_non = self.num_non_donors
        
        total_fixed = (self.total_lab_cost or 0.0) + (self.shipping_cost or 0.0) + (self.donor_shipping_cost or 0.0)
        refund_per = self.refund_per_donor or 0.0
        total_refund_pool = refund_per * n_donors if n_donors > 0 else 0.0
        donor_shipping_cost = self.donor_shipping_cost or 0.0
        
        if n_part == 0:
            return {
                'total_participants': 0,
                'total_donors': 0,
                'total_non_donors': 0,
                'total_fixed_cost': round(total_fixed, 2),
                'total_refund_pool': round(total_refund_pool, 2),
                'donor_shipping_cost': round(self.donor_shipping_cost or 0.0, 2),
                'base_per_person': 0.0,
                'donor_pays': 0.0,
                'non_donor_pays': 0.0,
                'effective_donor_refund': round(refund_per, 2),
                'message': 'No approved participants yet.'
            }
        
        # Base share of fixed costs
        base_share = total_fixed / n_part
        
        if n_non == 0:
            # If there are no non-donors, the donor still receives the refund credit as a negative balance.
            donor_pays = round(base_share - refund_per, 2)
            non_donor_pays = 0.0
        else:
            # Non-donors fund the refund pool via uplift, and donors can end up with a negative balance
            # when the refund exceeds their base share.
            uplift_per_non = total_refund_pool / n_non if n_non > 0 else 0.0
            non_donor_pays = round(base_share + uplift_per_non, 2)
            donor_pays = round(base_share - refund_per, 2)

        if donor_shipping_cost > 0 and self.donor_shipping_reimbursement == 'credit' and n_donors > 0:
            donor_pays = round(donor_pays - donor_shipping_cost / n_donors, 2)
        
        return {
            'total_participants': n_part,
            'total_donors': n_donors,
            'total_non_donors': n_non,
            'total_fixed_cost': round(total_fixed, 2),
            'total_refund_pool': round(total_refund_pool, 2),
            'base_per_person': round(base_share, 2),
            'donor_pays': donor_pays,
            'non_donor_pays': non_donor_pays,
            'effective_donor_refund': round(refund_per, 2),
            'message': None
        }
    
    def can_user_see(self, user) -> bool:
        """Visibility rule exactly as specified."""
        if user.is_admin:
            return True
        if self.status == 'recruiting':
            return True
        # member-only phases: only approved participants
        if self.status in ('testing', 'ready_for_payment', 'closed'):
            return self.participations.filter_by(user_id=user.id, approved=True).first() is not None
        return False

    def is_hidden_for_user(self, user) -> bool:
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        return DashboardHiddenGroupTest.query.filter_by(user_id=user.id, group_test_id=self.id).first() is not None
    
    def __repr__(self):
        return f'<GroupTest {self.id} {self.title} [{self.status}]>'


class Participation(db.Model):
    """
    Join/Participation record. Created on request (approved=False), promoted by admin.
    Captures all original spreadsheet columns + payment tracking.
    """
    __tablename__ = 'participations'
    __table_args__ = (
        db.UniqueConstraint('group_test_id', 'user_id', name='_group_test_user_uc'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    group_test_id = db.Column(db.Integer, db.ForeignKey('group_tests.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Core participant data (from request form + admin edits)
    name = db.Column(db.String(120), nullable=True)
    tg_username = db.Column(db.String(80), nullable=True)
    verified = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    order_status = db.Column(db.String(50), default='pending')  # pending, ordered, received, etc.
    us_based = db.Column(db.Boolean, default=True)
    vial_donor = db.Column(db.Boolean, default=False)
    state = db.Column(db.String(50), nullable=True)
    pay_vial_collector = db.Column(db.Boolean, default=False)
    pay_lab = db.Column(db.Boolean, default=False)
    paid_lab = db.Column(db.Boolean, default=False)          # Admin verification
    
    # Financial tracking (admin or future auto)
    amount_owed = db.Column(db.Float, default=0.0)
    amount_paid = db.Column(db.Float, default=0.0)           # Self-reported by participant
    preferred_payment_option_id = db.Column(db.Integer, db.ForeignKey('payment_options.id'), nullable=True)
    preferred_payment_snapshot = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    
    requested_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    approved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    denied = db.Column(db.Boolean, default=False, nullable=False, index=True)
    denied_at = db.Column(db.DateTime, nullable=True)
    denied_reason = db.Column(db.Text, nullable=True)

    preferred_payment_option = db.relationship('PaymentOption', lazy='joined')
    
    def update_amount_owed(self, costs_dict):
        """Helper to sync individual owed based on role (donor vs non). Call after approve or recalc."""
        if self.vial_donor:
            self.amount_owed = costs_dict.get('donor_pays', 0.0)
        else:
            self.amount_owed = costs_dict.get('non_donor_pays', 0.0)
    
    def __repr__(self):
        return f'<Participation user={self.user_id} test={self.group_test_id} approved={self.approved}>'
