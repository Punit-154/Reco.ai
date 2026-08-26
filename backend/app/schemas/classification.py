from pydantic import BaseModel, Field


class ClassifyPendingRequest(BaseModel):
    use_ai: bool = False
    limit: int = Field(default=100, ge=1, le=500)
