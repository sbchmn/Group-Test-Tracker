"""Add item_results to public_results

Revision ID: 7c1a2b3d4e5f
Revises: 9b7f1c2d4a5e
Create Date: 2026-08-20 00:00:01.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c1a2b3d4e5f'
down_revision = '9b7f1c2d4a5e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('public_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('item_results', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('public_results', schema=None) as batch_op:
        batch_op.drop_column('item_results')
