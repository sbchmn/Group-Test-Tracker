"""Add notification templates/configs and profile-related user fields.

Revision ID: f5d832cd8f6a
Revises: 084c3f28ae26
Create Date: 2026-07-22 00:01:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f5d832cd8f6a'
down_revision = '084c3f28ae26'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('receive_group_test_notifications', sa.Boolean(), nullable=False, server_default='1'))
        batch_op.add_column(sa.Column('notification_channel', sa.String(length=20), nullable=False, server_default='email'))

    op.create_table(
        'notification_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('email_subject', sa.String(length=200), nullable=True),
        sa.Column('email_body', sa.Text(), nullable=True),
        sa.Column('telegram_body', sa.Text(), nullable=True),
        sa.Column('hide_from_participant_notifications', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('is_default_password_reset', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('is_default_registration_welcome', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('notification_templates', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notification_templates_name'), ['name'], unique=True)

    op.create_table(
        'notification_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('notification_configs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notification_configs_key'), ['key'], unique=True)

    with op.batch_alter_table('group_tests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('donor_shipping_cost', sa.Float(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('donor_shipping_reimbursement', sa.String(length=40), nullable=False, server_default='credit'))
        batch_op.add_column(sa.Column('donor_shipping_reimbursed_by_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_group_tests_donor_shipping_reimbursed_by_id_users', 'users', ['donor_shipping_reimbursed_by_id'], ['id'])


def downgrade():
    with op.batch_alter_table('group_tests', schema=None) as batch_op:
        batch_op.drop_constraint('fk_group_tests_donor_shipping_reimbursed_by_id_users', type_='foreignkey')
        batch_op.drop_column('donor_shipping_reimbursed_by_id')
        batch_op.drop_column('donor_shipping_reimbursement')
        batch_op.drop_column('donor_shipping_cost')

    with op.batch_alter_table('notification_configs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notification_configs_key'))
    op.drop_table('notification_configs')

    with op.batch_alter_table('notification_templates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notification_templates_name'))
    op.drop_table('notification_templates')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('notification_channel')
        batch_op.drop_column('receive_group_test_notifications')
