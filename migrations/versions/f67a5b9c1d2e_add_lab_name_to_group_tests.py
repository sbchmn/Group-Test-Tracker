"""Add lab_name to group_tests

Revision ID: f67a5b9c1d2e
Revises: 54b86edcab2f
Create Date: 2026-07-07 11:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f67a5b9c1d2e'
down_revision = '54b86edcab2f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('group_tests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lab_name', sa.String(length=200), nullable=True))


def downgrade():
    with op.batch_alter_table('group_tests', schema=None) as batch_op:
        batch_op.drop_column('lab_name')
