"""Create public run lifecycle and ordered event tables."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "triage_runs",
        sa.Column("run_id", sa.String(length=36), primary_key=True),
        sa.Column("client_request_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("decision_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("client_request_id"),
    )
    op.create_index("ix_triage_runs_client_request_id", "triage_runs", ["client_request_id"])
    op.create_index("ix_triage_runs_status", "triage_runs", ["status"])
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("event_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["triage_runs.run_id"]),
        sa.UniqueConstraint("run_id", "sequence"),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])


def downgrade() -> None:
    op.drop_table("run_events")
    op.drop_table("triage_runs")
