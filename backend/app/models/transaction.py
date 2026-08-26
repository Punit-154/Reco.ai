import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, new_uuid


class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_transactions_source_external"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
        nullable=True,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    transaction_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(6), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gross_amount_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fee_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tax_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    refund_amount_paise: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    utr: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reference_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    narration: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    normalization_version: Mapped[str] = mapped_column(String(32), nullable=False)
