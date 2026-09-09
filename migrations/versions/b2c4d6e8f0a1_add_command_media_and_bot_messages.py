"""Add media-enabled bot command fields and message ownership records."""

from alembic import op
import sqlalchemy as sa


revision = 'b2c4d6e8f0a1'
down_revision = 'a7d9f1c2b3e4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('telegram_command_templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('response_image_key', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('allow_admin_bot_updates', sa.Boolean(), nullable=False, server_default='0'))

    op.create_table(
        'bot_command_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('command_template_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=30), nullable=False),
        sa.Column('chat_id', sa.String(length=120), nullable=False),
        sa.Column('message_id', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['command_template_id'], ['telegram_command_templates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'chat_id', 'message_id', name='_bot_command_provider_message_uc'),
    )
    with op.batch_alter_table('bot_command_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bot_command_messages_command_template_id'), ['command_template_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_bot_command_messages_provider'), ['provider'], unique=False)
        batch_op.create_index(batch_op.f('ix_bot_command_messages_chat_id'), ['chat_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_bot_command_messages_message_id'), ['message_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_bot_command_messages_created_at'), ['created_at'], unique=False)


def downgrade():
    with op.batch_alter_table('bot_command_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bot_command_messages_created_at'))
        batch_op.drop_index(batch_op.f('ix_bot_command_messages_message_id'))
        batch_op.drop_index(batch_op.f('ix_bot_command_messages_chat_id'))
        batch_op.drop_index(batch_op.f('ix_bot_command_messages_provider'))
        batch_op.drop_index(batch_op.f('ix_bot_command_messages_command_template_id'))
    op.drop_table('bot_command_messages')

    with op.batch_alter_table('telegram_command_templates', schema=None) as batch_op:
        batch_op.drop_column('allow_admin_bot_updates')
        batch_op.drop_column('response_image_key')