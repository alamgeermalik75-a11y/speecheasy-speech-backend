from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user_uid
from app.schemas.profile import ProfileCreateOrUpdate, ProfileResponse
from app.services.profile_service import ProfileService
from app.config import settings
from app.services.supabase_db_service import SupabaseDbService
from app.core.exceptions import NotFoundException

router = APIRouter(prefix="/profiles", tags=["Profiles"])

@router.get("/me", response_model=ProfileResponse)
async def get_my_profile(
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetch the currently authenticated patient's profile and active focus sound.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        prof = SupabaseDbService.get_profile(current_uid)
        if not prof:
            raise NotFoundException("Profile not found")
        return prof

    profile = await ProfileService.get_profile(db, current_uid)
    return profile

@router.post("", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
@router.put("", response_model=ProfileResponse)
async def create_or_update_profile(
    data: ProfileCreateOrUpdate,
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Create or update the authenticated patient's profile.
    Initializes or preserves focus sound progress.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseDbService.save_profile(
            current_uid, data.parent_name, data.child_name, data.phone, data.sound, data.alphabet_name, data.age
        )

    profile = await ProfileService.upsert_profile(db, current_uid, data)
    return profile

@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete the authenticated patient's account and all associated child data.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        SupabaseDbService.delete_profile(current_uid)
        return None

    await ProfileService.delete_profile(db, current_uid)
    return None
