from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user_uid
from app.schemas.attempt import (
    CreateAttemptRequest,
    AttemptResultResponse,
    AttemptResponse,
    ProgressOverviewResponse
)
from app.services.progress_service import ProgressService
from app.config import settings
from app.services.supabase_db_service import SupabaseDbService

router = APIRouter(prefix="/attempts", tags=["Practice Attempts"])

@router.post("", response_model=AttemptResultResponse, status_code=status.HTTP_201_CREATED)
async def record_practice_attempt(
    data: CreateAttemptRequest,
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Log a pronunciation attempt with atomic unique-item highest-score logic,
    category 20% calculation, sequential gating, and overall progress.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        res = SupabaseDbService.record_attempt(
            current_uid, data.item_id, data.alphabet_name, data.level_key, data.score
        )
        return AttemptResultResponse(
            attempt=AttemptResponse.model_validate(res["attempt"]),
            milestone_notification=res.get("milestone_notification"),
            sound_mastered=res.get("sound_mastered", False),
            next_sound=res.get("next_sound"),
            focus_progress=res.get("focus_progress", 0.0),
            category_progress=res.get("category_progress"),
            alphabet_progress=res.get("alphabet_progress"),
            overall_progress=res.get("overall_progress"),
            improved=res.get("improved"),
            progress_earned=res.get("progress_earned"),
            is_category_completed=res.get("is_category_completed"),
            next_category_unlocked=res.get("next_category_unlocked"),
        )

    return await ProgressService.record_attempt(db, current_uid, data)

@router.get("/overview", response_model=ProgressOverviewResponse)
@router.get("/progress", response_model=ProgressOverviewResponse)
async def get_progress_overview(
    alphabet_name: Optional[str] = Query(None),
    tz_offset_minutes: Optional[int] = Query(0),
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetch authenticated patient's progress overview:
    - overall progress across all 36 alphabets
    - current alphabet progress
    - 5 categories breakdown with percentage, unlock and completion states
    - daily, weekly, and monthly progress
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        data = SupabaseDbService.get_progress_overview(current_uid, alphabet_name, tz_offset_minutes=tz_offset_minutes or 0)
        return ProgressOverviewResponse.model_validate(data)

    return await ProgressService.get_progress_overview(db, current_uid, alphabet_name, tz_offset_minutes=tz_offset_minutes or 0)

@router.get("/history", response_model=List[AttemptResponse])
async def get_practice_history(
    alphabet_name: Optional[str] = Query(None),
    level_key: Optional[str] = Query(None, pattern=r"^(words|sentences|fillBlanks|poems|story)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetch authenticated patient's practice history, strictly scoped to their own UID.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        history = SupabaseDbService.get_attempt_history(
            current_uid=current_uid,
            alphabet_name=alphabet_name,
            level_key=level_key,
            limit=limit,
            offset=offset
        )
        return [AttemptResponse.model_validate(h) for h in history]

    attempts = await ProgressService.get_history(
        session=db,
        patient_uid=current_uid,
        alphabet_name=alphabet_name,
        level_key=level_key,
        limit=limit,
        offset=offset
    )
    return attempts

@router.delete("/reset", status_code=status.HTTP_200_OK)
async def reset_practice_progress(
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Reset all practice progress, attempts, and progress events for authenticated user to zero.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseDbService.reset_progress(current_uid)
    return await ProgressService.reset_progress(db, current_uid)
