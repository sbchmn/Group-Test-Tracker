"""Add user digest schedule fields and event queue table.

Revision ID: f0c4a6b1d9e2
Revises: e3a1c9d4b7f2
Create Date: 2026-08-31 00:20:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f0c4a6b1d9e2'
down_revision = 'e3a1c9d4b7f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('digest_frequency', sa.String(length=20), nullable=False, server_default='off'))
        batch_op.add_column(sa.Column('digest_hourly_minute_utc', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('digest_daily_hour_utc', sa.Integer(), nullable=False, server_default='9'))
        batch_op.add_column(sa.Column('digest_last_sent_at', sa.DateTime(), nullable=True))

    op.create_table(
        'user_digest_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('test_id', sa.Integer(), nullable=False),
        sa.Column('test_title', sa.String(length=200), nullable=False),
        sa.Column('old_status', sa.String(length=20), nullable=False),
        sa.Column('new_status', sa.String(length=20), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('user_digest_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_digest_events_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_digest_events_test_id'), ['test_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_digest_events_sent_at'), ['sent_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_digest_events_created_at'), ['created_at'], unique=False)


def downgrade():
    with op.batch_alter_table('user_digest_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_digest_events_created_at'))
        batch_op.drop_index(batch_op.f('ix_user_digest_events_sent_at'))
        batch_op.drop_index(batch_op.f('ix_user_digest_events_test_id'))
        batch_op.drop_index(batch_op.f('ix_user_digest_events_user_id'))
    op.drop_table('user_digest_events')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('digest_last_sent_at')
        batch_op.drop_column('digest_daily_hour_utc')
        batch_op.drop_column('digest_hourly_minute_utc')
        batch_op.drop_column('digest_frequency')
