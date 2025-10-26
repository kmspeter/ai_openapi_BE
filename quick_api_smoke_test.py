"""Simple smoke test suite for the AI Gateway REST API.

Runs minimal tests (health + chat) to verify that a running gateway instance is healthy.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional

import requests

DEFAULT_TIMEOUT = 20
BASE_URL_ENV = "GATEWAY_BASE_URL"
API_KEY_ENV = "GATEWAY_API_KEY"
TIMEOUT_ENV = "GATEWAY_TIMEOUT"


@dataclass
class GatewayConfig:
    """Configuration values used when communicating with the gateway."""

    base_url: str
    api_key: Optional[str]
    timeout: int

    @classmethod
    def from_environment(cls) -> "GatewayConfig":
        base_url = os.getenv(BASE_URL_ENV, "http://localhost:8000")
        api_key = os.getenv(API_KEY_ENV)
        timeout_raw = os.getenv(TIMEOUT_ENV)
        timeout = int(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT
        return cls(base_url=base_url, api_key=api_key, timeout=timeout)

    def headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers


class ApiSmokeTester:
    """Collection of helpers used to communicate with the gateway API."""

    def __init__(self, config: GatewayConfig):
        self.config = config

    def call(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.config.base_url.rstrip('/')}{path}"
        response = requests.request(
            method,
            url,
            headers=self.config.headers(),
            params=params,
            json=json_body,
            timeout=self.config.timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            print(f"\n[ERROR] {method} {path} -> {response.status_code} {response.text}")
            raise exc
        if response.content:
            return response.json()
        return None

    @staticmethod
    def pretty(title: str, payload: Any) -> None:
        print(f"\n=== {title} ===")
        print(json.dumps(payload, ensure_ascii=False, indent=2))


# -------------------------------
# Provider별 메시지 변환 빌더
# -------------------------------

def build_provider_body(model_id: str, session_id: str) -> Dict[str, Any]:
    """회사(프로바이더)별 요구 포맷에 맞춰 messages를 조정한다."""
    user_text = "Ping! Reply with 'pong'."

    messages = [{"role": "user", "content": user_text}]
    if model_id.startswith("claude-"):
        messages = [{"role": "user", "content": [{"type": "text", "text": user_text}]}]

    body = {
        "model": model_id,
        "messages": messages,
        "temperature": 0.0,
        "stream": False,
        "session_id": session_id,
        "user_id": "tester",
    }
    return body


# -------------------------------
# 개별 테스트 함수
# -------------------------------

def test_health(tester: ApiSmokeTester) -> None:
    payload = tester.call("GET", "/health")
    if not isinstance(payload, dict) or {"database", "providers"} - set(payload):
        raise AssertionError("health 응답 스키마 불일치")
    tester.pretty("Health Check", payload)


def test_chat_all_providers(tester: ApiSmokeTester, session_id: str) -> None:
    models = [
        "gpt-3.5-turbo",            # OpenAI
        "claude-3-7-sonnet-20250219", # Anthropic
        "gemini-2.5-flash",         # Google
    ]
    expected_providers = {
        "gpt-3.5-turbo": "openai",
        "claude-3-7-sonnet-20250219": "anthropic",
        "gemini-2.5-flash": "google",
    }

    successful_models = []
    for mid in models:
        body = build_provider_body(mid, session_id)
        print(f"\n>>> Testing chat with model={mid} ...")
        try:
            payload = tester.call("POST", "/api/chat/completions", json_body=body)
            required_keys = {"id", "model", "provider", "content", "usage", "cost", "created_at"}
            if not isinstance(payload, dict) or required_keys - set(payload):
                raise AssertionError("chat 응답 스키마 불일치")

            provider = payload.get("provider")
            if provider != expected_providers.get(mid):
                raise AssertionError(
                    f"chat 응답 provider 불일치 (model={mid}, expected={expected_providers.get(mid)}, actual={provider})"
                )

            usage = payload.get("usage")
            if not isinstance(usage, dict) or {"prompt_tokens", "completion_tokens", "total_tokens"} - set(usage):
                raise AssertionError("usage 필드가 누락되었습니다.")
            try:
                prompt_tokens = int(usage.get("prompt_tokens"))
                completion_tokens = int(usage.get("completion_tokens"))
                total_tokens = int(usage.get("total_tokens"))
            except (TypeError, ValueError):
                raise AssertionError("usage 토큰 값이 숫자가 아닙니다.")
            if total_tokens != prompt_tokens + completion_tokens:
                raise AssertionError("토큰 합계(total_tokens) 계산 오류")

            tester.pretty(f"Chat Completion ({mid})", payload)
            print("Model reply:", payload.get("content"))
            print(f"✅ Chat test passed with model={mid} ({provider})")
            successful_models.append(mid)
        except requests.HTTPError as exc:
            resp = getattr(exc, "response", None)
            if resp is not None:
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text
                if resp.status_code == 429 or "quota" in str(detail).lower():
                    print(f"⚠️  Quota/Rate limit for {mid}: {detail}")
                    continue
                print(f"❌ Chat failed for {mid}: status={resp.status_code}, detail={detail}")
            else:
                print(f"❌ Chat failed for {mid}: {exc}")
            continue
        except Exception as e:
            print(f"❌ Unexpected error for {mid}: {e}")
            continue

    if successful_models:
        test_usage_for_session(tester, session_id, successful_models, expected_providers)
    else:
        print("⚠️  All chat providers failed or quota reached.")


def test_usage_for_session(
    tester: ApiSmokeTester,
    session_id: str,
    successful_models: Iterable[str],
    expected_providers: Dict[str, str],
) -> None:
    print(f"\n>>> Fetching usage for session={session_id} ...")
    try:
        payload = tester.call("GET", f"/api/usage/session/{session_id}")
    except requests.HTTPError as exc:
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            print(f"❌ Failed to fetch usage: status={resp.status_code}, detail={detail}")
        else:
            print(f"❌ Failed to fetch usage: {exc}")
        return

    required_keys = {"session_id", "records", "totals", "total_cost"}
    if not isinstance(payload, dict) or required_keys - set(payload):
        raise AssertionError("session usage 응답 스키마 불일치")

    records = payload.get("records", [])
    providers_in_records = {record.get("provider") for record in records if isinstance(record, dict)}
    expected_provider_values = {expected_providers[mid] for mid in successful_models}
    if not expected_provider_values.issubset(providers_in_records):
        raise AssertionError("session usage에 모든 프로바이더 기록이 존재하지 않습니다.")

    totals = payload.get("totals", {})
    if not isinstance(totals, dict) or {"prompt_tokens", "completion_tokens", "total_tokens"} - set(totals):
        raise AssertionError("session usage totals 필드가 누락되었습니다.")
    try:
        totals_prompt = int(totals.get("prompt_tokens"))
        totals_completion = int(totals.get("completion_tokens"))
        totals_total = int(totals.get("total_tokens"))
    except (TypeError, ValueError):
        raise AssertionError("session usage totals 토큰 값이 숫자가 아닙니다.")
    if totals_total != totals_prompt + totals_completion:
        raise AssertionError("session usage totals 토큰 합계 불일치")

    tester.pretty("Session Usage", payload)
    print("✅ Session usage lookup succeeded")


# -------------------------------
# 실행 진입점
# -------------------------------

TEST_REGISTRY: Dict[str, Callable[[ApiSmokeTester, argparse.Namespace], None]] = {
    "health": lambda tester, args: test_health(tester),
    "chat": lambda tester, args: test_chat_all_providers(tester, session_id=args.session_id),
}


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run minimal smoke tests (health + chat)")
    parser.add_argument("--base-url", default=None, help=f"Gateway base URL (default: ${BASE_URL_ENV})")
    parser.add_argument("--api-key", default=None, help=f"Gateway API key (default: ${API_KEY_ENV})")
    parser.add_argument("--timeout", type=int, default=None, help=f"HTTP timeout (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--session-id", default="test-session-123", help="Session ID for chat tests")
    parser.add_argument("tests", nargs="*", choices=["health", "chat"], help="Specific tests to run (default: both)")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> GatewayConfig:
    config = GatewayConfig.from_environment()
    if args.base_url:
        config.base_url = args.base_url
    if args.api_key is not None:
        config.api_key = args.api_key
    if args.timeout is not None:
        config.timeout = args.timeout
    return config


def main() -> None:
    args = parse_args()
    config = build_config(args)
    tester = ApiSmokeTester(config)

    print("Running smoke tests against", config.base_url)

    tests_to_run = args.tests if args.tests else ["health", "chat"]

    for test_name in tests_to_run:
        print(f"\n>>> Running {test_name}...")
        try:
            TEST_REGISTRY[test_name](tester, args)
        except Exception as exc:
            print(f"⚠️  Test '{test_name}' encountered an error: {exc}")
            print("Continuing...")

    print("\n✅ Smoke tests completed (health + chat).")


if __name__ == "__main__":
    main()
