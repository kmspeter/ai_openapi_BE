from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from database import async_session_factory
from models.schemas import (
    DailyUsageResponse,
    MonthlyUsageResponse,
    SessionUsageRecord,
    SessionUsageResponse,
    UsageBreakdown,
    UserUsageHistoryResponse,
)
from services import usage_tracker

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/session/{session_id}", response_model=SessionUsageResponse)
async def get_session_usage(session_id: str) -> SessionUsageResponse:
    async with async_session_factory() as session:
        records = await usage_tracker.get_session_usage(session_id, session)

    if not records:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    pydantic_records: List[SessionUsageRecord] = [
        SessionUsageRecord(
            session_id=record.session_id,
            user_id=record.user_id,
            usage_date=record.usage_date,
            provider=record.provider,
            model_id=record.model_id,
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            total_tokens=record.total_tokens,
            input_cost=record.input_cost,
            output_cost=record.output_cost,
            total_cost=record.total_cost,
            currency=record.currency,
            created_at=record.created_at,
        )
        for record in records
    ]

    totals = UsageBreakdown(
        prompt_tokens=sum(record.prompt_tokens for record in pydantic_records),
        completion_tokens=sum(record.completion_tokens for record in pydantic_records),
        total_tokens=sum(record.total_tokens for record in pydantic_records),
    )

    total_cost = round(sum(record.total_cost for record in pydantic_records), 6)

    return SessionUsageResponse(session_id=session_id, records=pydantic_records, totals=totals, total_cost=total_cost)


@router.get("/user/{user_id}", response_model=List[DailyUsageResponse])
async def get_user_daily_usage(
    user_id: str,
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model_id: Optional[str] = Query(default=None),
) -> List[DailyUsageResponse]:
    async with async_session_factory() as session:
        entries = await usage_tracker.get_user_daily_usage(
            session,
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            provider=provider,
            model_id=model_id,
        )

    if not entries:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User usage not found")

    return [
        DailyUsageResponse(
            date=entry.date,
            provider=entry.provider,
            model_id=entry.model_id,
            prompt_tokens=entry.prompt_tokens,
            completion_tokens=entry.completion_tokens,
            total_tokens=entry.total_tokens,
            total_cost=round(entry.total_cost, 6),
            request_count=entry.request_count,
        )
        for entry in entries
    ]


@router.get("/user/{user_id}/all", response_model=UserUsageHistoryResponse)
async def get_full_user_usage(user_id: str) -> UserUsageHistoryResponse:
    async with async_session_factory() as session:
        daily_entries = await usage_tracker.get_user_daily_usage(session, user_id=user_id)
        monthly_entries = await usage_tracker.get_monthly_usage(session, user_id=user_id)
        session_entries = await usage_tracker.get_user_session_usage(session, user_id=user_id)

    if not daily_entries and not monthly_entries and not session_entries:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User usage not found")

    totals = UsageBreakdown(
        prompt_tokens=sum(entry.prompt_tokens for entry in daily_entries),
        completion_tokens=sum(entry.completion_tokens for entry in daily_entries),
        total_tokens=sum(entry.total_tokens for entry in daily_entries),
    )

    total_cost = round(sum(entry.total_cost for entry in daily_entries), 6)

    return UserUsageHistoryResponse(
        user_id=user_id,
        totals=totals,
        total_cost=total_cost,
        daily=[
            DailyUsageResponse(
                date=entry.date,
                provider=entry.provider,
                model_id=entry.model_id,
                prompt_tokens=entry.prompt_tokens,
                completion_tokens=entry.completion_tokens,
                total_tokens=entry.total_tokens,
                total_cost=round(entry.total_cost, 6),
                request_count=entry.request_count,
            )
            for entry in daily_entries
        ],
        monthly=[
            MonthlyUsageResponse(
                year_month=entry.year_month,
                provider=entry.provider,
                model_id=entry.model_id,
                prompt_tokens=entry.prompt_tokens,
                completion_tokens=entry.completion_tokens,
                total_tokens=entry.total_tokens,
                total_cost=round(entry.total_cost, 6),
                request_count=entry.request_count,
            )
            for entry in monthly_entries
        ],
        sessions=[
            SessionUsageRecord(
                session_id=entry.session_id,
                user_id=entry.user_id,
                usage_date=entry.usage_date,
                provider=entry.provider,
                model_id=entry.model_id,
                prompt_tokens=entry.prompt_tokens,
                completion_tokens=entry.completion_tokens,
                total_tokens=entry.total_tokens,
                input_cost=entry.input_cost,
                output_cost=entry.output_cost,
                total_cost=entry.total_cost,
                currency=entry.currency,
                created_at=entry.created_at,
            )
            for entry in session_entries
        ],
    )


