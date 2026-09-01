"""Add Telegram command chat/thread scope controls.

Revision ID: c9f1e2a4b7d6
Revises: b6e2d4c8a1f9
Create Date: 2026-09-01 01:35:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9f1e2a4b7d6'
down_revision = 'b6e2d4c8a1f9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('telegram_command_templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('allow_non_private', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('allowed_chat_ids', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('allowed_thread_ids', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('telegram_command_templates', schema=None) as batch_op:
        batch_op.drop_column('allowed_thread_ids')
        batch_op.drop_column('allowed_chat_ids')
        batch_op.drop_column('allow_non_private')
