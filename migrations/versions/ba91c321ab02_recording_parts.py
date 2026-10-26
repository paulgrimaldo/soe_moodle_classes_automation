"""Ordered recording parts within one academic session."""
from alembic import op
import sqlalchemy as sa

revision = "ba91c321ab02"
down_revision = "fa6dafc81276"
branch_labels = None
depends_on = None


def upgrade():
    # Give SQLite's old unnamed unique(session_id) a deterministic name.
    with op.batch_alter_table("recordings", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}) as batch:
        batch.drop_constraint("uq_recordings_session_id", type_="unique")
        batch.add_column(sa.Column("position", sa.Integer(), nullable=False, server_default="1"))
        batch.create_unique_constraint("uq_recording_part", ["session_id", "position"])
        batch.create_index("ix_recordings_session_id", ["session_id"])


def downgrade():
    if op.get_bind().execute(sa.text(
            "SELECT 1 FROM recordings GROUP BY session_id HAVING COUNT(*) > 1 LIMIT 1")).first():
        raise RuntimeError("Multipart recordings exist; downgrade would lose recording parts")
    with op.batch_alter_table("recordings") as batch:
        batch.drop_index("ix_recordings_session_id")
        batch.drop_constraint("uq_recording_part", type_="unique")
        batch.drop_column("position")
        batch.create_unique_constraint("uq_recordings_session_id", ["session_id"])
