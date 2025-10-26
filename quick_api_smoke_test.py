"""Simple smoke test suite for the AI Gateway REST API.

Runs minimal tests (health + chat + user) to verify that a running gateway instance is healthy.
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
        "gpt-3.5-turbo",              # OpenAI
        "claude-3-7-sonnet-20250219", # Anthropic
        "gemini-2.5-flash",           # Google
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
        print(f"✅ Chat tests passed for: {', '.join(successful_models)}")
    else:
        print("⚠️  All chat providers failed or quota reached.")


def test_usage_for_user(
    tester: ApiSmokeTester,
    user_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    provider: Optional[str] = None,
    model_id: Optional[str] = None,
) -> None:
    """유저별 일일 사용량 조회 테스트"""
    print(f"\n>>> Fetching usage for user={user_id} ...")

    params: Dict[str, Any] = {}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if provider:
        params["provider"] = provider
    if model_id:
        params["model_id"] = model_id

    try:
        payload = tester.call("GET", f"/api/usage/user/{user_id}", params=params)
    except requests.HTTPError as exc:
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            print(f"❌ Failed to fetch user usage: status={resp.status_code}, detail={detail}")
        else:
            print(f"❌ Failed to fetch user usage: {exc}")
        return

    if not isinstance(payload, list):
        raise AssertionError("user usage 응답은 리스트 형식이어야 합니다.")

    # 스키마 검증
    required_keys = {
        "date",
        "provider",
        "model_id",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "total_cost",
        "request_count",
    }
    for i, record in enumerate(payload):
        if not isinstance(record, dict) or required_keys - set(record):
            raise AssertionError(f"레코드 #{i}의 스키마 불일치: {record}")

    tester.pretty("User Daily Usage", payload)
    print(f"✅ User daily usage lookup succeeded for user={user_id}")


def test_full_usage_for_user(tester: ApiSmokeTester, user_id: str) -> None:
    """특정 사용자의 전체 사용 이력을 조회"""
    print(f"\n>>> Fetching full usage history for user={user_id} ...")

    try:
        payload = tester.call("GET", f"/api/usage/user/{user_id}/all")
    except requests.HTTPError as exc:
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            print(f"❌ Failed to fetch full user usage: status={resp.status_code}, detail={detail}")
        else:
            print(f"❌ Failed to fetch full user usage: {exc}")
        return

    if not isinstance(payload, dict):
        raise AssertionError("전체 사용 이력 응답은 딕셔너리 형식이어야 합니다.")

    required_keys = {"user_id", "totals", "total_cost", "daily", "monthly", "sessions"}
    if required_keys - set(payload):
        raise AssertionError(f"응답에 필요한 키가 없습니다: {required_keys - set(payload)}")

    totals = payload.get("totals")
    if not isinstance(totals, dict) or {"prompt_tokens", "completion_tokens", "total_tokens"} - set(totals):
        raise AssertionError("totals 스키마 불일치")

    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if not isinstance(totals.get(key), int):
            raise AssertionError(f"totals.{key} 값은 정수여야 합니다: {totals.get(key)}")

    if not isinstance(payload.get("total_cost"), (int, float)):
        raise AssertionError("total_cost 값은 숫자여야 합니다.")

    def _assert_daily(records: Any) -> None:
        if not isinstance(records, list):
            raise AssertionError("daily 필드는 리스트여야 합니다.")
        required_daily_keys = {
            "date",
            "provider",
            "model_id",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "total_cost",
            "request_count",
        }
        for i, record in enumerate(records):
            if not isinstance(record, dict) or required_daily_keys - set(record):
                raise AssertionError(f"daily 레코드 #{i} 스키마 불일치: {record}")

    def _assert_monthly(records: Any) -> None:
        if not isinstance(records, list):
            raise AssertionError("monthly 필드는 리스트여야 합니다.")
        required_monthly_keys = {
            "year_month",
            "provider",
            "model_id",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "total_cost",
            "request_count",
        }
        for i, record in enumerate(records):
            if not isinstance(record, dict) or required_monthly_keys - set(record):
                raise AssertionError(f"monthly 레코드 #{i} 스키마 불일치: {record}")

    def _assert_sessions(records: Any) -> None:
        if not isinstance(records, list):
            raise AssertionError("sessions 필드는 리스트여야 합니다.")
        required_session_keys = {
            "session_id",
            "user_id",
            "usage_date",
            "provider",
            "model_id",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "input_cost",
            "output_cost",
            "total_cost",
            "currency",
            "created_at",
        }
        for i, record in enumerate(records):
            if not isinstance(record, dict) or required_session_keys - set(record):
                raise AssertionError(f"session 레코드 #{i} 스키마 불일치: {record}")

    _assert_daily(payload.get("daily"))
    _assert_monthly(payload.get("monthly"))
    _assert_sessions(payload.get("sessions"))

    tester.pretty("Full User Usage", payload)
    print(f"✅ Full usage history lookup succeeded for user={user_id}")


# -------------------------------
# 실행 진입점
# -------------------------------

TEST_REGISTRY: Dict[str, Callable[[ApiSmokeTester, argparse.Namespace], None]] = {
    "health": lambda tester, args: test_health(tester),
    "chat": lambda tester, args: test_chat_all_providers(tester, session_id=args.session_id),
    "user": lambda tester, args: test_usage_for_user(
        tester,
        user_id=args.user_id,
        start_date=args.start_date,
        end_date=args.end_date,
        provider=args.provider,
        model_id=args.model_id,
    ),
    "user_all": lambda tester, args: test_full_usage_for_user(tester, user_id=args.user_id),
}


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run minimal smoke tests (health + chat + user)")
    parser.add_argument("--base-url", default=None, help=f"Gateway base URL (default: ${BASE_URL_ENV})")
    parser.add_argument("--api-key", default=None, help=f"Gateway API key (default: ${API_KEY_ENV})")
    parser.add_argument("--timeout", type=int, default=None, help=f"HTTP timeout (default: {DEFAULT_TIMEOUT})")

    # chat용
    parser.add_argument("--session-id", default="test-session-123", help="Session ID for chat tests")

    # user용
    parser.add_argument("--user-id", default="tester", help="User ID for user usage test")
    parser.add_argument("--start-date", default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--provider", default=None, help="Filter by provider (openai/anthropic/google)")
    parser.add_argument("--model-id", default=None, help="Filter by model ID")

    parser.add_argument(
        "tests",
        nargs="*",
        choices=["health", "chat", "user", "user_all"],
        help="Specific tests to run (default: all: health, chat, user, user_all)",
    )
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

    tests_to_run = args.tests if args.tests else ["health", "chat", "user", "user_all"]

    for test_name in tests_to_run:
        print(f"\n>>> Running {test_name}...")
        try:
            TEST_REGISTRY[test_name](tester, args)
        except Exception as exc:
            print(f"⚠️  Test '{test_name}' encountered an error: {exc}")
            print("Continuing...")

    print("\n✅ Smoke tests completed.")


if __name__ == "__main__":
    main()
