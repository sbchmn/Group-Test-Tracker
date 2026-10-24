"""Freeze existing non-recruiting tests without changing any assigned charges."""
from alembic import op
import sqlalchemy as sa

revision = 'a9c3e5f7b2d4'
down_revision = 'f8a2c4e6b9d1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('group_tests') as batch:
        batch.add_column(sa.Column('costs_frozen', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('costs_frozen_at', sa.DateTime()))
        batch.add_column(sa.Column('costs_frozen_by_id', sa.Integer()))
        batch.create_foreign_key('fk_group_tests_costs_frozen_by_users', 'users', ['costs_frozen_by_id'], ['id'])
        batch.add_column(sa.Column('cost_snapshot', sa.JSON()))
        batch.add_column(sa.Column('late_buy_in_amount', sa.Numeric(12, 2)))
        batch.add_column(sa.Column('cost_revision', sa.Integer(), nullable=False, server_default='1'))
    with op.batch_alter_table('participations') as batch:
        batch.add_column(sa.Column('is_late_buy_in', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(sa.text("UPDATE group_tests SET costs_frozen = :locked WHERE status <> 'recruiting'").bindparams(locked=True))


def downgrade():
    with op.batch_alter_table('participations') as batch:
        batch.drop_column('is_late_buy_in')
    with op.batch_alter_table('group_tests') as batch:
        batch.drop_constraint('fk_group_tests_costs_frozen_by_users', type_='foreignkey')
        for name in ['cost_revision', 'late_buy_in_amount', 'cost_snapshot', 'costs_frozen_by_id', 'costs_frozen_at', 'costs_frozen']:
            batch.drop_column(name)
