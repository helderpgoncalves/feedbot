"""roles, project_members, invites

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-06

"""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users.role — default to admin so any pre-existing single-user installs upgrade
    # cleanly (the original user keeps full access). Fresh installs go through /setup
    # which explicitly creates the owner.
    op.add_column(
        "users",
        sa.Column("role", sa.String(16), nullable=False, server_default="admin"),
    )

    op.create_table(
        "project_members",
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "invites",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column("email", sa.String(255), index=True, nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("token", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "invited_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("invites")
    op.drop_table("project_members")
    op.drop_column("users", "role")
