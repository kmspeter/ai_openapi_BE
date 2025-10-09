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


def _to_gemini_parts(content: Any) -> List[Dict[str, str]]:
    """
    Gemini 1.5 계열은 각 message에 parts 리스트가 필요하고,
    각 part는 일반적으로 {"text": "..."} 형태를 권장한다.
    (간단화를 위해 text-only만 변환. 이미지/바이너리는 필요 시 확장)
    """
    # 문자열이면 바로 {"text": ...}
    if isinstance(content, str):
        return [{"text": content}]

    # 리스트면 항목별로 정규화
    if isinstance(content, list):
        parts: List[Dict[str, str]] = []
        for item in content:
            if isinstance(item, str):
                parts.append({"text": item})
            elif isinstance(item, dict):
                # Anthropic 등에서 오는 {"type":"text","text":"..."}도 수용
                if "text" in item:
                    parts.append({"text": str(item["text"])})
                elif item.get("type") == "text" and "text" in item:
                    parts.append({"text": str(item["text"])})
                else:
                    # 알 수 없는 dict는 문자열화
                    parts.append({"text": str(item)})
            else:
                parts.append({"text": str(item)})
        return parts

    # 기타 타입은 문자열화
    return [{"text": str(content)}]


def _normalize_messages(messages: List[dict[str, Any]]) -> tuple[str | None, List[dict[str, Any]]]:
    """
    입력 messages(OpenAI/일반형)를 Gemini 포맷(contents)으로 정규화한다.
    - system 메시지는 system_instruction으로 병합
    - user/assistant → user/model 역할로 매핑
    - content는 parts=[{"text": "..."}] 형태로 강제
    """
    system_prompt = None
    normalized: List[dict[str, Any]] = []

    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")

        if role == "system":
            system_prompt = content if system_prompt is None else f"{system_prompt}\n\n{content}"
            continue

        # 역할 매핑 (assistant/model → "model", 나머지 → "user")
        if role in {"assistant", "model"}:
            gemini_role = "model"
        else:
            gemini_role = "user"

        parts = _to_gemini_parts(content)
        normalized.append({"role": gemini_role, "parts": parts})

    return system_prompt, normalized


def _call_gemini(request: ChatCompletionRequest, system_prompt: str | None, contents: List[dict[str, Any]]):
    # generation_config 구성
    generation_config: Dict[str, Any] = {}
    if request.temperature is not None:
        generation_config["temperature"] = request.temperature
    if request.max_tokens is not None:
        generation_config["max_output_tokens"] = request.max_tokens

    model = genai.GenerativeModel(
        model_name=request.model,
        system_instruction=system_prompt or None,
    )

    # Gemini SDK는 동기 클라이언트이므로 to_thread로 감싼다
    return model.generate_content(
        contents=contents,
        generation_config=generation_config or None,
    )


async def chat_completion(request: ChatCompletionRequest) -> Dict[str, Any]:
    """
    Google Gemini chat completion.
    - 스트리밍 미지원
    - messages를 Gemini 포맷으로 정규화
    - usage_metadata 없으면 토큰 수 추정
    """
    if request.stream:
        raise GeminiServiceError("Streaming responses are not supported in this implementation.")

    if not settings.google_api_key:
        raise GeminiServiceError("Google API key is not configured.")

    genai.configure(api_key=settings.google_api_key)

    # 입력 메시지 정규화 (system → system_instruction, content → parts)
    system_prompt, contents = _normalize_messages([m.model_dump() for m in request.messages])

    try:
        response = await asyncio.to_thread(_call_gemini, request, system_prompt, contents)
    except GoogleAPIError as exc:  # pragma: no cover - SDK specific
        raise GeminiServiceError(str(exc)) from exc
    except Exception as exc:  # 기타 런타임 예외도 포착
        raise GeminiServiceError(str(exc)) from exc

    # 텍스트 추출
    text = getattr(response, "text", "") or ""

    # 사용량 메타
    usage_meta = getattr(response, "usage_metadata", None)

    # 사용량 추정 대비 원본 메시지 준비 (토큰 카운터용)
    fallback_messages = [message.model_dump() for message in request.messages]

    prompt_tokens = (
        usage_meta.prompt_token_count
        if usage_meta and getattr(usage_meta, "prompt_token_count", None) is not None
        else count_prompt_tokens(request.model, fallback_messages)
    )
    completion_tokens = (
        usage_meta.candidates_token_count
        if usage_meta and getattr(usage_meta, "candidates_token_count", None) is not None
        else count_completion_tokens(request.model, text)
    )

    return {
        "id": getattr(response, "response_id", "gemini-response"),
        "content": text,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
