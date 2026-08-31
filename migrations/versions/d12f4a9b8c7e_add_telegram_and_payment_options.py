"""Add telegram linkage and payment option schema.

Revision ID: d12f4a9b8c7e
Revises: c3d9e1f4a7b2
Create Date: 2026-08-31 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd12f4a9b8c7e'
down_revision = 'c3d9e1f4a7b2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('telegram_chat_id', sa.String(length=80), nullable=True))
        batch_op.create_index(batch_op.f('ix_users_telegram_chat_id'), ['telegram_chat_id'], unique=False)

    op.create_table(
        'telegram_link_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=120), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )
    with op.batch_alter_table('telegram_link_tokens', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_telegram_link_tokens_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_telegram_link_tokens_token'), ['token'], unique=True)

    op.create_table(
        'payment_options',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('method_type', sa.String(length=40), nullable=False),
        sa.Column('recipient_name', sa.String(length=120), nullable=True),
        sa.Column('account_handle', sa.String(length=200), nullable=True),
        sa.Column('wallet_address', sa.String(length=255), nullable=True),
        sa.Column('network', sa.String(length=120), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('qr_payload_override', sa.String(length=500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('payment_options', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_payment_options_method_type'), ['method_type'], unique=False)

    op.create_table(
        'group_test_payment_options',
        sa.Column('group_test_id', sa.Integer(), nullable=False),
        sa.Column('payment_option_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['group_test_id'], ['group_tests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['payment_option_id'], ['payment_options.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('group_test_id', 'payment_option_id'),
    )

    with op.batch_alter_table('participations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('preferred_payment_option_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('preferred_payment_snapshot', sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            'fk_participations_preferred_payment_option_id_payment_options',
            'payment_options',
            ['preferred_payment_option_id'],
            ['id'],
        )


def downgrade():
    with op.batch_alter_table('participations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_participations_preferred_payment_option_id_payment_options', type_='foreignkey')
        batch_op.drop_column('preferred_payment_snapshot')
        batch_op.drop_column('preferred_payment_option_id')

    op.drop_table('group_test_payment_options')

    with op.batch_alter_table('payment_options', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_payment_options_method_type'))
    op.drop_table('payment_options')

    with op.batch_alter_table('telegram_link_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_telegram_link_tokens_token'))
        batch_op.drop_index(batch_op.f('ix_telegram_link_tokens_user_id'))
    op.drop_table('telegram_link_tokens')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_telegram_chat_id'))
        batch_op.drop_column('telegram_chat_id')
