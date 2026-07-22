"""Compatibility revision for historical Alembic state.

Revision ID: 084c3f28ae26
Revises: f67a5b9c1d2e
Create Date: 2026-07-22 00:00:00.000000

This revision preserves compatibility for environments that already recorded
this historical revision ID but do not have the corresponding migration file
available in the repository.
"""

# revision identifiers, used by Alembic.
revision = '084c3f28ae26'
down_revision = 'f67a5b9c1d2e'
branch_labels = None
depends_on = None


def upgrade():
    # No schema changes are required for this compatibility revision.
    pass


def downgrade():
    # No schema changes were applied by this revision.
    pass
