"""Payment reporting, private evidence access, and shared review decisions."""
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from flask import Blueprint, abort, current_app, jsonify, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm.exc import StaleDataError

from . import db
from .models import Participation, PaymentSubmission
from .storage import (
    StorageConfigurationError, StorageReadError, StorageUploadError,
    delete_payment_proof, payment_proof_storage_ready, read_payment_proof, upload_payment_proof,
)

payment_bp = Blueprint('payments', __name__, url_prefix='/payments')


@payment_bp.before_request
def enforce_payment_tenant_contract():
    # New payment endpoints follow the same write restrictions as the main UI.
    from .routes import enforce_managed_tenant_contract
    return enforce_managed_tenant_contract()

# Deliberately independent from wallet URI schemes: EVM networks share a scheme,
# but have different transaction explorers. Ambiguous "bnb"/"binance" are excluded.
EXPLORERS = {
    'bitcoin': ('Bitcoin', 'https://mempool.space/tx/'),
    'litecoin': ('Litecoin', 'https://litecoinspace.org/tx/'),
    'bitcoincash': ('Bitcoin Cash', 'https://blockchair.com/bitcoin-cash/transaction/'),
    'ethereum': ('Ethereum', 'https://etherscan.io/tx/'),
    'arbitrum': ('Arbitrum One', 'https://arbiscan.io/tx/'),
    'optimism': ('OP Mainnet', 'https://optimistic.etherscan.io/tx/'),
    'base': ('Base', 'https://basescan.org/tx/'),
    'polygon': ('Polygon', 'https://polygonscan.com/tx/'),
    'solana': ('Solana', 'https://solscan.io/tx/'),
    'tron': ('Tron', 'https://tronscan.org/#/transaction/'),
    'bsc': ('BNB Smart Chain', 'https://bscscan.com/tx/'),
}
ALIASES = {
    'btc': 'bitcoin', 'ltc': 'litecoin', 'bch': 'bitcoincash',
    'eth': 'ethereum', 'erc20': 'ethereum', 'arbitrumone': 'arbitrum',
    'opmainnet': 'optimism', 'matic': 'polygon', 'polygonpos': 'polygon',
    'sol': 'solana', 'trx': 'tron', 'trc20': 'tron',
    'bep20': 'bsc', 'bnbsmartchain': 'bsc', 'binancesmartchain': 'bsc',
}


def explorer_url(network, transaction_id):
    key = re.sub(r'[\s_-]', '', network or '').lower()
    key = ALIASES.get(key, key)
    if key not in EXPLORERS or not re.fullmatch(r'[A-Za-z0-9]{1,255}', transaction_id or ''):
        return None
    return EXPLORERS[key][1] + quote(transaction_id, safe='')


def option_snapshot(option):
    profile = option.to_payment_profile()
    return {
        'id': option.id, 'title': option.display_title(), 'method_type': option.method_type,
        'network': option.network or '', 'destination': profile['destination_value'],
        'destination_label': profile['destination_label'], 'details': option.details or '',
        'payment_link': profile['payment_link'], 'link_type': profile['link_type'],
        'proof_image_enabled': bool(option.proof_image_enabled),
        'proof_transaction_enabled': bool(option.proof_transaction_enabled),
        'proof_requirement': option.proof_requirement,
    }


def _authorized_part(part_id, owner_only=False):
    part = db.get_or_404(Participation, part_id)
    if current_user.id != part.user_id and (owner_only or not current_user.is_admin):
        abort(403)
    if not current_user.is_admin and (not part.approved or part.denied or not part.group_test.can_user_see(current_user)):
        abort(403)
    return part


def _serialize_submission(submission):
    snapshot = submission.method_snapshot
    return {
        'id': submission.id, 'amount': str(submission.amount), 'method': snapshot,
        'transaction_id': submission.transaction_id or '',
        'explorer_url': explorer_url(snapshot.get('network'), submission.transaction_id)
        if snapshot.get('method_type') == 'crypto' else None,
        'image_url': url_for('payments.proof', submission_id=submission.id) if submission.image_key else None,
        'archived_by_merge': submission.archived_by_merge, 'status': submission.status, 'denial_reason': submission.denial_reason or '',
        'submitted_at': submission.submitted_at.isoformat() + 'Z',
        'reviewed_at': submission.reviewed_at.isoformat() + 'Z' if submission.reviewed_at else None,
        'reviewed_by_id': submission.reviewed_by_id,
    }


