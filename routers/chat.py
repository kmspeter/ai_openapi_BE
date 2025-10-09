from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status

from models.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    CostBreakdown,
    UsageBreakdown,
)
from services import (
    anthropic_service,
    cost_calculator,
    gemini_service,
    openai_service,
    usage_tracker,
)
from services.token_counter import count_prompt_tokens

router = APIRouter(prefix="/chat", tags=["chat"])


def _map_service_error(exc: Exception) -> HTTPException:
    """공급자 예외를 FastAPI 예외로 변환."""
    message = str(exc)
    lowered = message.lower()

    if "not configured" in lowered or "api key" in lowered:
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)

    # 모델 미지원 / 엔드포인트 불일치 / 존재하지 않음
    if (
        "unsupported model" in lowered
        or "unsupported" in lowered
        or "does not exist" in lowered
        or "not found" in lowered
    ):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)

    # 요금제 초과 / rate limit / quota 등은 429로 구분
    if (
        "rate" in lowered
        or "rate limit" in lowered
        or "quota" in lowered
        or "insufficient_quota" in lowered
        or "exceeded your current quota" in lowered
    ):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "Quota or rate limit exceeded", "message": message},
        )

    # 기본: 500 에러
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"error": "Provider API failure", "message": message},
    )


@router.post("/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(payload: ChatCompletionRequest) -> ChatCompletionResponse:
    """
    Chat Completion 엔드포인트.
    빌링 한도 초과 시 경고 메시지로 대체 응답을 반환하고 계속 진행한다.
    """
    try:
        model_config = cost_calculator.get_model_config(payload.model)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unsupported model"
        ) from exc

    try:
        cost_calculator.validate_token_limits(payload.model, payload.max_tokens)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    messages_payload = [message.model_dump() for message in payload.messages]
    prompt_tokens = count_prompt_tokens(payload.model, messages_payload)

    provider_response: Dict[str, Any] = {}

    try:
        # 실제 모델 호출
        if model_config.provider == "openai":
            provider_response = await openai_service.chat_completion(payload)
        elif model_config.provider == "anthropic":
            provider_response = await anthropic_service.chat_completion(payload)
        elif model_config.provider in {"google", "gemini"}:
            provider_response = await gemini_service.chat_completion(payload)
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Unsupported provider"
            )

    except Exception as exc:
        message = str(exc).lower()
        # ✅ 빌링 초과(Quota) 시: 경고만 출력하고 더미 응답으로 대체
        if "insufficient_quota" in message or "exceeded your current quota" in message:
            print(f"[WARNING] Billing quota exceeded for {payload.model}: {exc}")
            provider_response = {
                "id": f"mock-{uuid4()}",
                "content": "[Warning] Billing quota exceeded — simulated response.",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": 0,
            }
        else:
            # 그 외 오류는 정상적으로 매핑
            http_exc = _map_service_error(exc)
            raise http_exc from exc

    # === 응답 정리 ===
    prompt_tokens = provider_response.get("prompt_tokens", prompt_tokens) or prompt_tokens
    completion_tokens = provider_response.get("completion_tokens", 0)
    total_tokens = prompt_tokens + completion_tokens

    input_cost, output_cost, total_cost, currency = cost_calculator.calculate_cost(
        payload.model, prompt_tokens, completion_tokens
    )
    total_cost = round(total_cost, 6)

    # 세션 사용량 기록
    session_id = payload.session_id or f"session-{uuid4().hex}"
    await usage_tracker.track_usage(
        session_id=session_id,
        user_id=payload.user_id,
        provider=model_config.provider,
        model_id=payload.model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=total_cost,
        currency=currency,
    )

    # === 최종 응답 ===
    return ChatCompletionResponse(
        id=str(provider_response.get("id") or uuid4()),
        model=payload.model,
        provider=model_config.provider,
        content=str(provider_response.get("content", "")),
        usage=UsageBreakdown(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
        cost=CostBreakdown(
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=total_cost,
            currency=currency,
        ),
        created_at=datetime.now(UTC),
    )
