"""Add telegram webhook replay and digest tables.

Revision ID: e3a1c9d4b7f2
Revises: d12f4a9b8c7e
Create Date: 2026-08-31 00:00:01.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3a1c9d4b7f2'
down_revision = 'd12f4a9b8c7e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telegram_user_id', sa.String(length=40), nullable=True))
        batch_op.create_index(batch_op.f('ix_users_telegram_user_id'), ['telegram_user_id'], unique=True)

    op.create_table(
        'telegram_webhook_updates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('update_id', sa.BigInteger(), nullable=False),
        sa.Column('source_ip', sa.String(length=45), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('update_id'),
    )
    with op.batch_alter_table('telegram_webhook_updates', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_telegram_webhook_updates_update_id'), ['update_id'], unique=True)

    op.create_table(
        'telegram_status_digest_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('chat_id', sa.String(length=120), nullable=False),
        sa.Column('window_bucket', sa.String(length=32), nullable=False),
        sa.Column('event_key', sa.String(length=120), nullable=False),
        sa.Column('test_id', sa.Integer(), nullable=False),
        sa.Column('test_title', sa.String(length=200), nullable=False),
        sa.Column('old_status', sa.String(length=20), nullable=False),
        sa.Column('new_status', sa.String(length=20), nullable=False),
        sa.Column('mention_usernames', sa.Text(), nullable=True),
        sa.Column('mention_user_ids', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chat_id', 'window_bucket', 'event_key', name='_tg_digest_chat_window_event_uc'),
    )
    with op.batch_alter_table('telegram_status_digest_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_telegram_status_digest_events_chat_id'), ['chat_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_telegram_status_digest_events_window_bucket'), ['window_bucket'], unique=False)
        batch_op.create_index(batch_op.f('ix_telegram_status_digest_events_event_key'), ['event_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_telegram_status_digest_events_test_id'), ['test_id'], unique=False)


def downgrade():
    with op.batch_alter_table('telegram_status_digest_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_telegram_status_digest_events_test_id'))
        batch_op.drop_index(batch_op.f('ix_telegram_status_digest_events_event_key'))
        batch_op.drop_index(batch_op.f('ix_telegram_status_digest_events_window_bucket'))
        batch_op.drop_index(batch_op.f('ix_telegram_status_digest_events_chat_id'))
    op.drop_table('telegram_status_digest_events')

    with op.batch_alter_table('telegram_webhook_updates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_telegram_webhook_updates_update_id'))
    op.drop_table('telegram_webhook_updates')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_telegram_user_id'))
        batch_op.drop_column('telegram_user_id')
