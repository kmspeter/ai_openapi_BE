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
    UserDailyUsageResponse,
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


@router.get("/users", response_model=List[UserDailyUsageResponse])
async def get_all_users_daily_usage(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    model_id: Optional[str] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
) -> List[UserDailyUsageResponse]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be before or equal to end_date",
        )

    async with async_session_factory() as session:
        entries = await usage_tracker.get_all_users_daily_usage(
            session,
            start_date=start_date,
            end_date=end_date,
            provider=provider,
            model_id=model_id,
            user_id=user_id,
        )

    if not entries:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usage not found")

    return [
        UserDailyUsageResponse(
            user_id=entry.user_id,
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
