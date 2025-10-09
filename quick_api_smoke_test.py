"""Simple smoke test suite for the AI Gateway REST API.

This script exercises a small collection of read/write endpoints so you can
quickly verify that a running gateway instance is healthy.  The base URL and
API key can be supplied via environment variables or command line arguments.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date
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
        except requests.HTTPError as exc:  # pragma: no cover - for manual runs
            print(f"\n[ERROR] {method} {path} -> {response.status_code} {response.text}")
            raise exc
        if response.content:
            return response.json()
        return None

    @staticmethod
    def pretty(title: str, payload: Any) -> None:
        print(f"\n=== {title} ===")
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def test_health(tester: ApiSmokeTester) -> None:
    payload = tester.call("GET", "/health")
    if not isinstance(payload, dict) or {"database", "providers"} - set(payload):
        raise AssertionError("health 응답 스키마 불일치")
    tester.pretty("Health Check", payload)


def test_chat(tester: ApiSmokeTester, session_id: str) -> None:
    body = {
        "model": "gpt-4-turbo-preview",
        "messages": [{"role": "user", "content": "Ping! Reply with 'pong'."}],
        "temperature": 0.0,
        "stream": False,
        "session_id": session_id,
        "user_id": "tester",
    }
    payload = tester.call("POST", "/api/chat/completions", json_body=body)
    required_keys = {"id", "model", "provider", "content", "usage", "cost", "created_at"}
    if not isinstance(payload, dict) or required_keys - set(payload):
        raise AssertionError("chat 응답 스키마 불일치")
    tester.pretty("Chat Completion", payload)
    print("\nModel reply:", payload.get("content"))


def test_usage_daily(tester: ApiSmokeTester) -> None:
    payload = tester.call("GET", "/api/usage/daily")
    if not isinstance(payload, list):
        raise AssertionError("daily usage는 배열이어야 함")
    tester.pretty("Daily Usage (all)", payload[:3])


def test_usage_daily_by_date(tester: ApiSmokeTester, usage_date: str) -> None:
    payload = tester.call("GET", f"/api/usage/daily/{usage_date}")
    if not isinstance(payload, list):
        raise AssertionError("daily usage(date)는 배열이어야 함")
    tester.pretty(f"Daily Usage ({usage_date})", payload[:3])


def test_usage_monthly(tester: ApiSmokeTester) -> None:
    payload = tester.call("GET", "/api/usage/monthly")
    if not isinstance(payload, list):
        raise AssertionError("monthly usage는 배열이어야 함")
    tester.pretty("Monthly Usage (all)", payload[:3])


def test_usage_monthly_period(tester: ApiSmokeTester, year_month: str) -> None:
    payload = tester.call("GET", f"/api/usage/monthly/{year_month}")
    if not isinstance(payload, list):
        raise AssertionError("monthly usage(period)는 배열이어야 함")
    tester.pretty(f"Monthly Usage ({year_month})", payload[:3])


def test_session_usage(tester: ApiSmokeTester, session_id: str) -> None:
    payload = tester.call("GET", f"/api/usage/session/{session_id}")
    required_keys = {"session_id", "records", "totals", "total_cost"}
    if not isinstance(payload, dict) or required_keys - set(payload):
        raise AssertionError("session usage 응답 스키마 불일치")
    tester.pretty(f"Session Usage ({session_id})", payload)


TEST_REGISTRY: Dict[str, Callable[[ApiSmokeTester, argparse.Namespace], None]] = {
    "health": lambda tester, args: test_health(tester),
    "chat": lambda tester, args: test_chat(tester, session_id=args.session_id),
    "usage-daily": lambda tester, args: test_usage_daily(tester),
    "usage-daily-by-date": lambda tester, args: test_usage_daily_by_date(tester, args.usage_date),
    "usage-monthly": lambda tester, args: test_usage_monthly(tester),
    "usage-monthly-period": lambda tester, args: test_usage_monthly_period(tester, args.year_month),
    "session-usage": lambda tester, args: test_session_usage(tester, session_id=args.session_id),
}


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    today = date.today()
    parser = argparse.ArgumentParser(description="Run quick smoke tests against the AI gateway API")
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"Gateway base URL (default: ${BASE_URL_ENV} or http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=f"Gateway API key (default: ${API_KEY_ENV})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help=f"HTTP timeout in seconds (default: ${TIMEOUT_ENV} or {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--usage-date",
        default=today.strftime("%Y-%m-%d"),
        help="Usage date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--year-month",
        default=today.strftime("%Y-%m"),
        help="Usage period in YYYY-MM format",
    )
    parser.add_argument(
        "--session-id",
        default="test-session-123",
        help="Session identifier used for chat and session usage tests",
    )
    parser.add_argument(
        "tests",
        nargs="*",
        choices=sorted(TEST_REGISTRY),
        default=list(TEST_REGISTRY),
        help="Specific tests to run (default: run all)",
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

    for test_name in args.tests:
        print(f"\n>>> Running {test_name}...")
        TEST_REGISTRY[test_name](tester, args)

    print("\nAll requested smoke tests completed successfully.")


if __name__ == "__main__":
    main()
