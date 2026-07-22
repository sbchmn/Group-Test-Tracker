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

from . import db
import os

from .models import User, GroupTest, Participation, NotificationTemplate, NotificationConfig
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
    
    submit = SubmitField('Save Group Test')


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
        tests.sort(key=lambda x: x.updated_at, reverse=True)
    
    return render_template('dashboard.html', tests=tests, current_user=current_user)


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
        group_test_id=test_id, user_id=current_user.id, approved=True
    ).first()
    
    # Show full participant list (approved + pending) to admins + approved members
    show_participant_list = current_user.is_admin or my_part is not None
    
    if show_participant_list:
        parts = test.participations.order_by(Participation.approved.desc(), Participation.requested_at).all()
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
                amount_owed = None
                if part.user_id == current_user.id:
                    amount_owed = costs.get('non_donor_pays' if not part.vial_donor else 'donor_pays', 0)
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


# ==================== ADMIN ROUTES ====================

@main_bp.route('/admin/create-test', methods=['GET', 'POST'])
@login_required
@admin_required
def create_test():
    form = GroupTestForm()
    populate_donor_shipping_choices(form)
    if form.validate_on_submit():
        lab_items = []
        names = request.form.getlist('lab_item_name')
        prices = request.form.getlist('lab_item_price')
        vials = request.form.getlist('lab_item_vials')
        for name, price, vial_count in zip(names, prices, vials):
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
            lab_items.append({
                'name': name,
                'price': round(price_value, 2),
                'vials_needed': vial_value,
            })

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
            created_by=current_user.id
        )
        db.session.add(test)
        db.session.commit()
        flash(f'Group test "{test.title}" created successfully.', 'success')
        return redirect(url_for('main.test_detail', test_id=test.id))
    return render_template('admin/create_test.html', form=form)


@main_bp.route('/admin/edit-test/<int:test_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_test(test_id):
    test = GroupTest.query.get_or_404(test_id)
    form = GroupTestForm(obj=test)  # Pre-populate
    populate_donor_shipping_choices(form)
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
        for name, price, vial_count in zip(names, prices, vials):
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
            lab_items.append({
                'name': name,
                'price': round(price_value, 2),
                'vials_needed': vial_value,
            })
        test.lab_name = form.lab_name.data or None
        test.lab_test_details = lab_items
        test.total_lab_cost = form.total_lab_cost.data or 0.0
        test.donor_shipping_cost = form.donor_shipping_cost.data or 0.0
        test.donor_shipping_reimbursement = form.donor_shipping_reimbursement.data or 'credit'
        test.donor_shipping_reimbursed_by_id = form.donor_shipping_reimbursed_by_id.data or None
        if test.status != 'closed':
            test.results_link = None  # Clear if not closed
        db.session.commit()
        flash('Group test updated.', 'success')
        return redirect(url_for('main.test_detail', test_id=test_id))
    
    return render_template('admin/edit_test.html', form=form, test=test)


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
            part.approved = True
            part.approved_at = datetime.utcnow()
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
        part.approved = True
        part.approved_at = datetime.utcnow()
        costs = part.group_test.calculate_costs()
        part.update_amount_owed(costs)
        db.session.commit()
        flash(f'Approved {part.name or part.user.username} for test.', 'success')
    return redirect(url_for('main.manage_participants', test_id=part.group_test_id))


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

    # Get users who are not already participants in this test
    existing_participant_ids = [p.user_id for p in test.participations]
    available_users = User.query.filter(User.id.notin_(existing_participant_ids)).all()

    form.user_id.choices = [(u.id, f"{u.username} ({u.email})") for u in available_users]

    if form.validate_on_submit():
        user = User.query.get(form.user_id.data)
        if not user:
            flash('User not found.', 'danger')
            return redirect(url_for('main.add_participant_to_test', test_id=test_id))

        # Create participation with auto-approval
        part = Participation(
            group_test_id=test.id,
            user_id=user.id,
            name=user.username,
            tg_username=user.tg_username,
            approved=True,
            approved_at=datetime.utcnow(),
            active=True
        )
        # Calculate initial owed amount
        costs = test.calculate_costs()
        part.update_amount_owed(costs)

        db.session.add(part)
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
    db.session.commit()
    flash('Results link updated and test marked closed (if needed). Visible only to approved members.', 'success')
    return redirect(url_for('main.test_detail', test_id=test_id))


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