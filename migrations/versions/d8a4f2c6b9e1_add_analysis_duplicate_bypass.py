"""Allow explicit analysis runs to bypass completed-run deduplication."""

from alembic import op
import sqlalchemy as sa


revision = 'd8a4f2c6b9e1'
down_revision = 'e4b7c9d1a2f3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'result_analysis_runs',
        sa.Column('bypass_duplicate_check', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column('result_analysis_runs', 'bypass_duplicate_check')
