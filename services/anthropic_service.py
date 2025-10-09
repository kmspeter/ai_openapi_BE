from __future__ import annotations

from typing import Any, Dict, List

from anthropic import AsyncAnthropic, AnthropicError

from config import settings
from models.schemas import ChatCompletionRequest
from services.token_counter import count_completion_tokens, count_prompt_tokens


class AnthropicServiceError(RuntimeError):
    """Custom error wrapper for Anthropic API failures."""
    pass


def _prepare_messages(messages: List[dict[str, Any]]) -> tuple[str | None, List[dict[str, Any]]]:
    """
    Anthropic API는 messages 내 각 item이 다음과 같은 형태를 요구한다:
      {"role": "user", "content": [{"type": "text", "text": "..."}]}
    따라서 content가 str이면 자동으로 위 형태로 변환한다.
    또한, 'system' 역할은 system_prompt로 병합하여 반환한다.
    """
    system_prompt = None
    normalized: List[dict[str, Any]] = []

    for message in messages:
        role = message.get("role")
        content = message.get("content")

        # system 메시지 누적
        if role == "system":
            system_prompt = (
                content if system_prompt is None else f"{system_prompt}\n\n{content}"
            )
            continue

        # Anthropic 형식으로 content 정규화
        if isinstance(content, str):
            normalized_content = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            # 이미 올바른 구조
            normalized_content = content
        else:
            # 잘못된 형식 방어적 처리
            normalized_content = [{"type": "text", "text": str(content)}]

        normalized.append({"role": role, "content": normalized_content})

    return system_prompt, normalized


async def chat_completion(request: ChatCompletionRequest) -> Dict[str, Any]:
    """Handles Anthropic chat completion calls with automatic message normalization."""
    if request.stream:
        raise AnthropicServiceError("Streaming responses are not supported in this implementation.")

    if not settings.anthropic_api_key:
        raise AnthropicServiceError("Anthropic API key is not configured.")

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    system_prompt, normalized_messages = _prepare_messages([m.model_dump() for m in request.messages])

    try:
        response = await client.messages.create(
            model=request.model,
            messages=normalized_messages,
            system=system_prompt,
            temperature=request.temperature,
            max_tokens=request.max_tokens or 1024,
        )
    except AnthropicError as exc:  # pragma: no cover
        raise AnthropicServiceError(str(exc)) from exc

    # content 합치기 (Claude는 여러 block.text로 나올 수 있음)
    text_parts = [block.text for block in response.content if hasattr(block, "text")]
    content = "".join(text_parts)

    # usage 처리
    prompt_tokens = (
        response.usage.input_tokens
        if getattr(response, "usage", None)
        else count_prompt_tokens(request.model, normalized_messages)
    )
    completion_tokens = (
        response.usage.output_tokens
        if getattr(response, "usage", None)
        else count_completion_tokens(request.model, content)
    )

    return {
        "id": getattr(response, "id", "unknown"),
        "content": content,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
