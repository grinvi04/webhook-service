"""add event_id and idempotency unique constraint to webhook_events

Revision ID: 634bbf55b755
Revises: a14bd9ecd5f5
Create Date: 2026-06-28 21:45:18.652306

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "634bbf55b755"
down_revision: str | None = "a14bd9ecd5f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 멱등 backstop: 공급자 이벤트 ID를 저장하고 (customer_id, source, event_id)에
    # 고유제약을 건다. Redis TTL 만료 후 재시도가 중복행을 만드는 것을 차단한다.
    # event_id NULL 행은 NULL distinct 규칙으로 충돌하지 않는다.
    op.add_column("webhook_events", sa.Column("event_id", sa.String(), nullable=True))
    op.create_index(
        op.f("ix_webhook_events_event_id"),
        "webhook_events",
        ["event_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_webhook_events_customer_source_event",
        "webhook_events",
        ["customer_id", "source", "event_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_webhook_events_customer_source_event",
        "webhook_events",
        type_="unique",
    )
    op.drop_index(op.f("ix_webhook_events_event_id"), table_name="webhook_events")
    op.drop_column("webhook_events", "event_id")
