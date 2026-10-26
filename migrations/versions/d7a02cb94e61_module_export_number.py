"""Add a manually assigned module number for web exports."""
from alembic import op
import sqlalchemy as sa

revision = "d7a02cb94e61"
down_revision = "c3ad19e62b04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("academic_modules", sa.Column("export_number", sa.Integer(), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM academic_modules WHERE export_number IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Manual export numbers exist; downgrade would lose them")
    op.drop_column("academic_modules", "export_number")
