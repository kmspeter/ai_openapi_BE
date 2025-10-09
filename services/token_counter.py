from __future__ import annotations

import math
from typing import Any, Iterable

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None


def _estimate_tokens_from_chars(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def _message_text(message: dict[str, Any]) -> str:
    """Extract a text representation from various message content formats."""

    content = message.get("content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text_value = item.get("text")
                if text_value is not None:
                    parts.append(str(text_value))
                elif "content" in item:
                    parts.append(str(item["content"]))
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "\n".join(parts)

    return str(content)


def count_prompt_tokens(model: str, messages: Iterable[dict[str, Any]]) -> int:
    message_texts = [_message_text(message) for message in messages]

    if tiktoken is None:
        return sum(_estimate_tokens_from_chars(text) for text in message_texts)

    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")

    total = 0
    for text in message_texts:
        total += len(encoding.encode(text))
    return total


def count_completion_tokens(model: str, content: str) -> int:
    if tiktoken is None:
        return _estimate_tokens_from_chars(content)

    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(content))
