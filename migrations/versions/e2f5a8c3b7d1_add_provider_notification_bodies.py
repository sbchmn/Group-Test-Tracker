"""Add per-provider notification template bodies for Discord and Root.

Revision ID: e2f5a8c3b7d1
Revises: d7f3b2c9a4e1
Create Date: 2026-09-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'e2f5a8c3b7d1'
down_revision = 'd7f3b2c9a4e1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('notification_templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('discord_body', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('root_body', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('notification_templates', schema=None) as batch_op:
        batch_op.drop_column('root_body')
        batch_op.drop_column('discord_body')
