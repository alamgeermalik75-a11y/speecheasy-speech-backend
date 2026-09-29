from fastapi import APIRouter
from app.api.v1.endpoints import (
    profiles,
    patients,
    daily_tips,
    ratings,
    therapists,
    appointments,
    attempts,
    notifications,
    chat,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(profiles.router)
api_router.include_router(patients.router)
api_router.include_router(daily_tips.router)
api_router.include_router(ratings.router)
api_router.include_router(therapists.router)
api_router.include_router(appointments.router)
api_router.include_router(attempts.router)
api_router.include_router(notifications.router)
api_router.include_router(chat.router)
