"""Track COA prompts and expiring Telegram menus."""
from alembic import op
import sqlalchemy as sa

revision = 'f1a3c5e7b9d2'
down_revision = 'e7a9b1c3d5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('telegram_interactions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('chat_id', sa.String(120), nullable=False),
        sa.Column('thread_id', sa.String(80)),
        sa.Column('telegram_user_id', sa.String(40), nullable=False),
        sa.Column('bot_message_id', sa.String(80), nullable=False),
        sa.Column('command_message_id', sa.String(80)),
        sa.Column('is_ephemeral', sa.Boolean(), nullable=False),
        sa.Column('command_is_ephemeral', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('closed_at', sa.DateTime()),
        sa.Column('menu_deleted', sa.Boolean(), nullable=False),
        sa.Column('command_deleted', sa.Boolean(), nullable=False),
        sa.Column('cleanup_complete', sa.Boolean(), nullable=False),
        sa.Column('cleanup_attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime()))
    op.create_index('ix_telegram_interactions_expires_at', 'telegram_interactions', ['expires_at'])


def downgrade():
    op.drop_table('telegram_interactions')
