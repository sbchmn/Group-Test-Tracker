"""Administrator draft/publish workflow and public immutable branding assets."""
import io
from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import BooleanField, FileField, HiddenField, SelectField, StringField, TextAreaField
from wtforms.validators import Length
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from . import db
from .branding import ASSET_KEYS, DEFAULTS, FONTS, TEXT_LIMITS, create_asset, email_parts, get_state, validate_settings
from .models import BrandingAsset, BrandingRevision, BrandingState

branding_bp = Blueprint('branding', __name__)


class BrandingForm(FlaskForm):
    version = HiddenField()
    enabled = BooleanField('Enable customer branding')
    font = SelectField('Font', choices=[(key, value[0]) for key, value in FONTS.items()])
    default_theme = SelectField('Default appearance', choices=[('light', 'Light'), ('dark', 'Dark'), ('system', 'Device preference')])
    logo_upload = FileField('Primary logo')
    dark_logo_upload = FileField('Logo for dark backgrounds (optional)')
    favicon_upload = FileField('Browser icon (optional)')


LABELS = {
    'name': 'Application name', 'short_name': 'Short name (optional)', 'tagline': 'Tagline',
    'intro': 'Welcome text', 'support_email': 'Support email', 'user_help_url': 'User help link',
    'admin_help_url': 'Administrator help link', 'operator_name': 'Operator / organization name',
    'legal_email': 'Legal contact email', 'mailing_address': 'Mailing address',
    'governing_law': 'Governing law', 'effective_date': 'Policy effective date',
}
for _key, _limit in TEXT_LIMITS.items():
    setattr(BrandingForm, _key, (TextAreaField if _key in ('intro', 'mailing_address') else StringField)(LABELS[_key], validators=[Length(max=_limit)]))
for _mode in ('light', 'dark'):
    for _part in ('accent', 'nav', 'surface'):
        setattr(BrandingForm, _mode + '_' + _part, StringField(_part.title() if _part != 'nav' else 'Navigation'))


def administrator(function):
    @wraps(function)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin or current_user.is_reserved_support_account:
            abort(403)
        return function(*args, **kwargs)
    return wrapped


@branding_bp.before_request
def enforce_subscription():
    if request.method == 'POST' and request.endpoint != 'branding.theme':
        from .routes import enforce_managed_tenant_contract
        return enforce_managed_tenant_contract()


def _publish(state, settings, action):
    clean, errors = validate_settings(settings)
    if errors:
        raise ValueError('Review the draft fields before publishing: ' + ', '.join(errors))
    state.published = clean
    for key in ASSET_KEYS:
        if clean[key]:
            db.session.get(BrandingAsset, clean[key]).published = True
    db.session.add(BrandingRevision(actor_id=current_user.id, action=action, settings=dict(clean)))


