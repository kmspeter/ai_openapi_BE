from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from database import DailyUsage, MonthlyUsage, SessionUsage, async_session_factory


async def track_usage(
    *,
    session_id: str,
    user_id: Optional[str],
    provider: str,
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    input_cost: float,
    output_cost: float,
    total_cost: float,
    currency: str,
    db_session: Optional[AsyncSession] = None,
    usage_datetime: Optional[datetime] = None,
) -> None:
    close_session = False
    if db_session is None:
        db_session = async_session_factory()
        close_session = True

    total_tokens = prompt_tokens + completion_tokens
    now = usage_datetime or datetime.now(UTC)
    usage_date = now.date()
    year_month = f"{usage_date.year:04d}-{usage_date.month:02d}"

    try:
        await db_session.execute(
            insert(SessionUsage)
            .values(
                session_id=session_id,
                user_id=user_id,
                usage_date=usage_date,
                provider=provider,
                model_id=model_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                input_cost=input_cost,
                output_cost=output_cost,
                total_cost=total_cost,
                currency=currency,
                created_at=now,
            )
            .on_conflict_do_update(
                index_elements=[
                    SessionUsage.session_id,
                    SessionUsage.user_id,
                    SessionUsage.usage_date,
                    SessionUsage.model_id,
                ],
                set_={
                    "provider": provider,
                    "prompt_tokens": SessionUsage.prompt_tokens + prompt_tokens,
                    "completion_tokens": SessionUsage.completion_tokens + completion_tokens,
                    "total_tokens": SessionUsage.total_tokens + total_tokens,
                    "input_cost": SessionUsage.input_cost + input_cost,
                    "output_cost": SessionUsage.output_cost + output_cost,
                    "total_cost": SessionUsage.total_cost + total_cost,
                    "currency": currency,
                },
            )
        )

        await db_session.execute(
            insert(DailyUsage)
            .values(
                date=usage_date,
                user_id=user_id,
                provider=provider,
                model_id=model_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                total_cost=total_cost,
                request_count=1,
            )
            .on_conflict_do_update(
                index_elements=[DailyUsage.date, DailyUsage.user_id, DailyUsage.model_id],
                set_={
                    "provider": provider,
                    "prompt_tokens": DailyUsage.prompt_tokens + prompt_tokens,
                    "completion_tokens": DailyUsage.completion_tokens + completion_tokens,
                    "total_tokens": DailyUsage.total_tokens + total_tokens,
                    "total_cost": DailyUsage.total_cost + total_cost,
                    "request_count": DailyUsage.request_count + 1,
                },
            )
        )

        await db_session.execute(
            insert(MonthlyUsage)
            .values(
                year_month=year_month,
                user_id=user_id,
                provider=provider,
                model_id=model_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                total_cost=total_cost,
                request_count=1,
            )
            .on_conflict_do_update(
                index_elements=[MonthlyUsage.year_month, MonthlyUsage.user_id, MonthlyUsage.model_id],
                set_={
                    "provider": provider,
                    "prompt_tokens": MonthlyUsage.prompt_tokens + prompt_tokens,
                    "completion_tokens": MonthlyUsage.completion_tokens + completion_tokens,
                    "total_tokens": MonthlyUsage.total_tokens + total_tokens,
                    "total_cost": MonthlyUsage.total_cost + total_cost,
                    "request_count": MonthlyUsage.request_count + 1,
                },
            )
        )

        await db_session.commit()
    except Exception:
        await db_session.rollback()
        raise
    finally:
        if close_session:
            await db_session.close()


async def get_session_usage(session_id: str, db_session: AsyncSession) -> list[SessionUsage]:
    result = await db_session.execute(
        select(SessionUsage).where(SessionUsage.session_id == session_id).order_by(SessionUsage.created_at.asc())
    )
    return list(result.scalars().all())


async def get_daily_usage(
    db_session: AsyncSession,
    *,
    usage_date: Optional[date] = None,
    provider: Optional[str] = None,
    model_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> list[DailyUsage]:
    if usage_date is not None:
        return await get_all_users_daily_usage(
            db_session,
            start_date=usage_date,
            end_date=usage_date,
            provider=provider,
            model_id=model_id,
            user_id=user_id,
        )
    return await get_all_users_daily_usage(
        db_session,
        provider=provider,
        model_id=model_id,
        user_id=user_id,
    )


async def get_user_daily_usage(
    db_session: AsyncSession,
    *,
    user_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    provider: Optional[str] = None,
    model_id: Optional[str] = None,
) -> list[DailyUsage]:
    return await get_all_users_daily_usage(
        db_session,
        start_date=start_date,
        end_date=end_date,
        provider=provider,
        model_id=model_id,
        user_id=user_id,
    )


async def get_all_users_daily_usage(
    db_session: AsyncSession,
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    provider: Optional[str] = None,
    model_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> list[DailyUsage]:
    stmt = select(DailyUsage)
    if start_date:
        stmt = stmt.where(DailyUsage.date >= start_date)
    if end_date:
        stmt = stmt.where(DailyUsage.date <= end_date)
    if provider:
        stmt = stmt.where(DailyUsage.provider == provider)
    if model_id:
        stmt = stmt.where(DailyUsage.model_id == model_id)
    if user_id:
        stmt = stmt.where(DailyUsage.user_id == user_id)
    stmt = stmt.order_by(
        DailyUsage.date.desc(),
        DailyUsage.user_id,
        DailyUsage.model_id,
        DailyUsage.provider,
    )
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


async def get_user_session_usage(
    db_session: AsyncSession,
    *,
    user_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    provider: Optional[str] = None,
    model_id: Optional[str] = None,
) -> list[SessionUsage]:
    stmt = select(SessionUsage).where(SessionUsage.user_id == user_id)
    if start_date:
        stmt = stmt.where(SessionUsage.usage_date >= start_date)
    if end_date:
        stmt = stmt.where(SessionUsage.usage_date <= end_date)
    if provider:
        stmt = stmt.where(SessionUsage.provider == provider)
    if model_id:
        stmt = stmt.where(SessionUsage.model_id == model_id)
    stmt = stmt.order_by(
        SessionUsage.usage_date.desc(),
        SessionUsage.session_id,
        SessionUsage.model_id,
        SessionUsage.provider,
    )
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


async def get_monthly_usage(
    db_session: AsyncSession,
    *,
    year_month: Optional[str] = None,
    provider: Optional[str] = None,
    model_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> list[MonthlyUsage]:
    stmt = select(MonthlyUsage)
    if year_month:
        stmt = stmt.where(MonthlyUsage.year_month == year_month)
    if provider:
        stmt = stmt.where(MonthlyUsage.provider == provider)
    if model_id:
        stmt = stmt.where(MonthlyUsage.model_id == model_id)
    if user_id:
        stmt = stmt.where(MonthlyUsage.user_id == user_id)
    stmt = stmt.order_by(MonthlyUsage.year_month.desc(), MonthlyUsage.provider, MonthlyUsage.model_id)
    result = await db_session.execute(stmt)
    return list(result.scalars().all())
