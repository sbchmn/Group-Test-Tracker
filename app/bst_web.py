"""GTM administration for the same BST policies and decisions used by the bot."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, BooleanField, TextAreaField, SelectField, HiddenField
from wtforms.validators import DataRequired, Length, NumberRange, Email

from . import db
from .models import BSTTopic, BSTVendor, BSTEvent
from .routes import admin_required, enforce_managed_tenant_contract
from . import bst_service as bst

bst_bp = Blueprint('bst', __name__)
bst_bp.before_request(enforce_managed_tenant_contract)


class TopicForm(FlaskForm):
    name = StringField('Topic label', validators=[DataRequired(), Length(max=160)])
    chat_id = StringField('Telegram group Chat ID', validators=[DataRequired(), Length(max=80)])
    thread_id = IntegerField('Topic ID', validators=[DataRequired(), NumberRange(min=1)])
    enabled = BooleanField('Enable vendor-only posting enforcement')
    version = HiddenField()


for _key, (_label, _default) in bst.OPTIONS.items():
    setattr(TopicForm, _key, BooleanField(_label, default=_default))


class VendorForm(FlaskForm):
    topic_id = SelectField('BST topic', coerce=int, validators=[DataRequired()])
    telegram_user_id = StringField('Numeric Telegram user ID', validators=[DataRequired(), Length(max=20)])
    vendor_name = StringField('Vendor name', validators=[DataRequired(), Length(max=160)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=254)])
    guarantees = TextAreaField('Vendor guarantees', validators=[DataRequired(), Length(max=3000)])
    dispute_contact = TextAreaField('Dispute resolution contact', validators=[DataRequired(), Length(max=3000)])
    dispute_process = TextAreaField('Dispute resolution process', validators=[DataRequired(), Length(max=3000)])


@bst_bp.route('/admin/bst')
@login_required
@admin_required
def index():
    topics = BSTTopic.query.order_by(BSTTopic.name).all()
    query = BSTVendor.query.join(BSTTopic)
    selected_topic = request.args.get('topic', type=int)
    status = request.args.get('status', 'all')
    search = request.args.get('q', '').strip()
    if selected_topic:
        query = query.filter(BSTVendor.topic_id == selected_topic)
    if status == 'approved':
        query = query.filter(BSTVendor.is_approved.is_(True))
    elif status in {'pending', 'draft', 'changes', 'denied', 'revoked'}:
        query = query.filter(BSTVendor.status == status)
    if search:
        from sqlalchemy import or_, cast, String
        query = query.filter(or_(BSTVendor.telegram_user_id.ilike(f'%{search}%'), cast(BSTVendor.draft, String).ilike(f'%{search}%')))
    vendors = query.order_by(BSTVendor.created_at.desc(), BSTVendor.id.desc()).paginate(
        page=max(1, request.args.get('page', 1, type=int)), per_page=25, error_out=False)
    return render_template('admin/bst/index.html', topics=topics, vendors=vendors, selected_topic=selected_topic, status=status, search=search, bst=bst)


@bst_bp.route('/admin/bst/topics/new', methods=['GET', 'POST'])
@bst_bp.route('/admin/bst/topics/<int:topic_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def topic_settings(topic_id=None):
    topic = db.get_or_404(BSTTopic, topic_id) if topic_id else None
    form = TopicForm()
    if form.validate_on_submit():
        try:
            topic = bst.save_topic(form.chat_id.data, form.thread_id.data, form.name.data,
                                   {key: getattr(form, key).data for key in bst.OPTIONS}, form.enabled.data,
                                   topic, int(form.version.data or 0), web_user=current_user)
            flash('BST topic settings saved.', 'success')
            return redirect(url_for('bst.topic_settings', topic_id=topic.id))
        except (bst.BSTError, ValueError) as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    if not form.is_submitted() and topic:
        form.name.data, form.chat_id.data, form.thread_id.data = topic.name, topic.chat_id, topic.thread_id
        form.enabled.data, form.version.data = topic.enabled, str(topic.version)
        for key, value in bst.options(topic).items():
            getattr(form, key).data = value
    return render_template('admin/bst/topic.html', form=form, topic=topic, bst=bst)


@bst_bp.route('/admin/bst/vendors/new', methods=['GET', 'POST'])
@login_required
@admin_required
def create_vendor():
    form = VendorForm()
    form.topic_id.choices = [(t.id, t.name) for t in BSTTopic.query.order_by(BSTTopic.name).all()]
    if form.validate_on_submit():
        try:
            topic = db.get_or_404(BSTTopic, form.topic_id.data)
            vendor = bst.preapprove(topic, form.telegram_user_id.data,
                                    {field: getattr(form, field).data for field in bst.FIELDS}, web_user=current_user)
            flash('Vendor created and approved. Required email verification still applies before posting.', 'success')
            return redirect(url_for('bst.vendor_detail', vendor_id=vendor.id))
        except bst.BSTError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
    return render_template('admin/bst/create_vendor.html', form=form)


@bst_bp.route('/admin/bst/vendors/<int:vendor_id>')
@login_required
@admin_required
def vendor_detail(vendor_id):
    vendor = db.get_or_404(BSTVendor, vendor_id)
    history = BSTEvent.query.filter_by(vendor_id=vendor.id).order_by(BSTEvent.created_at.desc(), BSTEvent.id.desc()).limit(100).all()
    return render_template('admin/bst/vendor.html', vendor=vendor, history=history, bst=bst,
                           queue=request.args.get('return_to') == 'queue')


@bst_bp.route('/admin/bst/vendors/<int:vendor_id>/decision', methods=['POST'])
@login_required
@admin_required
def decision(vendor_id):
    vendor = db.get_or_404(BSTVendor, vendor_id)
    try:
        bst.decide(vendor, request.form.get('action'), int(request.form.get('version', 0)),
                   request.form.get('reason', ''), web_user=current_user)
        flash('BST decision saved. The applicant notification is queued.', 'success')
        if request.form.get('return_to') == 'queue':
            return redirect(url_for('main.action_queue', **{key: request.form.get(key, '') for key in ('q', 'status', 'page', 'type')}))
    except (bst.BSTError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(url_for('bst.vendor_detail', vendor_id=vendor.id,
                            **{key: request.form.get(key, '') for key in ('return_to', 'q', 'status', 'page', 'type')}))
