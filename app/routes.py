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
    FloatField, DateField, SelectField, SubmitField, FieldList, FormField
)
from wtforms.validators import DataRequired, Email, Length, Optional, NumberRange, EqualTo, URL
from datetime import datetime, date
from functools import wraps
from itertools import zip_longest
from sqlalchemy import or_

from . import db
import os

from .models import User, GroupTest, Participation, NotificationTemplate, NotificationConfig, Tag, PublicResult, DashboardHiddenGroupTest
from .export import generate_test_export
from .notifications import append_notification_log, read_notification_log, send_password_reset, send_group_test_notification, render_notification_template, send_notification_message

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
    password = PasswordField('New Password (leave blank to keep current)', validators=[Optional(), Length(min=6)])
    submit = SubmitField('Save User')


class ProfileForm(FlaskForm):
    """Form for users to edit their own profile details."""
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    tg_username = StringField('Telegram Username', validators=[Optional(), Length(max=80)])
    receive_group_test_notifications = BooleanField('Receive Group Test Notifications?', default=True)
    notification_channel = SelectField('Notify via', choices=[('email', 'Email'), ('telegram', 'Telegram')], default='email')
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
    service_base_url = StringField('Service Base URL', validators=[Optional(), URL(require_tld=False)])
    notification_debug_enabled = BooleanField('Enable debug-level notification logs')
    submit = SubmitField('Save Configuration')


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