@payment_bp.get('/<int:part_id>')
@login_required
def detail(part_id):
    part = _authorized_part(part_id)
    reports = part.payment_submissions
    options = [option_snapshot(option) for option in part.group_test.payment_options if option.is_active]
    response = jsonify(
        participant=part.name or part.user.username, test=part.group_test.title,
        amount_owed=f'{part.amount_owed or 0:.2f}', amount_paid=f'{part.amount_paid or 0:.2f}',
        paid=bool(part.paid_lab), pending=part.payment_claim_pending,
        revision=part.payment_revision, preferred_option_id=part.preferred_payment_option_id,
        legacy_snapshot=part.preferred_payment_snapshot or 'No payment method recorded',
        options=options, latest=_serialize_submission(part.current_payment_submission) if part.current_payment_submission else None,
        history=[_serialize_submission(report) for report in reports],
        upload_ready=payment_proof_storage_ready(),
        can_report=bool(current_user.id == part.user_id and part.approved and not part.denied and not part.paid_lab
                        and part.group_test.status in ('ready_for_payment', 'testing', 'closed')),
    )
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def _revision_matches(part):
    try:
        return int(request.form.get('revision', '')) == part.payment_revision
    except (TypeError, ValueError):
        return False


@payment_bp.post('/<int:part_id>/report')
@login_required
def report(part_id):
    part = _authorized_part(part_id, owner_only=True)
    if part.paid_lab or part.group_test.status not in ('ready_for_payment', 'testing', 'closed'):
        return jsonify(error='Payment reporting is unavailable for this test.'), 409
    if not _revision_matches(part):
        return jsonify(error='This payment has changed. Close and reopen the modal to see the latest details.'), 409
    errors = {}
    try:
        amount = Decimal(request.form.get('amount', ''))
        if not amount.is_finite() or amount <= 0 or amount > Decimal('9999999999.99') or amount != amount.quantize(Decimal('.01')):
            raise ValueError()
    except (InvalidOperation, ValueError):
        errors['amount'] = 'Enter a positive amount with no more than two decimal places.'
    try:
        selected_id = int(request.form.get('option_id', '0'))
    except ValueError:
        selected_id = 0
    option = next((item for item in part.group_test.payment_options if item.id == selected_id and item.is_active), None)
    latest = part.current_payment_submission
    # Inactive/removed methods may be kept for an existing report, never selected anew.
    if latest and latest.method_snapshot.get('id') == selected_id:
        snapshot = latest.method_snapshot
    elif option:
        snapshot = option_snapshot(option)
    else:
        snapshot = None
        errors['option_id'] = 'Choose an available payment method.'
    transaction_id = request.form.get('transaction_id', '').strip()
    if len(transaction_id) > 255 or any(ord(ch) < 32 for ch in transaction_id):
        errors['transaction_id'] = 'Enter a transaction ID of up to 255 characters.'
    file = request.files.get('image')
    has_new_image = bool(file and file.filename)
    remove_image = request.form.get('remove_image') == 'true'
    same_method = bool(latest and latest.method_snapshot.get('id') == selected_id)
    image_key = latest.image_key if same_method and not remove_image else None
    if snapshot:
        if transaction_id and not snapshot['proof_transaction_enabled']:
            errors['transaction_id'] = 'Transaction IDs are not accepted for this method.'
        if has_new_image and not snapshot['proof_image_enabled']:
            errors['image'] = 'Images are not accepted for this method.'
        if not snapshot['proof_image_enabled']:
            image_key = None
        has_image = bool(image_key or has_new_image)
        requirement = snapshot['proof_requirement']
        if requirement == 'either' and not (has_image or transaction_id):
            errors['proof'] = 'Provide at least one accepted proof of payment.'
        if requirement == 'all':
            if snapshot['proof_image_enabled'] and not has_image:
                errors['image'] = 'An image is required for this method.'
            if snapshot['proof_transaction_enabled'] and not transaction_id:
                errors['transaction_id'] = 'A transaction ID is required for this method.'
    if errors:
        return jsonify(errors=errors), 400
    uploaded_key = None
    try:
        if has_new_image:
            uploaded_key = upload_payment_proof(file)
            image_key = uploaded_key
        if latest and latest.status == 'pending':
            latest.status = 'superseded'
        submission = PaymentSubmission(
            participation_id=part.id, amount=amount, method_snapshot=snapshot,
            transaction_id=transaction_id or None, image_key=image_key,
        )
        db.session.add(submission)
        first_claim = part.payment_claimed_at is None
        part.amount_paid = float(amount)
        part.preferred_payment_option_id = option.id if option else part.preferred_payment_option_id
        part.preferred_payment_snapshot = ' | '.join(filter(None, [snapshot['title'], snapshot['destination'], snapshot['network']]))
        part.payment_claimed_at = datetime.utcnow()
        # Force a versioned participation UPDATE even if the other values match.
        part.payment_revision += 1
        db.session.commit()
    except (StorageConfigurationError, StorageUploadError) as exc:
        db.session.rollback()
        return jsonify(errors={'image': str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        if uploaded_key:
            delete_payment_proof(uploaded_key)
        if isinstance(exc, StaleDataError):
            return jsonify(error='This payment changed during submission. Close and reopen the modal.'), 409
        raise
    if first_claim:
        from .routes import _notify_payment_claim
        try:
            _notify_payment_claim(part.group_test, part)
        except Exception:
            current_app.logger.exception('Payment report saved, but administrator notification failed')
    return jsonify(message='Payment submitted for review.')


def review_payment(part, approve):
    """Shared by both admin screens and the existing form endpoints."""
    if not part.approved or part.denied:
        return 'Only approved participants can have payments reviewed.', 409
    reports = part.payment_submissions
    if (reports or request.form.get('revision') is not None) and not _revision_matches(part):
        return 'This payment has changed. Reopen it before making a decision.', 409
    if part.paid_lab or (not approve and not part.payment_claim_pending):
        return 'This payment is no longer awaiting review.', 409
    reason = request.form.get('reason', request.form.get('deny_reason', '')).strip()
    if not approve and (not reason or len(reason) > 1000):
        return 'Enter a denial reason of up to 1,000 characters.', 400
    latest = part.current_payment_submission
    now = datetime.utcnow()
    if latest and latest.status == 'pending':
        latest.status = 'approved' if approve else 'denied'
        latest.reviewed_at = now
        latest.reviewed_by_id = current_user.id
        latest.denial_reason = None if approve else reason
    else:
        # Preserve manual decisions and legacy claims as reviewable history too.
        db.session.add(PaymentSubmission(
            participation_id=part.id, amount=Decimal(str(part.amount_paid or 0)),
            method_snapshot=latest.method_snapshot if latest else {'id': part.preferred_payment_option_id, 'title': part.preferred_payment_snapshot or 'Manual payment record',
                             'network': '', 'destination': '', 'method_type': 'other',
                             'proof_image_enabled': False, 'proof_transaction_enabled': False, 'proof_requirement': 'optional'},
            image_key=latest.image_key if latest else None,
            transaction_id=latest.transaction_id if latest else None,
            status='approved' if approve else 'denied', reviewed_at=now, reviewed_by_id=current_user.id,
            denial_reason=None if approve else reason,
            submitted_at=part.payment_claimed_at or now,
        ))
    part.paid_lab = approve
    part.payment_claimed_at = None
    part.payment_verified_at = now if approve else None
    part.payment_verified_by_id = current_user.id if approve else None
    part.payment_revision += 1
    try:
        db.session.commit()
    except StaleDataError:
        db.session.rollback()
        return 'This payment changed during review. Reopen it before making a decision.', 409
    if not approve:
        from .notifications import send_notification_message
        try:
            delivered = send_notification_message(
                part.user, part.user.notification_channel or 'email',
                f'Payment needs attention: {part.group_test.title}',
                f'Your payment report for {part.group_test.title} was denied. Reason: {reason}\n\n'
                f'Update and resubmit your report: {url_for("main.test_detail", test_id=part.group_test_id, _external=True)}#payment-options',
            )
            if not delivered:
                return 'Payment denied. Notification delivery failed; the reason is available in the app.', 200
        except Exception:
            current_app.logger.exception('Payment denial saved, but participant notification failed')
            return 'Payment denied. Notification delivery failed; the reason is available in the app.', 200
    return 'Payment approved.' if approve else 'Payment denied and participant notified.', 200


@payment_bp.post('/<int:part_id>/review')
@login_required
def review(part_id):
    if not current_user.is_admin:
        abort(403)
    part = _authorized_part(part_id)
    decision = request.form.get('decision')
    if decision not in {'approve', 'deny'}:
        return jsonify(error='Choose Approve Payment or Deny Payment.'), 400
    message, status = review_payment(part, decision == 'approve')
    return jsonify(**{'message' if status == 200 else 'error': message}), status


@payment_bp.get('/proof/<int:submission_id>')
@login_required
def proof(submission_id):
    submission = db.get_or_404(PaymentSubmission, submission_id)
    _authorized_part(submission.participation_id)
    if not submission.image_key:
        abort(404)
    try:
        payload = read_payment_proof(submission.image_key)
    except (StorageReadError, StorageConfigurationError):
        abort(503)
    response = send_file(io.BytesIO(payload), mimetype='image/jpeg', max_age=0)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
