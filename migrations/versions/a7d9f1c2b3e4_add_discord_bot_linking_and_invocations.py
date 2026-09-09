"""Add Discord bot linking and command invocation tables.

Revision ID: a7d9f1c2b3e4
Revises: c9f1e2a4b7d6
Create Date: 2026-09-01 02:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7d9f1c2b3e4'
down_revision = 'c9f1e2a4b7d6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('discord_username', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('discord_user_id', sa.String(length=40), nullable=True))
        batch_op.create_index(batch_op.f('ix_users_discord_username'), ['discord_username'], unique=False)
        batch_op.create_index(batch_op.f('ix_users_discord_user_id'), ['discord_user_id'], unique=True)

    op.create_table(
        'discord_link_tokens',
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
    with op.batch_alter_table('discord_link_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_discord_link_tokens_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_discord_link_tokens_token'), ['token'], unique=True)

    op.create_table(
        'discord_command_invocations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('command_template_id', sa.Integer(), nullable=False),
        sa.Column('channel_id', sa.String(length=80), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['command_template_id'], ['telegram_command_templates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('discord_command_invocations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_discord_command_invocations_command_template_id'), ['command_template_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_discord_command_invocations_channel_id'), ['channel_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_discord_command_invocations_created_at'), ['created_at'], unique=False)


def downgrade():
    with op.batch_alter_table('discord_command_invocations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_discord_command_invocations_created_at'))
        batch_op.drop_index(batch_op.f('ix_discord_command_invocations_channel_id'))
        batch_op.drop_index(batch_op.f('ix_discord_command_invocations_command_template_id'))
    op.drop_table('discord_command_invocations')

    with op.batch_alter_table('discord_link_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_discord_link_tokens_token'))
        batch_op.drop_index(batch_op.f('ix_discord_link_tokens_user_id'))
    op.drop_table('discord_link_tokens')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_discord_user_id'))
        batch_op.drop_index(batch_op.f('ix_users_discord_username'))
        batch_op.drop_column('discord_user_id')
        batch_op.drop_column('discord_username')