@branding_bp.route('/admin/branding', methods=['GET', 'POST'])
@administrator
def editor():
    state = get_state()
    draft = {**DEFAULTS, **(state.draft if state else {})}
    form = BrandingForm(data={**draft, 'version': str(state.version if state else 0)})
    error_message = None
    status = 200
    if form.is_submitted():
        try:
            expected = int(request.form.get('version', '-1'))
            if expected != (state.version if state else 0):
                raise StaleDataError()
            if state is None:
                state = BrandingState(id=1, draft=dict(DEFAULTS), published=dict(DEFAULTS))
                db.session.add(state)
            action = request.form.get('action')
            if action == 'save':
                if not form.validate():
                    raise ValueError('Review the highlighted fields.')
                candidate = {key: getattr(form, key).data for key in DEFAULTS if hasattr(form, key)}
                candidate.update({key: draft[key] for key in ASSET_KEYS})
                clean, errors = validate_settings(candidate)
                for key, message in errors.items():
                    if hasattr(form, key):
                        getattr(form, key).errors = list(getattr(form, key).errors) + [message]
                if errors:
                    raise ValueError('Review the highlighted fields.')
                for key in ASSET_KEYS:
                    upload = getattr(form, key + '_upload').data
                    if request.form.get('remove_' + key) == 'yes':
                        clean[key] = ''
                    if upload and upload.filename:
                        try:
                            clean[key] = create_asset(upload).id
                        except ValueError as error:
                            getattr(form, key + '_upload').errors = [str(error)]
                            raise
                state.draft = clean
                # Advance the version even when saving an otherwise identical draft.
                if state.version is not None:
                    state.version += 1
                flash('Branding draft saved. Preview it, then publish when ready.', 'success')
            elif action == 'publish':
                _publish(state, state.draft, 'publish')
                state.version = (state.version or 0) + 1
                flash('Branding published. Members and outgoing messages now use this revision.', 'success')
            elif action == 'discard':
                state.draft = dict(state.published)
                state.version = (state.version or 0) + 1
                flash('Draft replaced with the current published settings.', 'success')
            elif action == 'defaults':
                # Keep operator details and saved custom draft available.
                settings = {**state.published, 'enabled': False}
                _publish(state, settings, 'disable')
                state.version = (state.version or 0) + 1
                flash('Default GTM branding restored. Your custom draft is still saved.', 'success')
            elif action == 'restore':
                revision_id = request.form.get('revision_id', type=int)
                revision = db.session.get(BrandingRevision, revision_id) if revision_id else None
                if revision is None:
                    raise ValueError('Choose an available published revision.')
                _publish(state, revision.settings, 'restore')
                state.draft = dict(revision.settings)
                state.version = (state.version or 0) + 1
                flash('Selected branding revision restored and published.', 'success')
            else:
                abort(400)
            db.session.commit()
            return redirect(url_for('branding.editor'))
        except (StaleDataError, IntegrityError):
            db.session.rollback()
            error_message = 'Another administrator changed these settings. Reload this page before saving again.'
            status = 409
        except ValueError as error:
            db.session.rollback()
            error_message = str(error)
            status = 400
    revisions = BrandingRevision.query.order_by(BrandingRevision.id.desc()).limit(20).all()
    live_state = get_state()
    return render_template('admin/branding.html', form=form, draft=draft, revisions=revisions,
                           published_branding={**DEFAULTS, **(live_state.published if live_state else {})},
                           error_message=error_message, branding_text_fields=LABELS), status


@branding_bp.get('/admin/branding/preview/<surface>')
@administrator
def preview(surface):
    state = get_state()
    g.branding_override = {**DEFAULTS, **(state.draft if state else {})}
    g.branding_preview = True
    g.branding_preview_public = surface != 'dashboard'
    g.branding_preview_theme = 'dark' if request.args.get('theme') == 'dark' else 'light'
    if surface == 'home':
        return render_template('index.html')
    if surface == 'login':
        from .routes import LoginForm
        return render_template('login.html', form=LoginForm())
    if surface == 'register':
        from .routes import RegisterForm, _apply_available_channels
        form = RegisterForm()
        _apply_available_channels(form)
        return render_template('register.html', form=form)
    if surface in ('terms', 'privacy'):
        return render_template(surface + '.html')
    if surface == 'email':
        _, body = email_parts('<p>Hello Alex,</p><p>Your group test has an update. Sign in to review the details.</p>')
        return render_template('admin/branding_preview.html', email_body=body)
    if surface == 'dashboard':
        return render_template('admin/branding_preview.html', email_body=None)
    abort(404)


@branding_bp.get('/branding/assets/<asset_id>/<variant>.png')
def asset(asset_id, variant):
    if variant not in ('image', 'icon'):
        abort(404)
    item = db.session.get(BrandingAsset, asset_id)
    if item is None or (not item.published and (not current_user.is_authenticated or not current_user.is_admin or current_user.is_reserved_support_account)):
        abort(404)
    response = send_file(io.BytesIO(item.icon_data if variant == 'icon' else item.data), mimetype='image/png',
                         download_name='branding.png', etag=asset_id + '-' + variant,
                         max_age=31536000 if item.published else 0)
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if item.published else 'private, no-store'
    return response


@branding_bp.post('/appearance')
def theme():
    form = FlaskForm()
    if not form.validate_on_submit():
        abort(400)
    choice = request.form.get('theme')
    if choice not in ('site', 'light', 'dark', 'system'):
        abort(400)
    if current_user.is_authenticated:
        current_user.theme_preference = choice
        db.session.commit()
    from .routes import _safe_next_url
    destination = _safe_next_url(request.form.get('next'))
    if destination and ('\\' in destination or any(ord(char) < 32 for char in destination)):
        destination = None
    response = redirect(destination or url_for('main.index'))
    if not current_user.is_authenticated:
        response.set_cookie('gtm_theme', choice, max_age=31536000, httponly=True, secure=request.is_secure, samesite='Lax')
    return response
