import uuid
from pydantic import BaseModel


class RowError(BaseModel):
    row_number: int
    error: str


class IngestionSummary(BaseModel):
    ingestion_run_id: uuid.UUID
    source_id: uuid.UUID
    source_kind: str
    inserted: int
    skipped_duplicates: int
    failed_rows: int
    errors: list[RowError]
