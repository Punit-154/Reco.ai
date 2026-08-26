from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt


class RazorpaySettlement(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    entity: Literal["settlement"]
    amount: StrictInt
    status: str
    fees: StrictInt | None = None
    tax: StrictInt | None = None
    utr: str | None = None
    created_at: StrictInt


class RazorpaySettlementListPage(BaseModel):
    model_config = ConfigDict(extra="allow")

    entity: Literal["collection"]
    count: StrictInt
    items: list[RazorpaySettlement]


class RazorpayWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    entity: Literal["event"]
    account_id: str
    event: str
    contains: list[str] = []
    payload: dict
    created_at: StrictInt
