"""feedback delivery tracking — outbound replies and done notifications

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-07

"""
from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedbacks", sa.Column("author_chat_id", sa.String(128), nullable=True))
    op.add_column("feedbacks", sa.Column("user_reply_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("feedbacks", sa.Column("reply_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("feedbacks", sa.Column("reply_sent_message", sa.Text, nullable=True))
    op.add_column("feedbacks", sa.Column("notified_done_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("feedbacks", sa.Column("last_outbound_message_id", sa.String(64), nullable=True))
    op.create_index(
        "ix_feedbacks_outbound_pending", "feedbacks", ["reply_to_user", "reply_sent_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_feedbacks_outbound_pending", table_name="feedbacks")
    op.drop_column("feedbacks", "last_outbound_message_id")
    op.drop_column("feedbacks", "notified_done_at")
    op.drop_column("feedbacks", "reply_sent_message")
    op.drop_column("feedbacks", "reply_sent_at")
    op.drop_column("feedbacks", "user_reply_at")
    op.drop_column("feedbacks", "author_chat_id")
