from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user_uid
from app.schemas.rating import SubmitRatingRequest, MyRatingResponse
from app.services.rating_service import RatingService
from app.config import settings
from app.services.supabase_db_service import SupabaseDbService

router = APIRouter(prefix="/ratings", tags=["Ratings"])

@router.get("/{doctor_id}/my-rating", response_model=MyRatingResponse)
async def get_my_doctor_rating(
    doctor_id: str,
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the rating submitted by the authenticated patient for a specific doctor.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        rating = SupabaseDbService.get_my_rating(current_uid, doctor_id)
        return MyRatingResponse(doctor_id=doctor_id, rating=rating)

    return await RatingService.get_my_rating(db, current_uid, doctor_id)

@router.post("", response_model=dict)
async def submit_or_update_doctor_rating(
    data: SubmitRatingRequest,
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Submit or update a 1-5 star doctor rating and recalculate the doctor's average rating.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        res = SupabaseDbService.submit_rating(current_uid, data.doctor_id, data.rating)
        return {
            "success": True,
            "message": "Rating submitted successfully",
            "doctor_id": data.doctor_id,
            "new_average_rating": res.get("rating")
        }

    new_avg = await RatingService.submit_rating(db, current_uid, data)
    return {
        "success": True,
        "message": "Rating submitted successfully",
        "doctor_id": data.doctor_id,
        "new_average_rating": new_avg
    }