def mask_secret(value, reveal_prefix=4, reveal_suffix=6):
    if not value:
        return ''
    value = str(value)
    if len(value) <= reveal_prefix + reveal_suffix:
        return value
    return f"{value[:reveal_prefix]}{'*' * (len(value) - reveal_prefix - reveal_suffix)}{value[-reveal_suffix:]}"


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
            new_password = os.urandom(6).hex()
            user.set_password(new_password)
            user.notification_channel = form.notification_channel.data or user.notification_channel or 'email'
            db.session.commit()
            send_password_reset(user, new_password)
            flash('A password reset message has been sent.', 'success')
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
    db.session.commit()
    send_password_reset(user, new_password)
    flash(f'A password reset message was sent to {user.username}.', 'success')
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

        if form.password.data:
            current_user.set_password(form.password.data)
            flash('Password updated.', 'success')

        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('main.profile'))

    return render_template('profile.html', form=form)


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
        # Efficient query: all recruiting OR (testing/closed AND user has approved part.)
        recruiting = GroupTest.query.filter_by(status='recruiting').all()
        member_tests = (
            GroupTest.query
            .join(Participation)
            .filter(
                Participation.user_id == current_user.id,
                Participation.approved == True,
                GroupTest.status.in_(['testing', 'closed'])
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
        return test.status.title()

    def group_sort_key(test):
        if sort_by == 'title':
            return (test.title or '').lower()
        if sort_by == 'compound':
            return (test.compound or '').lower()
        if sort_by == 'tags':
            return test.tag_names().lower()
        if sort_by == 'status':
            status_order = {'recruiting': 0, 'testing': 1, 'closed': 2}
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
            group_order = {'Recruiting': 0, 'Testing': 1, 'Closed': 2}
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
        costs=costs,
        participations=parts,
        my_part=my_part,
        show_participant_list=show_participant_list,
        reimbursed_by_user=reimbursed_by_user,
        notify_form=form,
        notification_templates=templates
    )


@main_bp.route('/my-results')
@login_required
def my_results():
    group_by = request.args.get('group_by', 'none')
    sort_by = request.args.get('sort_by', 'posted_at')
    sort_dir = request.args.get('sort_dir', 'desc')
    query = (request.args.get('q') or '').strip().lower()

    group_results = []
    member_tests = (
        GroupTest.query
        .join(Participation)
        .filter(
            Participation.user_id == current_user.id,
            Participation.approved == True,
            GroupTest.status == 'closed',
            GroupTest.results_link.isnot(None),
        )
        .all()
    )
    for test in member_tests:
        group_results.append({
            'kind': 'group_test',
            'title': test.title,
            'summary': test.description or '',
            'results_link': test.results_link,
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

    if form.validate_on_submit():
        part.order_status = form.order_status.data
        part.paid_lab = form.paid_lab.data
        if form.amount_paid.data is not None:
            part.amount_paid = form.amount_paid.data
        if form.notes.data:
            part.notes = form.notes.data

        db.session.commit()
        flash("Your status has been updated.", "success")
        return redirect(url_for('main.test_detail', test_id=test_id))

    return render_template('participant_update_status.html', form=form, test=test, part=part)


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
    if not form.is_submitted():
        form.tag_names.data = ''
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
            results_posted_at=datetime.utcnow() if form.status.data == 'closed' and form.results_link.data else None,
            created_by=current_user.id
        )
        db.session.add(test)
        db.session.flush()
        apply_tags_to_record(test, form.tag_names.data)
        db.session.commit()
        flash(f'Group test "{test.title}" created successfully.', 'success')
        return redirect(url_for('main.test_detail', test_id=test.id))
    return render_template('admin/create_test.html', form=form, tag_suggestions=get_all_tag_names())


@main_bp.route('/admin/edit-test/<int:test_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_test(test_id):
    test = GroupTest.query.get_or_404(test_id)
    form = GroupTestForm(obj=test)  # Pre-populate
    populate_donor_shipping_choices(form)
    if not form.is_submitted():
        form.tag_names.data = test.tag_names()
    if form.donor_shipping_reimbursed_by_id.data in (None, '') and test.donor_shipping_reimbursed_by_id:
        form.donor_shipping_reimbursed_by_id.data = test.donor_shipping_reimbursed_by_id
    elif form.donor_shipping_reimbursed_by_id.data is None:
        form.donor_shipping_reimbursed_by_id.data = 0
    
    if form.validate_on_submit():
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
        apply_tags_to_record(test, form.tag_names.data)
        if test.status != 'closed':
            test.results_link = None  # Clear if not closed
            test.results_posted_at = None
        elif test.results_link and not test.results_posted_at:
            test.results_posted_at = datetime.utcnow()
        db.session.commit()
        flash('Group test updated.', 'success')
        return redirect(url_for('main.test_detail', test_id=test_id))
    
    return render_template('admin/edit_test.html', form=form, test=test, tag_suggestions=get_all_tag_names())


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
    if form.validate_on_submit():
        for key, value in {
            'mailjet_api_key': form.mailjet_api_key.data,
            'mailjet_secret_key': form.mailjet_secret_key.data,
            'mailjet_sender_email': form.mailjet_sender_email.data,
            'telegram_bot_token': form.telegram_bot_token.data,
            'service_base_url': form.service_base_url.data,
            'notification_debug_enabled': 'true' if form.notification_debug_enabled.data else 'false',
        }.items():
            config = NotificationConfig.query.filter_by(key=key).first() or NotificationConfig(key=key)
            config.value = value or None
            db.session.add(config)
        db.session.commit()
        append_notification_log('configuration: credentials updated')
        flash('Notification configuration saved.', 'success')
        return redirect(url_for('main.notification_config'))

    if not form.is_submitted():
        configs = {cfg.key: cfg.value for cfg in NotificationConfig.query.all()}
        form.mailjet_api_key.data = mask_secret(configs.get('mailjet_api_key'))
        form.mailjet_secret_key.data = mask_secret(configs.get('mailjet_secret_key'))
        form.mailjet_sender_email.data = configs.get('mailjet_sender_email')
        form.telegram_bot_token.data = mask_secret(configs.get('telegram_bot_token'))
        form.service_base_url.data = configs.get('service_base_url')
        form.notification_debug_enabled.data = str(configs.get('notification_debug_enabled', 'false')).lower() == 'true'
    log_contents = read_notification_log()
    return render_template('admin/notification_config.html', form=form, log_contents=log_contents)


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
            notification_channel=form.notification_channel.data or 'email'
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
    link = request.form.get('results_link', '').strip()
    test.results_link = link if link else None
    if test.status != 'closed':
        test.status = 'closed'
    if test.results_link and not test.results_posted_at:
        test.results_posted_at = datetime.utcnow()
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
        result = PublicResult(
            title=form.title.data,
            summary=form.summary.data,
            results_link=form.results_link.data.strip(),
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
    )


@main_bp.route('/admin/public-results/<int:result_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_public_result(result_id):
    result = PublicResult.query.get_or_404(result_id)
    title = result.title
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