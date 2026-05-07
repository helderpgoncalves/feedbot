"""server-side sessions, audit log, magic-link PKCE binding

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-07

Adds three things, all additive (no destructive changes):

1. ``sessions``                          — replaces the cookie-signed session.
   The cookie now carries only an opaque token; lookup is server-side, so
   sessions are revocable individually or in bulk ("log out from all devices").

2. ``audit_events``                      — structured audit log for sensitive
   actions (login, logout, key revoked, member removed, llm-settings changed).
   Compliance-friendly from day one; required for the cloud later.

3. ``magic_link_tokens.nonce_hash``      — PKCE-style binding. The browser that
   submits POST /login generates a nonce and stores its hash here; when the
   magic link is opened, the same browser must present the matching cookie or
   the link is logged as ``cross_device_login`` and (in lax mode) still allowed
   but the user is emailed a notification.

The cookie format change is a hard cutover: existing signed-cookie sessions
become invalid the moment 0006 is deployed. Documented in CHANGELOG under
"Changed (BREAKING)".
"""

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Server-side sessions ────────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
    )
    op.create_index(
        "ix_sessions_user_active",
        "sessions",
        ["user_id", "revoked_at", "expires_at"],
    )

    # ── Audit log ───────────────────────────────────────────────────────────
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        # Free-form event name, e.g. "login.ok", "login.cross_device",
        # "session.revoked", "api_key.created", "llm_settings.updated".
        sa.Column("event", sa.String(64), nullable=False, index=True),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),  # JSON-serialized blob
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )
    op.create_index(
        "ix_audit_events_tenant_created",
        "audit_events",
        ["tenant_id", "created_at"],
    )

    # ── Magic-link PKCE binding ─────────────────────────────────────────────
    # nonce_hash is set if the login request carried an mlnonce cookie.
    # nullable so existing rows survive (they will simply expire normally).
    op.add_column(
        "magic_link_tokens",
        sa.Column("nonce_hash", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("magic_link_tokens", "nonce_hash")
    op.drop_index("ix_audit_events_tenant_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_sessions_user_active", table_name="sessions")
    op.drop_table("sessions")
