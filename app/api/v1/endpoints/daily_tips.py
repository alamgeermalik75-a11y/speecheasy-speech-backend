from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy import select, and_, asc
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.daily_tip import DailyTip
from app.schemas.daily_tip import DailyTipResponse

from app.config import settings
from app.services.supabase_db_service import SupabaseDbService

router = APIRouter(prefix="/daily-tips", tags=["Daily Tips"])

@router.get("", response_model=List[DailyTipResponse])
async def get_active_daily_tips(
    db: AsyncSession = Depends(get_db)
):
    """
    Get all active speech therapy daily tips ordered by sort_order.
    Used by Flutter app for dayOfYear % tips.length rotation.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        import anyio
        return await anyio.to_thread.run_sync(SupabaseDbService.list_daily_tips)

    stmt = (
        select(DailyTip)
        .where(DailyTip.is_active.is_(True))
        .order_by(asc(DailyTip.sort_order), asc(DailyTip.created_at))
    )
    result = await db.execute(stmt)
    tips = result.scalars().all()
    return tips
