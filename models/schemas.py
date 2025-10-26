from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional, Union, Dict, Any

from pydantic import BaseModel, Field, model_validator


# --- Chat Models --------------------------------------------------------------

class ChatMessage(BaseModel):
    """
    메시지 포맷:
      - OpenAI: {"role": "user", "content": "Hello"}
      - Anthropic: {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
      - Gemini: {"role": "user", "parts": [{"text": "Hello"}]} (게이트웨이에서 parts→content 변환)
    """
    role: Literal["system", "user", "assistant"]
    content: Union[str, List[Dict[str, Any]]] = Field(
        ...,
        description="Message content. Supports str or structured list formats."
    )

    @model_validator(mode="before")
    def normalize_content(cls, values: Any):
        # Gemini의 'parts' 필드 → 'content'로 변환
        if isinstance(values, dict) and "parts" in values and "content" not in values:
            parts = values.get("parts", [])
            if isinstance(parts, list) and parts and isinstance(parts[0], dict) and "text" in parts[0]:
                values["content"] = [{"type": "text", "text": parts[0]["text"]}]
            elif isinstance(parts, list) and parts and isinstance(parts[0], str):
                values["content"] = [{"type": "text", "text": parts[0]}]
            else:
                values["content"] = [{"type": "text", "text": str(parts)}]
        return values


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


# --- Response Schemas --------------------------------------------------------

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
    usage_date: date
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


class UserUsageHistoryResponse(BaseModel):
    user_id: Optional[str]
    totals: UsageBreakdown
    total_cost: float
    daily: List[DailyUsageResponse]
    monthly: List[MonthlyUsageResponse]
    sessions: List[SessionUsageRecord]


class UsageQueryParams(BaseModel):
    provider: Optional[str] = None
    model_id: Optional[str] = None
    user_id: Optional[str] = None


class HealthStatus(BaseModel):
    database: bool
    providers: dict[str, bool]
