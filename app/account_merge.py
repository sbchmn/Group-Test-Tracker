"""Transactional administrator account merges, with explicit overlap decisions."""
import hashlib
import json

from sqlalchemy import delete, or_, select, update

from . import costs, db
from .models import AccountMergeAudit, BotLinkToken, GroupTest, User


class MergeError(ValueError):
    pass


LINKS = {
    'telegram': ('telegram_user_id', 'telegram_chat_id', 'tg_username'),
    'discord': ('discord_user_id', 'discord_username'),
    'root': ('root_user_id',),
}
PAYMENT_FIELDS = ('amount_paid', 'paid_lab', 'payment_claimed_at', 'payment_verified_at',
                  'payment_verified_by_id', 'preferred_payment_option_id', 'preferred_payment_snapshot')


def _user_references():
    for table in db.metadata.sorted_tables:
        columns = [column for column in table.c
                   if any(fk.target_fullname == 'users.id' for fk in column.foreign_keys)]
        if columns:
            yield table, columns


def _values(record):
    return {column.name: getattr(record, column.name) for column in record.__table__.c}


def _serial(value):
    return json.loads(json.dumps(value, default=str))


def preview(primary, duplicate, actor_id):
    if primary.id == duplicate.id:
        raise MergeError('Choose two different accounts.')
    if primary.system_account_key or duplicate.system_account_key:
        raise MergeError('System-managed accounts cannot be merged.')
    if duplicate.id == actor_id:
        raise MergeError('Your signed-in account must be the primary account.')
    if duplicate.is_admin and duplicate.is_active and not (primary.is_admin and primary.is_active):
        others = User.query.filter(User.id.notin_([primary.id, duplicate.id]), User.is_admin.is_(True),
                                   User.is_active.is_(True), User.system_account_key.is_(None)).count()
        if not others:
            raise MergeError('This merge would remove the last active administrator. Choose an active admin as primary.')
    primary_parts = {part.group_test_id: part for part in primary.participations.all()}
    duplicate_parts = {part.group_test_id: part for part in duplicate.participations.all()}
    overlaps = [{'test': primary_parts[test_id].group_test, 'primary': primary_parts[test_id],
                 'duplicate': duplicate_parts[test_id]} for test_id in sorted(primary_parts.keys() & duplicate_parts.keys())]
    conflicts = [name for name, fields in LINKS.items()
                 if any(getattr(primary, field) for field in fields)
                 and any(getattr(duplicate, field) for field in fields)
                 and any(getattr(primary, field) != getattr(duplicate, field) for field in fields)]
    state = {'users': [_values(primary), _values(duplicate)], 'references': {}, 'tests': []}
    for table, columns in _user_references():
        state['references'][table.name] = [dict(row) for row in db.session.execute(
            select(table).where(or_(*(column.in_([primary.id, duplicate.id]) for column in columns)))
            .order_by(*table.primary_key.columns)).mappings()]
    for test_id in sorted(primary_parts.keys() | duplicate_parts.keys()):
        test = db.session.get(GroupTest, test_id)
        state['tests'].append([test_id, test.cost_revision, test.cost_snapshot])
    # Reports can change independently of account details. Include every report in
    # the preview fingerprint so approval cannot silently consume a newer payment.
    state['reports'] = [[_values(report) for report in part.payment_submissions]
                        for part in sorted(list(primary_parts.values()) + list(duplicate_parts.values()), key=lambda part: part.id)]
    token = hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()
    return {'overlaps': overlaps, 'conflicts': conflicts, 'token': token,
            'transferred_tests': len(duplicate_parts.keys() - primary_parts.keys()),
            'duplicate_test_count': len(duplicate_parts), 'link_fields': LINKS}


