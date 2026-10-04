"""Add the Root bridge schema: identity column, replay ledger, event dedupe, outbox.

Revision ID: c8e2f5b7d3a9
Revises: b7d1e4f9a2c6
Create Date: 2026-09-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'c8e2f5b7d3a9'
down_revision = 'b7d1e4f9a2c6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('root_user_id', sa.String(length=40), nullable=True))
        batch_op.create_index('ix_users_root_user_id', ['root_user_id'], unique=True)

    op.create_table(
        'root_bridge_nonces',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nonce_digest', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nonce_digest'),
    )
    op.create_index('ix_root_bridge_nonces_nonce_digest', 'root_bridge_nonces', ['nonce_digest'], unique=True)
    op.create_index('ix_root_bridge_nonces_expires_at', 'root_bridge_nonces', ['expires_at'])

    op.create_table(
        'root_inbound_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.String(length=120), nullable=False),
        sa.Column('event_type', sa.String(length=60), nullable=False),
        sa.Column('channel_id', sa.String(length=120), nullable=True),
        sa.Column('source_root_user_id', sa.String(length=40), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id'),
    )
    op.create_index('ix_root_inbound_events_message_id', 'root_inbound_events', ['message_id'], unique=True)

    op.create_table(
        'root_outbox',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('channel_id', sa.String(length=120), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('lease_token', sa.String(length=64), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(), nullable=True),
        sa.Column('event_key', sa.String(length=120), nullable=True),
        sa.Column('last_error', sa.String(length=300), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_key'),
    )
    op.create_index('ix_root_outbox_channel_id', 'root_outbox', ['channel_id'])
    op.create_index('ix_root_outbox_status', 'root_outbox', ['status'])
    op.create_index('ix_root_outbox_event_key', 'root_outbox', ['event_key'], unique=True)


def downgrade():
    op.drop_index('ix_root_outbox_event_key', table_name='root_outbox')
    op.drop_index('ix_root_outbox_status', table_name='root_outbox')
    op.drop_index('ix_root_outbox_channel_id', table_name='root_outbox')
    op.drop_table('root_outbox')

    op.drop_index('ix_root_inbound_events_message_id', table_name='root_inbound_events')
    op.drop_table('root_inbound_events')

    op.drop_index('ix_root_bridge_nonces_expires_at', table_name='root_bridge_nonces')
    op.drop_index('ix_root_bridge_nonces_nonce_digest', table_name='root_bridge_nonces')
    op.drop_table('root_bridge_nonces')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index('ix_users_root_user_id')
        batch_op.drop_column('root_user_id')
