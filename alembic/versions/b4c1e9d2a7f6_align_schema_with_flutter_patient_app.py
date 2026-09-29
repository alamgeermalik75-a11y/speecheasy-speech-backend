"""align schema with flutter patient app

- patients: drop condition / notes / practice_code (spec section 27)
- patient_requests: drop condition / notes (spec section 27),
  add phone / age / updated_at (spec section 13)

Columns are dropped only when they exist so the migration is idempotent for
both the legacy Supabase deployment and fresh local SQLite databases.

Revision ID: b4c1e9d2a7f6
Revises: 826344a83ded
Create Date: 2026-09-29 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4c1e9d2a7f6'
down_revision: Union[str, None] = '826344a83ded'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Columns removed because the patient Flutter app never uses them.
PATIENTS_DROP = ["condition", "notes", "practice_code"]
PATIENT_REQUESTS_DROP = ["condition", "notes"]

# Columns added so a therapist-acceptance flow can store contact info
# derived server-side from the authenticated patient's profile.
PATIENT_REQUESTS_ADD = [
    sa.Column("phone", sa.String(), nullable=True),
    sa.Column("age", sa.Integer(), nullable=True),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    ),
]


def _existing_columns(table: str) -> set:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return {c["name"] for c in inspector.get_columns(table)}


def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return table in inspector.get_table_names()


def upgrade() -> None:
    if _table_exists("patients"):
        existing = _existing_columns("patients")
        for col in PATIENTS_DROP:
            if col in existing:
                op.drop_column("patients", col)

    if _table_exists("patient_requests"):
        existing = _existing_columns("patient_requests")
        for col in PATIENT_REQUESTS_DROP:
            if col in existing:
                op.drop_column("patient_requests", col)
        for col in PATIENT_REQUESTS_ADD:
            if col.name not in existing:
                op.add_column("patient_requests", col)


def downgrade() -> None:
    if _table_exists("patient_requests"):
        existing = _existing_columns("patient_requests")
        for col in reversed(PATIENT_REQUESTS_ADD):
            if col.name in existing:
                op.drop_column("patient_requests", col.name)
        for col in PATIENT_REQUESTS_DROP:
            if col not in existing:
                op.add_column("patient_requests", sa.Column(col, sa.String(), nullable=True))

    if _table_exists("patients"):
        existing = _existing_columns("patients")
        for col in reversed(PATIENTS_DROP):
            if col not in existing:
                op.add_column("patients", sa.Column(col, sa.String(), nullable=True))
