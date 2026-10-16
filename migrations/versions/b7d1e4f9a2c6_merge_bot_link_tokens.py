"""Merge per-provider bot link-token tables into one provider-keyed table.

Adds bot_link_tokens, copies existing Telegram and Discord tokens across (newly
issued ids are deliberately not preserved -- nothing references them by id), then
drops the two single-provider tables.

Revision ID: b7d1e4f9a2c6
Revises: e2f5a8c3b7d1
Create Date: 2026-09-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'b7d1e4f9a2c6'
down_revision = 'e2f5a8c3b7d1'
branch_labels = None
depends_on = None

_LINK_TOKEN_COLUMNS = (
    'user_id',
    'token',
    'expires_at',
    'used_at',
    'created_at',
)


def _create_legacy_table(table_name):
    op.create_table(
        table_name,
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=120), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )
    op.create_index(f'ix_{table_name}_user_id', table_name, ['user_id'])
    op.create_index(f'ix_{table_name}_token', table_name, ['token'], unique=True)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # SQLite and MySQL do not roll back DDL, so a copy that fails after the table is
    # created leaves bot_link_tokens behind with alembic_version still at the
    # previous revision. Recreating unconditionally makes every retry die on
    # "table already exists"; skipping when the table is present lets the operator
    # fix the data and simply run the upgrade again.
    if 'bot_link_tokens' not in existing_tables:
        op.create_table(
            'bot_link_tokens',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('provider', sa.String(length=20), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('token', sa.String(length=120), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('used_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('provider', 'token', name='_bot_link_token_provider_token_uc'),
        )
        op.create_index('ix_bot_link_tokens_provider', 'bot_link_tokens', ['provider'])
        op.create_index('ix_bot_link_tokens_user_id', 'bot_link_tokens', ['user_id'])
        op.create_index('ix_bot_link_tokens_token', 'bot_link_tokens', ['token'])

    columns = ', '.join(_LINK_TOKEN_COLUMNS)
    for provider, table_name in (('telegram', 'telegram_link_tokens'), ('discord', 'discord_link_tokens')):
        if table_name not in existing_tables:
            continue
        bind.execute(
            sa.text(
                f"INSERT INTO bot_link_tokens (provider, {columns}) "
                f"SELECT :provider, {columns} FROM {table_name}"
            ),
            {'provider': provider},
        )

    for table_name in ('telegram_link_tokens', 'discord_link_tokens'):
        if table_name in existing_tables:
            op.drop_table(table_name)


def downgrade():
    _create_legacy_table('telegram_link_tokens')
    _create_legacy_table('discord_link_tokens')

    columns = ', '.join(_LINK_TOKEN_COLUMNS)
    bind = op.get_bind()
    for provider, table_name in (('telegram', 'telegram_link_tokens'), ('discord', 'discord_link_tokens')):
        bind.execute(
            sa.text(
                f"INSERT INTO {table_name} ({columns}) "
                f"SELECT {columns} FROM bot_link_tokens WHERE provider = :provider"
            ),
            {'provider': provider},
        )

    op.drop_index('ix_bot_link_tokens_token', table_name='bot_link_tokens')
    op.drop_index('ix_bot_link_tokens_user_id', table_name='bot_link_tokens')
    op.drop_index('ix_bot_link_tokens_provider', table_name='bot_link_tokens')
    op.drop_table('bot_link_tokens')
