from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError

from config import settings
from models.schemas import ChatCompletionRequest
from services.token_counter import count_completion_tokens, count_prompt_tokens


class GeminiServiceError(RuntimeError):
    pass


def _normalize_messages(messages: List[dict[str, str]]) -> tuple[str | None, List[dict[str, Any]]]:
    system_prompt = None
    normalized: List[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        content = message["content"]
        if role == "system":
            system_prompt = content if system_prompt is None else f"{system_prompt}\n\n{content}"
            continue
        normalized.append({"role": "user" if role == "user" else "model", "parts": [content]})
    return system_prompt, normalized


def _call_gemini(request: ChatCompletionRequest, system_prompt: str | None, contents: List[dict[str, Any]]):
    generation_config = {}
    if request.temperature is not None:
        generation_config["temperature"] = request.temperature
    if request.max_tokens is not None:
        generation_config["max_output_tokens"] = request.max_tokens

    model = genai.GenerativeModel(model_name=request.model, system_instruction=system_prompt)
    return model.generate_content(contents=contents, generation_config=generation_config or None)


async def chat_completion(request: ChatCompletionRequest) -> Dict[str, Any]:
    if request.stream:
        raise GeminiServiceError("Streaming responses are not supported in this implementation.")

    if not settings.google_api_key:
        raise GeminiServiceError("Google API key is not configured.")

    genai.configure(api_key=settings.google_api_key)
    system_prompt, contents = _normalize_messages([m.model_dump() for m in request.messages])

    try:
        response = await asyncio.to_thread(_call_gemini, request, system_prompt, contents)
    except GoogleAPIError as exc:  # pragma: no cover - SDK specific
        raise GeminiServiceError(str(exc)) from exc

    text = response.text if hasattr(response, "text") else ""
    usage_meta = getattr(response, "usage_metadata", None)

    fallback_messages = [message.model_dump() for message in request.messages]
    prompt_tokens = (
        usage_meta.prompt_token_count
        if usage_meta and usage_meta.prompt_token_count is not None
        else count_prompt_tokens(request.model, fallback_messages)
    )
    completion_tokens = (
        usage_meta.candidates_token_count if usage_meta and usage_meta.candidates_token_count is not None else count_completion_tokens(
            request.model, text
        )
    )

    return {
        "id": getattr(response, "response_id", "gemini-response"),
        "content": text,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
