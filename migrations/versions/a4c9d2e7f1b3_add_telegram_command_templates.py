"""Add telegram command templates table.

Revision ID: a4c9d2e7f1b3
Revises: f0c4a6b1d9e2
Create Date: 2026-09-01 00:40:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a4c9d2e7f1b3'
down_revision = 'f0c4a6b1d9e2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'telegram_command_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('command', sa.String(length=40), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('reply_text', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('command'),
    )
    with op.batch_alter_table('telegram_command_templates', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_telegram_command_templates_command'), ['command'], unique=True)


def downgrade():
    with op.batch_alter_table('telegram_command_templates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_telegram_command_templates_command'))
    op.drop_table('telegram_command_templates')
