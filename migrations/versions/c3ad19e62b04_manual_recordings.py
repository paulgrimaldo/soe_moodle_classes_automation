"""Preserve explicitly linked recordings during discovery."""
from alembic import op
import sqlalchemy as sa

revision = "c3ad19e62b04"
down_revision = "ba91c321ab02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("academic_sessions", sa.Column("recordings_manual", sa.Boolean(), nullable=False,
                                                server_default=sa.text("0")))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM academic_sessions WHERE recordings_manual = 1 LIMIT 1")).first():
        raise RuntimeError("Manual recording links exist; downgrade would remove their protection")
    # Native DROP COLUMN keeps referencing recordings/jobs intact with FK checks on.
    op.drop_column("academic_sessions", "recordings_manual")
