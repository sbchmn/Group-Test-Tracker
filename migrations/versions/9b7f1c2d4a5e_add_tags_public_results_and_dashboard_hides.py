"""Add tags, public results, and dashboard hide state.

Revision ID: 9b7f1c2d4a5e
Revises: f5d832cd8f6a
Create Date: 2026-08-20 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9b7f1c2d4a5e'
down_revision = 'f5d832cd8f6a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('group_tests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('results_posted_at', sa.DateTime(), nullable=True))

    op.create_table(
        'tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('normalized_name', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('normalized_name'),
    )
    with op.batch_alter_table('tags', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tags_name'), ['name'], unique=True)
        batch_op.create_index(batch_op.f('ix_tags_normalized_name'), ['normalized_name'], unique=True)

    op.create_table(
        'public_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('results_link', sa.String(length=500), nullable=False),
        sa.Column('posted_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'dashboard_hidden_group_tests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('group_test_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['group_test_id'], ['group_tests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'group_test_id', name='_dashboard_hidden_user_test_uc'),
    )

    op.create_table(
        'group_test_tags',
        sa.Column('group_test_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['group_test_id'], ['group_tests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('group_test_id', 'tag_id'),
    )

    op.create_table(
        'public_result_tags',
        sa.Column('public_result_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['public_result_id'], ['public_results.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('public_result_id', 'tag_id'),
    )


def downgrade():
    op.drop_table('public_result_tags')
    op.drop_table('group_test_tags')
    op.drop_table('dashboard_hidden_group_tests')
    op.drop_table('public_results')
    with op.batch_alter_table('tags', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tags_normalized_name'))
        batch_op.drop_index(batch_op.f('ix_tags_name'))
    op.drop_table('tags')
    with op.batch_alter_table('group_tests', schema=None) as batch_op:
        batch_op.drop_column('results_posted_at')
