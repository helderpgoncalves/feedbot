"""subscriptions — per-tenant plan + Stripe linkage

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-09

Cloud billing foundation. Self-host runs this migration too — the table
is created empty and stays empty: ``assert_quota`` short-circuits on
``FEEDBOT_BILLING_ENABLED=false`` (the self-host default) and never reads
this table. We chose this over conditional migrations because:

  - Conditional schema = two divergent schemas to maintain across releases.
  - One empty table = zero ongoing cost (no inserts, no reads, no writes).
  - Self-hosters who later flip ``FEEDBOT_BILLING_ENABLED=true`` and wire
    their own Stripe account get a working table without an extra migrate.

Stripe column nullability:
    All ``stripe_*`` columns are nullable. A row may exist with only
    ``tenant_id`` and ``plan='free'`` set — that's the state right after
    a free-beta signup, before C2.4 wires the Stripe customer creation.
"""

from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        # One subscription per tenant — the UNIQUE constraint is what makes
        # ``ensure_subscription`` safe to call concurrently (PG raises and
        # the second writer falls through to the SELECT branch).
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        # ── Plan + status ────────────────────────────────────────────
        # Plan key matches the dict in feedbot_core/billing/plans.py.
        # Stored as a string (not an enum) so adding a tier is a 0-DDL
        # change.
        sa.Column("plan", sa.String(32), nullable=False, server_default="free"),
        # Mirrors Stripe's subscription status enum:
        # trialing | active | past_due | canceled | unpaid | incomplete
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        # ── Stripe linkage (all nullable for free-beta + self-host) ──
        sa.Column("stripe_customer_id", sa.String(64), nullable=True, unique=True),
        sa.Column("stripe_subscription_id", sa.String(64), nullable=True, unique=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        # ── Rolling monthly counters (incremented inline by ingest) ──
        # Stored on the Subscription row so the quota check is one row
        # read, not a COUNT(*) over the feedbacks table on every ingest.
        sa.Column("monthly_feedback_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("monthly_feedback_reset_at", sa.DateTime(timezone=True), nullable=True),
        # ── Audit ────────────────────────────────────────────────────
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("subscriptions")
