from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(..., min_length=1)


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage] = Field(..., min_length=1)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    stream: bool = False
    session_id: Optional[str] = None
    user_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_user_message(self) -> "ChatCompletionRequest":
        if not any(message.role == "user" for message in self.messages):
            raise ValueError("At least one user message is required")
        return self


class UsageBreakdown(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class CostBreakdown(BaseModel):
    input_cost: float
    output_cost: float
    total_cost: float
    currency: str = "USD"


class ChatCompletionResponse(BaseModel):
    id: str
    model: str
    provider: str
    content: str
    usage: UsageBreakdown
    cost: CostBreakdown
    created_at: datetime


class SessionUsageRecord(BaseModel):
    session_id: str
    user_id: Optional[str]
    provider: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    input_cost: float
    output_cost: float
    total_cost: float
    currency: str
    created_at: datetime


class SessionUsageResponse(BaseModel):
    session_id: str
    records: List[SessionUsageRecord]
    totals: UsageBreakdown
    total_cost: float


class AggregatedUsage(BaseModel):
    provider: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_cost: float
    request_count: int


class DailyUsageResponse(AggregatedUsage):
    date: date


class MonthlyUsageResponse(AggregatedUsage):
    year_month: str


class UsageQueryParams(BaseModel):
    provider: Optional[str] = None
    model_id: Optional[str] = None
    user_id: Optional[str] = None


class HealthStatus(BaseModel):
    database: bool
    providers: dict[str, bool]
