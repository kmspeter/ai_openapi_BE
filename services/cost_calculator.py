from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_CONFIG_PATH = BASE_DIR / "data" / "models_config.json"


class Pricing(BaseModel):
    input: float = Field(..., ge=0)
    output: float = Field(..., ge=0)
    currency: str = "USD"


class ModelConfig(BaseModel):
    id: str
    provider: str
    max_output_tokens: int = Field(..., gt=0)
    pricing: Pricing


@lru_cache()
def _load_models() -> Dict[str, ModelConfig]:
    if not MODELS_CONFIG_PATH.exists():
        raise FileNotFoundError(f"Model configuration file not found: {MODELS_CONFIG_PATH}")
    with MODELS_CONFIG_PATH.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    models: Dict[str, ModelConfig] = {}
    for model_id, payload in raw.items():
        payload.setdefault("id", model_id)
        models[model_id] = ModelConfig(**payload)
    return models


def get_model_config(model_id: str) -> ModelConfig:
    models = _load_models()
    if model_id not in models:
        raise KeyError(f"Unsupported model: {model_id}")
    return models[model_id]


def calculate_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> Tuple[float, float, float, str]:
    config = get_model_config(model_id)
    pricing = config.pricing
    input_cost = round((prompt_tokens / 1000) * pricing.input, 6)
    output_cost = round((completion_tokens / 1000) * pricing.output, 6)
    total_cost = round(input_cost + output_cost, 6)
    return input_cost, output_cost, total_cost, pricing.currency


def validate_token_limits(model_id: str, requested_max_tokens: int | None) -> None:
    if requested_max_tokens is None:
        return
    config = get_model_config(model_id)
    if requested_max_tokens > config.max_output_tokens:
        raise ValueError(
            f"Requested max_tokens {requested_max_tokens} exceeds limit for {model_id}: {config.max_output_tokens}"
        )


def list_supported_models() -> Dict[str, ModelConfig]:
    return _load_models().copy()
