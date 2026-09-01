"""Add Telegram command controls and invocation logs.

Revision ID: b6e2d4c8a1f9
Revises: a4c9d2e7f1b3
Create Date: 2026-09-01 01:05:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b6e2d4c8a1f9'
down_revision = 'a4c9d2e7f1b3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('telegram_command_templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('args_policy', sa.String(length=20), nullable=False, server_default='any'))
        batch_op.add_column(sa.Column('args_regex', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('args_help_text', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('rate_limit_window_seconds', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('rate_limit_max_calls', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('rate_limit_message', sa.Text(), nullable=True))
        batch_op.create_index(batch_op.f('ix_telegram_command_templates_category'), ['category'], unique=False)

    op.create_table(
        'telegram_command_invocations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('command_template_id', sa.Integer(), nullable=False),
        sa.Column('chat_id', sa.String(length=80), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['command_template_id'], ['telegram_command_templates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('telegram_command_invocations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_telegram_command_invocations_command_template_id'), ['command_template_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_telegram_command_invocations_chat_id'), ['chat_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_telegram_command_invocations_created_at'), ['created_at'], unique=False)


def downgrade():
    with op.batch_alter_table('telegram_command_invocations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_telegram_command_invocations_created_at'))
        batch_op.drop_index(batch_op.f('ix_telegram_command_invocations_chat_id'))
        batch_op.drop_index(batch_op.f('ix_telegram_command_invocations_command_template_id'))
    op.drop_table('telegram_command_invocations')

    with op.batch_alter_table('telegram_command_templates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_telegram_command_templates_category'))
        batch_op.drop_column('rate_limit_message')
        batch_op.drop_column('rate_limit_max_calls')
        batch_op.drop_column('rate_limit_window_seconds')
        batch_op.drop_column('args_help_text')
        batch_op.drop_column('args_regex')
        batch_op.drop_column('args_policy')
        batch_op.drop_column('category')
