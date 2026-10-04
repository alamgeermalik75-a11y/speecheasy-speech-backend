from datetime import date
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user_uid
from app.models.appointment import Appointment
from app.schemas.appointment import (
    CreateAppointmentRequest,
    AvailableSlotsResponse,
    AppointmentResponse,
    UpdateAppointmentStatusRequest,
    SessionListResponse
)
from app.services.booking_service import BookingService
from app.config import settings
from app.services.supabase_db_service import SupabaseDbService
from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException

# Statuses a PATIENT is allowed to set on their own appointment.
# Therapist-controlled statuses (confirmed / completed) are rejected here.
PATIENT_ALLOWED_STATUSES = {"cancelled", "pending"}

router = APIRouter(tags=["Appointments"])

@router.get("/therapists/{doctor_id}/slots", response_model=AvailableSlotsResponse)
async def get_doctor_available_slots(
    doctor_id: str,
    date_query: date = Query(..., alias="date", description="Date to query availability for"),
    db: AsyncSession = Depends(get_db)
):
    """
    Calculate and return available 30-minute time slots for a doctor on a given date.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        data = SupabaseDbService.get_doctor_available_slots(doctor_id, date_query)
        return AvailableSlotsResponse(date=date_query, slots=data["slots"], all_slots=data["all_slots"])

    data = await BookingService.get_available_slots(db, doctor_id, date_query)
    return AvailableSlotsResponse(date=date_query, slots=data["slots"], all_slots=data["all_slots"])

@router.get("/appointments/me", response_model=SessionListResponse)
@router.get("/appointments", response_model=SessionListResponse)
async def get_my_appointments(
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetch all appointments and clinical session history for the authenticated patient,
    enriched with doctor details, patient details, and cancellation quota status.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        import anyio
        data = await anyio.to_thread.run_sync(SupabaseDbService.get_my_appointments, current_uid)
        return SessionListResponse.model_validate(data)

    data = await BookingService.get_my_appointments(db, current_uid)
    return SessionListResponse.model_validate(data)

@router.post("/appointments", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
async def book_appointment(
    data: CreateAppointmentRequest,
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Book a 30-minute session with a speech therapist with concurrency and double-booking protection.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseDbService.book_appointment(
            current_uid, data.doctor_id, data.appointment_date, data.start_time, data.end_time
        )

    return await BookingService.create_appointment(db, current_uid, data)

@router.patch("/appointments/{appointment_id}/status", response_model=AppointmentResponse)
async def update_appointment_status(
    appointment_id: str,
    data: UpdateAppointmentStatusRequest,
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Patient-facing appointment status update.

    Rules (spec section 20):
    - The appointment MUST belong to the authenticated patient (ownership
      enforced server-side; a patient can never modify someone else's).
    - Patients may only cancel (or re-pend) their own appointment.
    - confirmed / completed remain therapist/system-controlled and are
      rejected with 403.
    """
    if data.status not in PATIENT_ALLOWED_STATUSES:
        raise ForbiddenException(
            "Patients can only cancel their appointments; other status changes are handled by the therapist."
        )

    if settings.SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseDbService.update_appointment_status(
            appointment_id, data.status, patient_uid=current_uid
        )

    stmt = select(Appointment).where(Appointment.id == appointment_id)
    appointment = (await db.execute(stmt)).scalar_one_or_none()
    if not appointment:
        raise NotFoundException("Appointment not found")

    # Ownership check: patient may only touch their own appointment.
    if appointment.patient_uid != current_uid:
        raise ForbiddenException("You do not have access to this appointment.")

    if appointment.status == "cancelled":
        raise BadRequestException("Appointment is already cancelled.")

    appointment.status = data.status
    await db.commit()
    await db.refresh(appointment)
    return appointment
