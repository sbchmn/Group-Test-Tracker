"""Add tag retirement fields: an active flag, a merge-forward pointer, and a flag that
keeps a live tag out of the bot menus.

Retiring a tag must never hide published content, so ``is_active`` only affects the
admin vocabulary picker. ``merged_into_id`` keeps a merged-away tag addressable by its
old id, which public-results tag pages and bot pagination callbacks both reference.
``hidden_from_bots`` is the control that does affect the menus, kept separate so hiding
an entry is always deliberate rather than a side effect of tidying vocabulary.

Revision ID: d7f3b2c9a4e1
Revises: c4d5e6f7a8b9
Create Date: 2026-09-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'd7f3b2c9a4e1'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tags', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('merged_into_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('hidden_from_bots', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_foreign_key('fk_tags_merged_into_tags', 'tags', ['merged_into_id'], ['id'])
        batch_op.create_index('ix_tags_merged_into_id', ['merged_into_id'])


def downgrade():
    with op.batch_alter_table('tags', schema=None) as batch_op:
        batch_op.drop_index('ix_tags_merged_into_id')
        batch_op.drop_constraint('fk_tags_merged_into_tags', type_='foreignkey')
        batch_op.drop_column('hidden_from_bots')
        batch_op.drop_column('merged_into_id')
        batch_op.drop_column('is_active')
