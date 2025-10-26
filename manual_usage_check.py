# manual_usage_check.py
import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# ------------------------------------------------------------
# 0) 실행 환경 정리: 프로젝트 루트를 import 경로에 추가
# ------------------------------------------------------------
THIS_DIR = Path(__file__).resolve().parent
# database.py가 현재 디렉터리에 없으면 상위 폴더도 경로에 추가
sys.path.append(str(THIS_DIR))
sys.path.append(str(THIS_DIR.parent))

# ------------------------------------------------------------
# 1) DB URL은 database 모듈 import 전에 설정되어야 함
#    (테스트용 SQLite 파일 사용)
# ------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/test_usage.db")

# ------------------------------------------------------------
# 2) 필요한 모듈 import
# ------------------------------------------------------------
from sqlalchemy import delete, select  # type: ignore
from database import (
    DailyUsage,
    MonthlyUsage,
    SessionUsage,
    async_session_factory,
    init_db,
)  # type: ignore
from services import usage_tracker  # type: ignore


# ------------------------------------------------------------
# 3) 공용 유틸: 테이블 비우기
# ------------------------------------------------------------
async def _clear_usage_tables() -> None:
    async with async_session_factory() as session:
        for model in (SessionUsage, DailyUsage, MonthlyUsage):
            await session.execute(delete(model))
        await session.commit()


# ------------------------------------------------------------
# 4) 테스트 1: 세션 단위 집계 확인
# ------------------------------------------------------------
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

    # 검증
    assert len(rows) == 1, f"행 개수 불일치: {len(rows)}"
    record = rows[0]
    assert record.prompt_tokens == 70, f"prompt_tokens={record.prompt_tokens}"
    assert record.completion_tokens == 15, f"completion_tokens={record.completion_tokens}"
    assert record.total_tokens == 85, f"total_tokens={record.total_tokens}"
    assert round(record.total_cost, 6) == 0.74, f"total_cost={record.total_cost}"
    assert record.currency == "USD", f"currency={record.currency}"

    print("[PASS] test_track_usage_aggregates_session_records")


# ------------------------------------------------------------
# 5) 테스트 2: 사용자 일별 집계 값 확인
# ------------------------------------------------------------
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

    # 검증
    assert len(entries) == 2, f"일별 엔트리 개수 불일치: {len(entries)}"

    latest, earliest = entries  # 최신 날짜가 먼저여야 함
    assert latest.date.isoformat() == "2024-05-02", f"latest.date={latest.date}"
    assert latest.model_id == "claude-3", f"latest.model_id={latest.model_id}"
    assert latest.request_count == 1, f"latest.request_count={latest.request_count}"
    assert latest.total_tokens == 50, f"latest.total_tokens={latest.total_tokens}"
    assert round(latest.total_cost, 6) == 0.5, f"latest.total_cost={latest.total_cost}"

    assert earliest.date.isoformat() == "2024-05-01", f"earliest.date={earliest.date}"
    assert earliest.model_id == "gpt-4o", f"earliest.model_id={earliest.model_id}"
    assert earliest.request_count == 2, f"earliest.request_count={earliest.request_count}"
    assert earliest.total_tokens == 100, f"earliest.total_tokens={earliest.total_tokens}"
    assert round(earliest.total_cost, 6) == 1.0, f"earliest.total_cost={earliest.total_cost}"

    print("[PASS] test_get_user_daily_usage_returns_aggregated_values")


# ------------------------------------------------------------
# 6) 엔트리 포인트
# ------------------------------------------------------------
def main() -> None:
    try:
        # DB 초기화 및 정리
        asyncio.run(init_db())
        asyncio.run(_clear_usage_tables())

        # 테스트 실행
        test_track_usage_aggregates_session_records()
        asyncio.run(_clear_usage_tables())

        test_get_user_daily_usage_returns_aggregated_values()

        print("\n✅ 모든 체크를 통과했습니다.")
    except AssertionError as e:
        print("\n❌ 검증 실패:", e)
        sys.exit(1)
    except ModuleNotFoundError as e:
        print("\n❌ 모듈을 찾을 수 없습니다:", e)
        print("   - 스크립트를 프로젝트 루트에서 실행했는지 확인하거나,")
        print("   - database / services 패키지 경로를 sys.path에 추가하세요.")
        sys.exit(1)
    except Exception as e:
        print("\n❌ 예기치 않은 오류:", repr(e))
        sys.exit(1)
    finally:
        # 테스트용 데이터 정리
        try:
            asyncio.run(_clear_usage_tables())
        except Exception:
            pass


if __name__ == "__main__":
    main()
