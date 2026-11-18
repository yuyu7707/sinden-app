"""per-user plans

プランを「ペア」ではなく「支払った人」が持つように変える（個人プラン・ふたりプラン）。
女神の鏡の回数も1人ずつ数える。

Revision ID: 64edfe7d5490
Revises: 31d71e22e520
Create Date: 2026-11-17 18:16:11.663703

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '64edfe7d5490'
down_revision = '31d71e22e520'
branch_labels = None
depends_on = None


def upgrade():
    # 鏡の利用記録は、公開前のためペア単位の記録を捨てて、1人ずつ数える表に作り直す
    op.drop_table('mirror_uses')
    op.create_table('mirror_uses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('visit_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_mirror_uses_user_id'),
    sa.PrimaryKeyConstraint('id')
    )

    with op.batch_alter_table('pairs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('comped', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.drop_column('lifetime')
        batch_op.drop_column('stripe_customer_id')
        batch_op.drop_column('subscription_status')
        batch_op.drop_column('stripe_subscription_id')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('plan', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('stripe_customer_id', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('subscription_status', sa.String(length=30), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('subscription_status')
        batch_op.drop_column('stripe_subscription_id')
        batch_op.drop_column('stripe_customer_id')
        batch_op.drop_column('plan')

    with op.batch_alter_table('pairs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('subscription_status', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('stripe_customer_id', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('lifetime', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.drop_column('comped')

    op.drop_table('mirror_uses')
    op.create_table('mirror_uses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pair_id', sa.Integer(), nullable=False),
    sa.Column('visit_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['pair_id'], ['pairs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
