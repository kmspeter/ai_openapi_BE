from __future__ import annotations

from typing import Any, Dict

from openai import AsyncOpenAI, OpenAIError

from config import settings
from models.schemas import ChatCompletionRequest
from services.token_counter import count_completion_tokens


class OpenAIServiceError(RuntimeError):
    pass


async def chat_completion(request: ChatCompletionRequest) -> Dict[str, Any]:
    if request.stream:
        raise OpenAIServiceError("Streaming responses are not supported in this implementation.")

    if not settings.openai_api_key:
        raise OpenAIServiceError("OpenAI API key is not configured.")

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    try:
        response = await client.chat.completions.create(
            model=request.model,
            messages=[message.model_dump() for message in request.messages],
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except OpenAIError as exc:  # pragma: no cover - SDK specific errors
        raise OpenAIServiceError(str(exc)) from exc

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
