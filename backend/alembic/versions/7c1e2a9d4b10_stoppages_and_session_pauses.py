"""stoppages table and session pauses

Revision ID: 7c1e2a9d4b10
Revises: 0b5e6a979d04
Create Date: 2026-10-22 08:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '7c1e2a9d4b10'
down_revision: Union[str, Sequence[str], None] = '0b5e6a979d04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sessions', sa.Column('pausedSec', sa.Float(), server_default=sa.text('0'), nullable=False))
    op.add_column('sessions', sa.Column('pausedAt', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sessions', sa.Column('pauseReason', sa.String(), nullable=True))
    op.add_column('sessions', sa.Column('closedBy', sa.String(), nullable=True))
    op.create_table(
        'stoppages',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('companyId', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('stationId', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('sessionId', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('operatorId', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('startedAt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('endedAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('durationSec', sa.Float(), nullable=True),
        sa.CheckConstraint("reason IN ('breakdown', 'changeover', 'material', 'other')",
                           name='ck_stoppage_reason'),
        sa.ForeignKeyConstraint(['companyId'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['stationId'], ['stations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sessionId'], ['sessions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_stoppages_companyId'), 'stoppages', ['companyId'], unique=False)
    op.create_index(op.f('ix_stoppages_stationId'), 'stoppages', ['stationId'], unique=False)
    op.create_index(op.f('ix_stoppages_sessionId'), 'stoppages', ['sessionId'], unique=False)
    op.create_index(op.f('ix_stoppages_startedAt'), 'stoppages', ['startedAt'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_stoppages_startedAt'), table_name='stoppages')
    op.drop_index(op.f('ix_stoppages_sessionId'), table_name='stoppages')
    op.drop_index(op.f('ix_stoppages_stationId'), table_name='stoppages')
    op.drop_index(op.f('ix_stoppages_companyId'), table_name='stoppages')
    op.drop_table('stoppages')
    op.drop_column('sessions', 'closedBy')
    op.drop_column('sessions', 'pauseReason')
    op.drop_column('sessions', 'pausedAt')
    op.drop_column('sessions', 'pausedSec')
