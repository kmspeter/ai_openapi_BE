from __future__ import annotations

from typing import Any, Dict, List

from anthropic import AsyncAnthropic, AnthropicError

from config import settings
from models.schemas import ChatCompletionRequest
from services.token_counter import count_completion_tokens, count_prompt_tokens


class AnthropicServiceError(RuntimeError):
    pass


def _prepare_messages(messages: List[dict[str, str]]) -> tuple[str | None, List[dict[str, str]]]:
    system_prompt = None
    normalized: List[dict[str, str]] = []
    for message in messages:
        role = message["role"]
        content = message["content"]
        if role == "system":
            system_prompt = content if system_prompt is None else f"{system_prompt}\n\n{content}"
            continue
        normalized.append({"role": role, "content": content})
    return system_prompt, normalized


async def chat_completion(request: ChatCompletionRequest) -> Dict[str, Any]:
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
    except AnthropicError as exc:  # pragma: no cover - SDK specific
        raise AnthropicServiceError(str(exc)) from exc

    text_parts = [block.text for block in response.content if hasattr(block, "text")]
    content = "".join(text_parts)

    prompt_tokens = response.usage.input_tokens if response.usage else count_prompt_tokens(
        request.model, normalized_messages
    )
    completion_tokens = response.usage.output_tokens if response.usage else count_completion_tokens(
        request.model, content
    )

    return {
        "id": response.id,
        "content": content,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
