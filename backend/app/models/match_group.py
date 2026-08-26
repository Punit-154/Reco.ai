import uuid

from sqlalchemy import BigInteger, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, new_uuid


class MatchGroup(Base, TimestampMixin):
    __tablename__ = "match_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    deterministic_score: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    expected_amount_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_amount_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delta_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rule_trace: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
