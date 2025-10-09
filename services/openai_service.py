from __future__ import annotations

from typing import Any, Dict

from openai import AsyncOpenAI, OpenAIError

from config import settings
from models.schemas import ChatCompletionRequest
from services.token_counter import count_completion_tokens


class OpenAIServiceError(RuntimeError):
    """Raised for OpenAI service-level errors."""
    pass


# Chat Completions 엔드포인트로 보장 동작하는 모델만 허용 (필요 시 확장)
CHAT_COMPLETIONS_COMPAT = {
    "gpt-3.5-turbo",
    # "gpt-4-turbo-preview",  # 게이트웨이/키 권한에 따라 활성화 가능
}


async def chat_completion(request: ChatCompletionRequest) -> Dict[str, Any]:
    if request.stream:
        raise OpenAIServiceError("Streaming responses are not supported in this implementation.")

    if not settings.openai_api_key:
        raise OpenAIServiceError("OpenAI API key is not configured.")

    # 엔드포인트 호환성 확인
    if request.model not in CHAT_COMPLETIONS_COMPAT:
        # 명시적으로 안내: 이 모델은 chat.completions가 아니라 responses API가 필요하거나 미지원
        raise OpenAIServiceError(f"Unsupported model for chat.completions: {request.model}")

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    try:
        response = await client.chat.completions.create(
            model=request.model,
            messages=[message.model_dump() for message in request.messages],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except OpenAIError as exc:  # pragma: no cover - SDK specific errors
        # 원문 보존해서 상위에서 상태코드 매핑할 수 있게 함
        raise OpenAIServiceError(f"openai_error: {str(exc)}") from exc

    choice = response.choices[0]
    content = choice.message.content or ""
    prompt_tokens = response.usage.prompt_tokens if response.usage else 0
    completion_tokens = response.usage.completion_tokens if response.usage else count_completion_tokens(
        request.model, content
    )

    return {
        "id": response.id,
        "content": content,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
