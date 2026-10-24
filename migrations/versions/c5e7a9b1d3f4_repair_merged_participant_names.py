"""Repair stale participant identity fields left by completed account merges."""
from alembic import op
import sqlalchemy as sa

revision = 'c5e7a9b1d3f4'
down_revision = 'b4d6f8a0c2e3'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    audits = sa.table('account_merge_audits', sa.column('id', sa.Integer),
        sa.column('primary_user_id', sa.Integer), sa.column('duplicate_user_id', sa.Integer),
        sa.column('details', sa.JSON))
    users = sa.table('users', sa.column('id', sa.Integer), sa.column('username', sa.String),
                     sa.column('tg_username', sa.String))
    parts = sa.table('participations', sa.column('id', sa.Integer), sa.column('user_id', sa.Integer),
        sa.column('name', sa.String), sa.column('tg_username', sa.String), sa.column('payment_revision', sa.Integer))
    for audit in connection.execute(sa.select(audits).order_by(audits.c.id)).mappings():
        primary = connection.execute(sa.select(users).where(users.c.id == audit['primary_user_id'])).mappings().first()
        if primary is None:
            continue  # A later merge may have removed this primary identity too.
        details = audit['details'] or {}
        affected_groups = {row['group_test_id'] for row in details.get('participations_before', [])
                           if row.get('user_id') == audit['duplicate_user_id']}
        for after in details.get('participations_after', []):
            if after.get('group_test_id') not in affected_groups:
                continue
            current = connection.execute(sa.select(parts).where(
                parts.c.id == after['id'], parts.c.user_id == primary['id'])).mappings().first()
            if current is None:
                continue
            changes = {}
            for field, replacement in [('name', primary['username']), ('tg_username', primary['tg_username'])]:
                # Respect any edits made since the merge, and never touch a row
                # based on an old name alone. The audit identifies exact records.
                if current[field] == after.get(field) and current[field] != replacement:
                    changes[field] = replacement
            if changes:
                changes['payment_revision'] = parts.c.payment_revision + 1
                connection.execute(parts.update().where(parts.c.id == current['id'],
                    parts.c.user_id == primary['id'], parts.c.payment_revision == current['payment_revision']).values(**changes))


def downgrade():
    # Data repair only. Restoring a removed account's label would reintroduce the
    # bug and could overwrite edits made after upgrade, so keep repaired values.
    pass