def merge(primary, duplicate, actor_id, form):
    # Stable lock order on databases supporting row locks; participation and test
    # version columns also reject concurrent payment or pricing edits.
    db.session.execute(select(User).where(User.id.in_([primary.id, duplicate.id]))
                       .order_by(User.id).with_for_update().execution_options(populate_existing=True)).all()
    test_ids = sorted({part.group_test_id for user in (primary, duplicate) for part in user.participations.all()})
    tests = db.session.execute(select(GroupTest).where(GroupTest.id.in_(test_ids))
                               .order_by(GroupTest.id).with_for_update()).scalars().all()
    plan = preview(primary, duplicate, actor_id)
    if form.get('preview_token') != plan['token']:
        raise MergeError('These accounts or their records changed. Review a fresh preview before confirming.')
    if form.get('confirm_merge') != 'yes':
        raise MergeError('Confirm that these accounts belong to the same person.')
    decisions = {}
    for overlap in plan['overlaps']:
        ident = overlap['test'].id
        decisions[ident] = {}
        for kind in ('membership', 'charge', 'payment'):
            choice = form.get(f'{kind}_{ident}')
            if choice not in ('primary', 'duplicate'):
                raise MergeError('Choose membership details, a charge and a payment record for every overlapping test.')
            decisions[ident][kind] = choice
    for provider in plan['conflicts']:
        if form.get('link_' + provider) not in ('primary', 'duplicate'):
            raise MergeError('Resolve each conflicting messaging link.')
    audit = {'primary': {'id': primary.id, 'username': primary.username, 'email': primary.email},
             'duplicate': {'id': duplicate.id, 'username': duplicate.username, 'email': duplicate.email},
             'participations_before': [_values(part) for user in (primary, duplicate) for part in user.participations.all()],
             'decisions': decisions, 'links': {}, 'transferred_references': {}}
    for test in tests:
        costs.ensure_snapshot(test)
    merged_participations = []
    for overlap in plan['overlaps']:
        test, kept, removed = overlap['test'], overlap['primary'], overlap['duplicate']
        selected = decisions[test.id]
        membership = overlap[selected['membership']]
        charge = overlap[selected['charge']].amount_owed
        payment = {field: getattr(overlap[selected['payment']], field) for field in PAYMENT_FIELDS}
        notes = '\n\n'.join(f'Account {part.user_id}: {part.notes}' for part in (kept, removed) if part.notes)
        membership_values = _values(membership)
        for key, value in membership_values.items():
            if key not in ('id', 'user_id', 'group_test_id', 'payment_revision', 'requested_at', 'notes', 'amount_owed', *PAYMENT_FIELDS):
                setattr(kept, key, value)
        kept.amount_owed = charge
        for field, value in payment.items():
            setattr(kept, field, value)
        kept.requested_at = min(kept.requested_at, removed.requested_at)
        kept.notes = notes or None
        kept.payment_revision += 1
        merged_participations.append(kept)
        for side in ('primary', 'duplicate'):
            for report in list(overlap[side].payment_submissions):
                if side != selected['payment']:
                    report.archived_by_merge = True
                if side == 'duplicate':
                    report.participation = kept
        if test.cost_snapshot:
            snapshot = dict(test.cost_snapshot)
            ids = snapshot.get('participant_ids', [])
            if kept.id in ids or removed.id in ids:
                kept.is_late_buy_in = False
                snapshot['participant_ids'] = sorted(set(kept.id if ident == removed.id else ident for ident in ids))
                test.cost_snapshot = snapshot
        # Move proofs before deleting their old parent; never invoke orphan cleanup
        # on evidence that now belongs to the surviving participation.
        db.session.flush()
        db.session.delete(removed)
        db.session.flush()
    for part in duplicate.participations.all():
        part.user_id = primary.id
        part.payment_revision += 1
        merged_participations.append(part)
    for provider, fields in LINKS.items():
        take_duplicate = form.get('link_' + provider) == 'duplicate' if provider in plan['conflicts'] else not any(getattr(primary, field) for field in fields)
        audit['links'][provider] = 'duplicate' if take_duplicate else 'primary'
        if take_duplicate:
            values = {field: getattr(duplicate, field) for field in fields}
            for field in fields:
                setattr(duplicate, field, None)
            db.session.flush()  # Release unique provider IDs before reassigning.
            for field, value in values.items():
                setattr(primary, field, value)
    # Participation names are separate saved fields, preferred over User.username
    # by lists, payment review and exports. They must follow the retained identity,
    # including when the duplicate was the only account participating in a test.
    for part in merged_participations:
        part.name = primary.username
        part.tg_username = primary.tg_username
    for hidden in duplicate.hidden_dashboard_tests.all():
        if primary.hidden_dashboard_tests.filter_by(group_test_id=hidden.group_test_id).first():
            db.session.delete(hidden)
        else:
            hidden.user_id = primary.id
    # Tokens must be reissued against the retained identity. Existing web sessions
    # are invalidated even when primary credentials remain unchanged.
    db.session.execute(delete(BotLinkToken).where(BotLinkToken.user_id.in_([primary.id, duplicate.id])))
    primary.session_epoch += 1
    primary_pending = {(event.test_id, event.old_status, event.new_status) for event in primary.digest_events.filter_by(sent_at=None)}
    for event in duplicate.digest_events.filter_by(sent_at=None).all():
        if (event.test_id, event.old_status, event.new_status) in primary_pending:
            db.session.delete(event)
    db.session.flush()
    handled = {'participations', 'dashboard_hidden_group_tests', 'bot_link_tokens'}
    for table, columns in _user_references():
        for column in columns:
            if table.name in handled and column.name == 'user_id':
                continue
            result = db.session.execute(update(table).where(column == duplicate.id).values({column.name: primary.id}))
            audit['transferred_references'][f'{table.name}.{column.name}'] = result.rowcount
    for test in tests:
        costs.recalculate(test)  # Quiet; frozen assigned charges stay unchanged.
    for test in GroupTest.query.all():
        snapshot = test.cost_snapshot
        if snapshot and snapshot.get('inputs', {}).get('donor_shipping_reimbursed_by_id') == duplicate.id:
            test.cost_snapshot = {**snapshot, 'inputs': {**snapshot['inputs'], 'donor_shipping_reimbursed_by_id': primary.id}}
    db.session.flush()
    db.session.expire_all()
    audit['participations_after'] = [_values(part) for part in primary.participations.all()]
    db.session.add(AccountMergeAudit(performed_by_id=actor_id, primary_user_id=primary.id,
                                    duplicate_user_id=duplicate.id, details=_serial(audit)))
    # Core delete avoids stale ORM relationship collections deleting moved rows.
    db.session.execute(delete(User.__table__).where(User.id == duplicate.id))
    db.session.flush()
    return plan