@router.get("/daily", response_model=List[DailyUsageResponse])
async def get_daily_usage(
    provider: Optional[str] = Query(default=None),
    model_id: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
) -> List[DailyUsageResponse]:
    today = date.today()
    async with async_session_factory() as session:
        entries = await usage_tracker.get_daily_usage(
            session,
            usage_date=today,
            provider=provider,
            model_id=model_id,
            user_id=user_id,
        )

    return [
        DailyUsageResponse(
            date=entry.date,
            provider=entry.provider,
            model_id=entry.model_id,
            prompt_tokens=entry.prompt_tokens,
            completion_tokens=entry.completion_tokens,
            total_tokens=entry.total_tokens,
            total_cost=round(entry.total_cost, 6),
            request_count=entry.request_count,
        )
        for entry in entries
    ]


@router.get("/daily/{usage_date}", response_model=List[DailyUsageResponse])
async def get_daily_usage_for_date(
    usage_date: date,
    provider: Optional[str] = Query(default=None),
    model_id: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
) -> List[DailyUsageResponse]:
    async with async_session_factory() as session:
        entries = await usage_tracker.get_daily_usage(
            session,
            usage_date=usage_date,
            provider=provider,
            model_id=model_id,
            user_id=user_id,
        )

    return [
        DailyUsageResponse(
            date=entry.date,
            provider=entry.provider,
            model_id=entry.model_id,
            prompt_tokens=entry.prompt_tokens,
            completion_tokens=entry.completion_tokens,
            total_tokens=entry.total_tokens,
            total_cost=round(entry.total_cost, 6),
            request_count=entry.request_count,
        )
        for entry in entries
    ]


@router.get("/monthly", response_model=List[MonthlyUsageResponse])
async def get_monthly_usage(
    provider: Optional[str] = Query(default=None),
    model_id: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
) -> List[MonthlyUsageResponse]:
    today = datetime.utcnow()
    year_month = f"{today.year:04d}-{today.month:02d}"
    async with async_session_factory() as session:
        entries = await usage_tracker.get_monthly_usage(
            session,
            year_month=year_month,
            provider=provider,
            model_id=model_id,
            user_id=user_id,
        )

    return [
        MonthlyUsageResponse(
            year_month=entry.year_month,
            provider=entry.provider,
            model_id=entry.model_id,
            prompt_tokens=entry.prompt_tokens,
            completion_tokens=entry.completion_tokens,
            total_tokens=entry.total_tokens,
            total_cost=round(entry.total_cost, 6),
            request_count=entry.request_count,
        )
        for entry in entries
    ]


@router.get("/monthly/{year_month}", response_model=List[MonthlyUsageResponse])
async def get_monthly_usage_for_period(
    year_month: str,
    provider: Optional[str] = Query(default=None),
    model_id: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
) -> List[MonthlyUsageResponse]:
    async with async_session_factory() as session:
        entries = await usage_tracker.get_monthly_usage(
            session,
            year_month=year_month,
            provider=provider,
            model_id=model_id,
            user_id=user_id,
        )

    return [
        MonthlyUsageResponse(
            year_month=entry.year_month,
            provider=entry.provider,
            model_id=entry.model_id,
            prompt_tokens=entry.prompt_tokens,
            completion_tokens=entry.completion_tokens,
            total_tokens=entry.total_tokens,
            total_cost=round(entry.total_cost, 6),
            request_count=entry.request_count,
        )
        for entry in entries
    ]
