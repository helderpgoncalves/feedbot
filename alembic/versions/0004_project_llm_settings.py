"""project_llm_settings + llm_calls — per-project classification config + cost tracking

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-07

"""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_llm_settings",
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False, server_default="none"),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column("encrypted_api_key", sa.LargeBinary, nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("monthly_budget_usd", sa.Float, nullable=True),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean, nullable=True),
        sa.Column("last_test_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column(
            "feedback_id",
            sa.Integer,
            sa.ForeignKey("feedbacks.id", ondelete="SET NULL"),
            index=True,
            nullable=True,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("usd_cost", sa.Float, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_text", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_llm_calls_project_created", "llm_calls", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_project_created", table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_table("project_llm_settings")
