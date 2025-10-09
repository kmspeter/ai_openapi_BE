from __future__ import annotations

import math
from typing import Iterable

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None


def _estimate_tokens_from_chars(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def count_prompt_tokens(model: str, messages: Iterable[dict[str, str]]) -> int:
    if tiktoken is None:
        return sum(_estimate_tokens_from_chars(message.get("content", "")) for message in messages)

    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")

    total = 0
    for message in messages:
        total += len(encoding.encode(message.get("content", "")))
    return total


def count_completion_tokens(model: str, content: str) -> int:
    if tiktoken is None:
        return _estimate_tokens_from_chars(content)

    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(content))
