from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user_uid
from app.schemas.notification import NotificationResponse, UnreadCountResponse, ActionCountResponse
from app.services.notification_service import NotificationService
from app.config import settings
from app.services.supabase_db_service import SupabaseDbService

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.get("", response_model=List[NotificationResponse])
async def list_notifications(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    List notifications belonging to the authenticated patient, ordered newest first.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        notifs = SupabaseDbService.get_notifications(current_uid)
        return [NotificationResponse.model_validate(n) for n in notifs]

    return await NotificationService.get_notifications(db, current_uid, limit, offset)

@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_notification_count(
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the count of unread notifications for the authenticated patient.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        count = SupabaseDbService.get_unread_count(current_uid)
        return UnreadCountResponse(count=count)

    count = await NotificationService.get_unread_count(db, current_uid)
    return UnreadCountResponse(count=count)

@router.patch("/mark-read", response_model=ActionCountResponse)
async def mark_all_notifications_as_read(
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Mark all unread notifications for the authenticated patient as read.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        SupabaseDbService.mark_notifications_read(current_uid)
        return ActionCountResponse(success=True, count=1)

    updated_count = await NotificationService.mark_all_read(db, current_uid)
    return ActionCountResponse(success=True, count=updated_count)

@router.delete("", response_model=ActionCountResponse)
async def clear_all_notifications(
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Clear all notification history for the authenticated patient.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        SupabaseDbService.clear_notifications(current_uid)
        return ActionCountResponse(success=True, count=1)

    deleted_count = await NotificationService.delete_all(db, current_uid)
    return ActionCountResponse(success=True, count=deleted_count)
