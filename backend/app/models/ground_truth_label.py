import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, new_uuid


class GroundTruthLabel(Base, TimestampMixin):
    __tablename__ = "ground_truth_labels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    opaque_source_record_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    fixture_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
