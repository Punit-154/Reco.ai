from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DecisionAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    MANUAL_OVERRIDE = "manual_override"


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DecisionAction
    reason: str | None = Field(default=None, min_length=1)
    override_category: str | None = None

    @model_validator(mode="after")
    def _validate_reason(self):
        needs_reason = self.action in (
            DecisionAction.REJECT,
            DecisionAction.MANUAL_OVERRIDE,
        )
        if needs_reason and (self.reason is None or not self.reason.strip()):
            raise ValueError(f"reason is required for {self.action.value}")
        return self
