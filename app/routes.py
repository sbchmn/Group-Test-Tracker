"""
Main Blueprint - All Routes, Form Classes, and Business Logic
- Strict visibility enforcement per requirements.
- Cost calculations delegated to model (single source of truth, tested).
- Admin-only routes protected with helper decorator.
- Clean separation: forms defined here, templates consume them.
- All POSTs use CSRF (via Flask-WTF).
"""

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, abort, jsonify, send_file
)
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, BooleanField, TextAreaField, 
    FloatField, DateField, SelectField, SubmitField, FieldList, FormField
)
from wtforms.validators import DataRequired, Email, Length, Optional, NumberRange, EqualTo
from datetime import datetime, date
from functools import wraps

from . import db
from .models import User, GroupTest, Participation
from .export import generate_test_export

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
    
    total_lab_cost = FloatField('Total Lab Cost ($)', validators=[Optional(), NumberRange(min=0)], default=0.0)
    shipping_cost = FloatField('Shipping to Lab ($)', validators=[Optional(), NumberRange(min=0)], default=0.0)
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


@main_bp.route('/test/<int:test_id>')
@login_required
def test_detail(test_id):
    test = GroupTest.query.get_or_404(test_id)
    if not test.can_user_see(current_user):
        abort(403)
    
    costs = test.calculate_costs()
    
    # Current user's participation (if any)
    my_part = None
    if not current_user.is_admin:
        my_part = Participation.query.filter_by(
            group_test_id=test_id, user_id=current_user.id
        ).first()
    
    # For admin: all participations; for member: just their own (or approved list if needed)
    if current_user.is_admin:
        parts = test.participations.all()
    else:
        parts = [my_part] if my_part else []
    
    return render_template(
        'group_test_detail.html',
        test=test,
        costs=costs,
        participations=parts,
        my_part=my_part
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
        flash('Participation request submitted successfully. Admin will review shortly.', 'success')
        return redirect(url_for('main.dashboard'))
    
    return render_template('request_participation.html', test=test, form=form)


# ==================== ADMIN ROUTES ====================

@main_bp.route('/admin/create-test', methods=['GET', 'POST'])
@login_required
@admin_required
def create_test():
    form = GroupTestForm()
    if form.validate_on_submit():
        test = GroupTest(
            title=form.title.data,
            description=form.description.data,
            start_date=form.start_date.data,
            vendor=form.vendor.data,
            batch_number=form.batch_number.data,
            compound=form.compound.data,
            size=form.size.data,
            status=form.status.data,
            total_lab_cost=form.total_lab_cost.data or 0.0,
            shipping_cost=form.shipping_cost.data or 0.0,
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
    
    if form.validate_on_submit():
        form.populate_obj(test)
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