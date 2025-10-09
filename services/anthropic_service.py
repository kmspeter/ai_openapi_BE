# services/anthropic_service.py
from __future__ import annotations

from typing import Any, Dict, List

from anthropic import AsyncAnthropic, AnthropicError

from config import settings
from models.schemas import ChatCompletionRequest
from services.token_counter import count_completion_tokens, count_prompt_tokens


class AnthropicServiceError(RuntimeError):
    """Custom error wrapper for Anthropic API failures."""
    pass


def _to_text_block_list(content: Any) -> List[dict[str, str]]:
    """
    Anthropic content는 [{"type":"text","text": "..."}] 형태의 리스트여야 함.
    - str이면 text 블록 리스트로 변환
    - 이미 리스트/블록 구조면 가능한 한 보존(방어적으로 정규화)
    - 그 외 타입은 str()로 텍스트 블록화
    """
    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    if isinstance(content, list):
        blocks: List[dict[str, str]] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                blocks.append({"type": "text", "text": item["text"]})
            elif isinstance(item, str):
                blocks.append({"type": "text", "text": item})
            else:
                blocks.append({"type": "text", "text": str(item)})
        return blocks

    # fallback
    return [{"type": "text", "text": str(content)}]


def _prepare_messages(messages: List[dict[str, Any]]) -> tuple[List[dict[str, str]] | None, List[dict[str, Any]]]:
    """
    - system 메시지는 블록 리스트로 누적해서 반환 (없으면 None)
    - user/assistant 메시지는 content를 항상 블록 리스트로 표준화
    """
    system_blocks: List[dict[str, str]] = []
    normalized: List[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            system_blocks.extend(_to_text_block_list(content))
            continue

        # Anthropic는 role이 "user" 또는 "assistant" 여야 함
        if role not in {"user", "assistant"}:
            # 안전하게 매핑(기타 role은 user로 보냄)
            role = "user"

        normalized.append({
            "role": role,
            "content": _to_text_block_list(content),
        })

    return (system_blocks if system_blocks else None), normalized


async def chat_completion(request: ChatCompletionRequest) -> Dict[str, Any]:
    """Handles Anthropic chat completion calls with automatic message normalization."""
    if request.stream:
        raise AnthropicServiceError("Streaming responses are not supported in this implementation.")

    if not settings.anthropic_api_key:
        raise AnthropicServiceError("Anthropic API key is not configured.")

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    # pydantic 모델 -> dict
    raw_messages = [m.model_dump() for m in request.messages]
    system_blocks, normalized_messages = _prepare_messages(raw_messages)

    try:
        # system은 리스트가 있을 때만 전달 (없으면 아예 빼기)
        create_kwargs: Dict[str, Any] = {
            "model": request.model,
            "messages": normalized_messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or 1024,
        }
        if system_blocks:
            create_kwargs["system"] = system_blocks  # ✅ 리스트 형태로만 전달

        response = await client.messages.create(**create_kwargs)

    except AnthropicError as exc:  # pragma: no cover
        # 원문 메시지를 그대로 래핑
        raise AnthropicServiceError(str(exc)) from exc

    # content 합치기 (Claude는 여러 block.text로 나올 수 있음)
    text_parts = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            text_parts.append(text)
    content = "".join(text_parts)

    # usage 처리 (없으면 로컬 추정)
    if getattr(response, "usage", None):
        prompt_tokens = int(response.usage.input_tokens or 0)
        completion_tokens = int(response.usage.output_tokens or 0)
    else:
        # 추정 시, prompt는 정규화된 메시지로 / completion은 content로
        prompt_tokens = count_prompt_tokens(request.model, normalized_messages)
        completion_tokens = count_completion_tokens(request.model, content)

    return {
        "id": getattr(response, "id", "anthropic-response"),
        "content": content,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
