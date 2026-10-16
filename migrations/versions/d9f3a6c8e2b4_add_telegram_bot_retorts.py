"""Add persistent Telegram retort deduplication and group cooldowns.

Revision ID: d9f3a6c8e2b4
Revises: c8e2f5b7d3a9
"""
from alembic import op
import sqlalchemy as sa

revision = 'd9f3a6c8e2b4'
down_revision = 'c8e2f5b7d3a9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'telegram_bot_retorts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('chat_id', sa.String(80), nullable=False),
        sa.Column('original_message_id', sa.BigInteger(), nullable=False),
        sa.Column('bot_message_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('response_message_id', sa.String(120), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('chat_id', 'original_message_id', name='_tg_retort_original_uc'),
    )
    op.create_table(
        'telegram_bot_retort_cooldowns',
        sa.Column('chat_id', sa.String(80), primary_key=True),
        sa.Column('next_allowed_at', sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table('telegram_bot_retort_cooldowns')
    op.drop_table('telegram_bot_retorts')
