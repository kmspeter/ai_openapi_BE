import asyncio
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

# 환경 변수는 database 모듈이 로드되기 전에 설정되어야 한다.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/test_usage.db")

from database import DailyUsage, MonthlyUsage, SessionUsage, async_session_factory, init_db
from services import usage_tracker


async def _clear_usage_tables() -> None:
    async with async_session_factory() as session:
        for model in (SessionUsage, DailyUsage, MonthlyUsage):
            await session.execute(delete(model))
        await session.commit()


@pytest.fixture(scope="session", autouse=True)
def setup_database() -> None:
    asyncio.run(init_db())
    asyncio.run(_clear_usage_tables())
    yield
    asyncio.run(_clear_usage_tables())


@pytest.fixture(autouse=True)
def cleanup_tables_between_tests() -> None:
    asyncio.run(_clear_usage_tables())
    yield
    asyncio.run(_clear_usage_tables())


def test_track_usage_aggregates_session_records() -> None:
    usage_time = datetime(2024, 5, 1, 12, 0, tzinfo=UTC)

    asyncio.run(
        usage_tracker.track_usage(
        session_id="session-1",
        user_id="user-1",
        provider="openai",
        model_id="gpt-4",
        prompt_tokens=50,
        completion_tokens=10,
        input_cost=0.4,
        output_cost=0.1,
        total_cost=0.5,
        currency="USD",
        usage_datetime=usage_time,
    )
    )

    asyncio.run(
        usage_tracker.track_usage(
        session_id="session-1",
        user_id="user-1",
        provider="openai",
        model_id="gpt-4",
        prompt_tokens=20,
        completion_tokens=5,
        input_cost=0.16,
        output_cost=0.08,
        total_cost=0.24,
        currency="USD",
        usage_datetime=usage_time,
    )
    )

    async def _fetch_session_rows() -> list[SessionUsage]:
        async with async_session_factory() as session:
            result = await session.execute(select(SessionUsage))
            return list(result.scalars().all())

    rows = asyncio.run(_fetch_session_rows())

    assert len(rows) == 1
    record = rows[0]
    assert record.prompt_tokens == 70
    assert record.completion_tokens == 15
    assert record.total_tokens == 85
    assert round(record.total_cost, 6) == 0.74
    assert record.currency == "USD"


def test_get_user_daily_usage_returns_aggregated_values() -> None:
    first_day = datetime(2024, 5, 1, 9, 30, tzinfo=UTC)
    second_day = datetime(2024, 5, 2, 15, 45, tzinfo=UTC)

    for _ in range(2):
        asyncio.run(
            usage_tracker.track_usage(
            session_id="session-a",
            user_id="user-42",
            provider="openai",
            model_id="gpt-4o",
            prompt_tokens=30,
            completion_tokens=20,
            input_cost=0.3,
            output_cost=0.2,
            total_cost=0.5,
            currency="USD",
            usage_datetime=first_day,
        )
        )

    asyncio.run(
        usage_tracker.track_usage(
        session_id="session-b",
        user_id="user-42",
        provider="anthropic",
        model_id="claude-3",
        prompt_tokens=40,
        completion_tokens=10,
        input_cost=0.32,
        output_cost=0.18,
        total_cost=0.5,
        currency="USD",
        usage_datetime=second_day,
    )
    )

    async def _fetch_user_daily_usage() -> list[DailyUsage]:
        async with async_session_factory() as session:
            return await usage_tracker.get_user_daily_usage(session, user_id="user-42")

    entries = asyncio.run(_fetch_user_daily_usage())

    assert len(entries) == 2

    # 최신 날짜가 먼저 정렬되어야 한다.
    latest, earliest = entries
    assert latest.date.isoformat() == "2024-05-02"
    assert latest.model_id == "claude-3"
    assert latest.request_count == 1
    assert latest.total_tokens == 50
    assert round(latest.total_cost, 6) == 0.5

    assert earliest.date.isoformat() == "2024-05-01"
    assert earliest.model_id == "gpt-4o"
    assert earliest.request_count == 2
    assert earliest.total_tokens == 100
    assert round(earliest.total_cost, 6) == 1.0
