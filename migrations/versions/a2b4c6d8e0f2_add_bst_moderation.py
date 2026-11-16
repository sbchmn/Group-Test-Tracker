"""Add independent Telegram BST applications, policies, and moderation state."""
from alembic import op
import sqlalchemy as sa

revision = 'a2b4c6d8e0f2'
down_revision = 'f1a3c5e7b9d2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('bst_conversations',
    sa.Column('telegram_user_id', sa.String(length=40), nullable=False),
    sa.Column('state', sa.JSON(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('telegram_user_id')
    )
    op.create_table('bst_topics',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('chat_id', sa.String(length=80), nullable=False),
    sa.Column('thread_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('code', sa.String(length=40), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('options', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('chat_id', 'thread_id', name='uq_bst_topic_location'),
    sa.UniqueConstraint('code')
    )
    op.create_table('bst_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('topic_id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.String(length=80), nullable=False),
    sa.Column('telegram_user_id', sa.String(length=40), nullable=False),
    sa.Column('album_id', sa.String(length=100), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('due_at', sa.DateTime(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['bst_topics.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('topic_id', 'message_id', name='uq_bst_message_location')
    )
    op.create_index(op.f('ix_bst_messages_album_id'), 'bst_messages', ['album_id'], unique=False)
    op.create_index(op.f('ix_bst_messages_due_at'), 'bst_messages', ['due_at'], unique=False)
    op.create_index(op.f('ix_bst_messages_topic_id'), 'bst_messages', ['topic_id'], unique=False)
    op.create_table('bst_vendors',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('topic_id', sa.Integer(), nullable=False),
    sa.Column('telegram_user_id', sa.String(length=40), nullable=False),
    sa.Column('username', sa.String(length=80), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('is_approved', sa.Boolean(), nullable=False),
    sa.Column('draft', sa.JSON(), nullable=False),
    sa.Column('approved', sa.JSON(), nullable=False),
    sa.Column('verified_email', sa.String(length=254), nullable=True),
    sa.Column('verification', sa.JSON(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['bst_topics.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('topic_id', 'telegram_user_id', name='uq_bst_vendor_identity')
    )
    op.create_index(op.f('ix_bst_vendors_status'), 'bst_vendors', ['status'], unique=False)
    op.create_index(op.f('ix_bst_vendors_submitted_at'), 'bst_vendors', ['submitted_at'], unique=False)
    op.create_index(op.f('ix_bst_vendors_topic_id'), 'bst_vendors', ['topic_id'], unique=False)
    op.create_table('bst_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('topic_id', sa.Integer(), nullable=False),
    sa.Column('vendor_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('actor_telegram_id', sa.String(length=40), nullable=True),
    sa.Column('actor_gtm_id', sa.Integer(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['bst_topics.id'], ),
    sa.ForeignKeyConstraint(['vendor_id'], ['bst_vendors.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bst_events_vendor_id'), 'bst_events', ['vendor_id'], unique=False)
    op.create_table('bst_notices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=False),
    sa.Column('recipient', sa.String(length=80), nullable=False),
    sa.Column('subject', sa.String(length=160), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(), nullable=False),
    sa.Column('complete', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['bst_events.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id', 'recipient', name='uq_bst_notice_event_recipient')
    )
    op.create_index(op.f('ix_bst_notices_next_attempt_at'), 'bst_notices', ['next_attempt_at'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_bst_notices_next_attempt_at'), table_name='bst_notices')
    op.drop_table('bst_notices')
    op.drop_index(op.f('ix_bst_events_vendor_id'), table_name='bst_events')
    op.drop_table('bst_events')
    op.drop_index(op.f('ix_bst_vendors_topic_id'), table_name='bst_vendors')
    op.drop_index(op.f('ix_bst_vendors_submitted_at'), table_name='bst_vendors')
    op.drop_index(op.f('ix_bst_vendors_status'), table_name='bst_vendors')
    op.drop_table('bst_vendors')
    op.drop_index(op.f('ix_bst_messages_topic_id'), table_name='bst_messages')
    op.drop_index(op.f('ix_bst_messages_due_at'), table_name='bst_messages')
    op.drop_index(op.f('ix_bst_messages_album_id'), table_name='bst_messages')
    op.drop_table('bst_messages')
    op.drop_table('bst_topics')
    op.drop_table('bst_conversations')
