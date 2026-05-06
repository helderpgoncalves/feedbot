"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-06

"""
from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), index=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenants.id", ondelete="CASCADE"), index=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_project_tenant_slug"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), index=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("prefix", sa.String(32), unique=True, index=True, nullable=False),
        sa.Column("secret_hash", sa.String(255), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False, server_default="write"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "chat_links",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), index=True),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("chat_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("platform", "chat_id", name="uq_chat_platform_id"),
    )

    op.create_table(
        "feedbacks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("public_id", sa.String(16), unique=True, index=True, nullable=False),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), index=True),
        sa.Column("type", sa.String(16), nullable=False, server_default="other"),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("tags", sa.String(255), nullable=True),
        sa.Column("author_platform", sa.String(16), nullable=False),
        sa.Column("author_id", sa.String(128), nullable=False),
        sa.Column("author_name", sa.String(255), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("reply_to_user", sa.Text, nullable=True),
        sa.Column("user_reply", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_feedbacks_project_status", "feedbacks", ["project_id", "status"])
    op.create_index("ix_feedbacks_project_created", "feedbacks", ["project_id", "created_at"])

    op.create_table(
        "magic_link_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), index=True, nullable=False),
        sa.Column("token_hash", sa.String(255), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "telegram_updates",
        sa.Column("update_id", sa.BigInteger, primary_key=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("telegram_updates")
    op.drop_table("magic_link_tokens")
    op.drop_index("ix_feedbacks_project_created", table_name="feedbacks")
    op.drop_index("ix_feedbacks_project_status", table_name="feedbacks")
    op.drop_table("feedbacks")
    op.drop_table("chat_links")
    op.drop_table("api_keys")
    op.drop_table("projects")
    op.drop_table("users")
    op.drop_table("tenants")
