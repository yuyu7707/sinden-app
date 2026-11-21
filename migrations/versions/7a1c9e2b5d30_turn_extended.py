"""turn extended

Revision ID: 7a1c9e2b5d30
Revises: 3c6173606b9f
Create Date: 2026-11-21 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7a1c9e2b5d30'
down_revision = '3c6173606b9f'
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('visits', schema=None) as batch_op:
        batch_op.add_column(sa.Column('turn_extended', sa.Boolean(), server_default=sa.false(), nullable=False))

def downgrade():
    with op.batch_alter_table('visits', schema=None) as batch_op:
        batch_op.drop_column('turn_extended')
