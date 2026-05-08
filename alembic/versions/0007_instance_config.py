"""instance_config singleton — runtime knobs settable from the dashboard

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-08

Self-host configuration that an admin can change from the UI without
SSH'ing into the box: SMTP, Telegram bot credentials, public domain,
HTTPS toggle, autostart toggle, telemetry opt-in. Stored in a single-
row table guarded by a CHECK (id = 1) constraint — there's exactly one
"instance" per deployment, and we want UPSERT semantics.

Encrypted columns (smtp_password, telegram_bot_token):
    Stored as ``BYTEA`` Fernet ciphertext. Encryption uses the same
    FEEDBOT_SECRET_KEY-derived key as M3's LLM provider keys (see
    ``feedbot_core/llm/crypto.py``). Rotating FEEDBOT_SECRET_KEY
    invalidates these along with the LLM keys — owners must re-enter
    them.

Multi-tenant note:
    This is a *deployment-wide* config, not a tenant-scoped one. Cloud
    deployments simply leave the row at all-defaults and never expose
    the related UI (``cfg.deployment === 'cloud'`` hides Settings →
    Domain & HTTPS, etc.). The SMTP fields *are* read by the API in
    cloud mode, but configured by the cloud operator via env vars,
    not via the table.

This migration is additive and self-host-safe: cloud, fresh deploys,
and existing self-host installs all see an empty default row after
upgrade.
"""

from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instance_config",
        # Singleton — only id=1 is permitted by the CHECK constraint
        # below. We use an INTEGER (not BOOLEAN) so future "well-known
        # row IDs" can be added without a migration if it ever becomes
        # useful (e.g. id=2 for a future cloud-tenant-default).
        sa.Column("id", sa.Integer(), primary_key=True),
        # ── SMTP ─────────────────────────────────────────────────────
        sa.Column("smtp_host", sa.String(255), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=True),
        sa.Column("smtp_user", sa.String(255), nullable=True),
        # Fernet ciphertext (urlsafe base64-encoded already by Fernet,
        # but stored as bytes since the API never re-renders it).
        sa.Column("smtp_password_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("smtp_from", sa.String(255), nullable=True),
        # ── Telegram bot ─────────────────────────────────────────────
        sa.Column("telegram_bot_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("telegram_bot_username", sa.String(64), nullable=True),
        # ── Domain + HTTPS (server-mode only; cloud sets via env) ────
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("https_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("letsencrypt_email", sa.String(255), nullable=True),
        # ── System ───────────────────────────────────────────────────
        sa.Column("autostart_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("telemetry_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        # ── Audit ────────────────────────────────────────────────────
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint("id = 1", name="ck_instance_config_singleton"),
    )

    # Insert the singleton row immediately so application code can
    # always assume it exists. No defaults beyond what the columns
    # already specify; updated_at uses NOW() server-side.
    op.execute("INSERT INTO instance_config (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("instance_config")
