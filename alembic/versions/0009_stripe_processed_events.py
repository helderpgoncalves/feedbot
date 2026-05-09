"""stripe_processed_events — webhook idempotency dedupe table

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-09

Stripe retries webhooks aggressively (every event is delivered "at-least
once" — sometimes many times within minutes during retries). Without
dedupe, replays would double-bump our counters or create duplicate
side-effects.

Strategy:
    - We store ``event.id`` (the unique Stripe event UUID) keyed against
      ``processed_at``. Every webhook handler does an INSERT; the unique
      constraint converts double-deliveries into IntegrityError, which
      we treat as "already processed, return 200".
    - 7-day TTL via a simple DELETE in a daily cleanup task; older events
      can't be replayed by Stripe anyway (Stripe's retry window is 3
      days).
    - Self-host gets the table even though it never receives a Stripe
      event — keeping the schema in sync removes the conditional-DDL
      footgun. The table stays empty.
"""

from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stripe_processed_events",
        # Stripe's event IDs are at most 32 chars (``evt_…``); 64 is plenty
        # of headroom for any future format change.
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            index=True,
        ),
        # Useful for debugging an "event N had no effect" report.
        sa.Column("event_type", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("stripe_processed_events")
