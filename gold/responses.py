"""Public response shapes used by FastAPI validation and OpenAPI."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class Breakdown(BaseModel):
    gold_value: str
    gst: str
    platform_fee: str


class Price(BaseModel):
    breakdown: Breakdown | None = None  # Older idempotency responses predate itemisation.
    id: str
    amount: str
    inr_per_gram: str
    grams: str


class Quote(Price):
    expires_at: datetime
    action: Literal["confirm_purchase"]


class Pending(BaseModel):
    quote: Quote | None


class Holdings(BaseModel):
    grams: str
    total_paid: str
    purchases: int


class Receipt(Price):
    created_at: datetime
    quote_id: str | None
    sip_id: str | None
    due_on: date | None


class Action(BaseModel):
    method: Literal["POST"]
    path: str
    idempotency_key: str
    body: dict
    quote: Quote | None = None


class Reply(BaseModel):
    intent: str
    message: str
    action: Action | None


class Plan(BaseModel):
    id: str
    amount: str
    frequency: Literal["daily", "weekly", "monthly"]
    anchor_day: int
    next_due: date | None
    state: Literal["active", "paused", "cancelled"]


class Event(BaseModel):
    seq: int
    owner: str
    time: datetime
    event: str
    details: dict
