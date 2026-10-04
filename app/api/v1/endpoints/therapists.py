from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user_uid
from app.models.therapist import Therapist, Patient, PatientRequest
from app.models.profile import Profile
from app.schemas.therapist import (
    TherapistResponse,
    DoctorCodeQuery,
    PatientRequestCreate,
    PatientRequestResponse,
    MyDoctorStatusResponse
)
from app.core.exceptions import NotFoundException, BadRequestException, ConflictException
from app.config import settings
from app.services.supabase_db_service import SupabaseDbService

router = APIRouter(prefix="/therapists", tags=["Therapists"])

@router.get("", response_model=List[TherapistResponse])
async def list_therapists(
    status_filter: str = Query("approved", alias="status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """
    List verified therapists. Defaults to status='approved'.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        import anyio
        return await anyio.to_thread.run_sync(
            SupabaseDbService.list_therapists, status_filter, limit, offset
        )

    stmt = (
        select(Therapist)
        .where(Therapist.status == status_filter)
        .order_by(desc(Therapist.rating))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())

@router.get("/by-code/{code}", response_model=TherapistResponse)
async def get_therapist_by_code(
    code: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Find an approved doctor using their unique clinical doctor_code (e.g. SPK-1234).
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        import anyio
        return await anyio.to_thread.run_sync(SupabaseDbService.get_therapist_by_code, code)

    cleaned_code = code.strip().upper()
    stmt = select(Therapist).where(
        and_(Therapist.doctor_code == cleaned_code, Therapist.status == "approved")
    )
    doctor = (await db.execute(stmt)).scalar_one_or_none()
    if not doctor:
        raise NotFoundException("No approved doctor found with that code.")
    return doctor

@router.post("/request", response_model=PatientRequestResponse, status_code=status.HTTP_201_CREATED)
async def request_therapist_registration(
    data: PatientRequestCreate,
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a registration request to a doctor. Auto-binds child name and parent identity.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseDbService.request_therapist_registration(current_uid, data.doctor_id)

    # 1. Fetch patient profile
    profile = (await db.execute(select(Profile).where(Profile.patient_uid == current_uid))).scalar_one_or_none()
    if not profile:
        raise NotFoundException("Please complete your child's profile before requesting a doctor.")

    # 2. Check doctor exists and is approved
    doctor = (await db.execute(select(Therapist).where(Therapist.id == data.doctor_id))).scalar_one_or_none()
    if not doctor:
        raise NotFoundException("Doctor not found")
    if doctor.status != "approved":
        raise BadRequestException("Cannot request an unapproved doctor")

    # 3. Rule 1, 2, 4: Enforce patient can have only ONE active doctor
    linked_stmt = select(Patient).where(Patient.patient_uid == current_uid)
    if (await db.execute(linked_stmt)).scalar_one_or_none():
        raise ConflictException("You are already registered with a doctor. You must first unregister from your current doctor before requesting another doctor.")

    # 4. Rule 5: Prevent duplicate or parallel doctor requests
    pending_stmt = select(PatientRequest).where(
        and_(
            PatientRequest.patient_uid == current_uid,
            PatientRequest.status == "pending"
        )
    )
    if (await db.execute(pending_stmt)).scalar_one_or_none():
        raise ConflictException("You already have a pending registration request. You can only request one doctor at a time. Please wait for a response or cancel it first.")

    # 5. Insert request
    child_name = profile.child_name or "Child"
    request = PatientRequest(
        doctor_id=data.doctor_id,
        patient_uid=current_uid,
        patient_name=child_name,
        parent_email=None,
        phone=profile.phone,
        age=profile.age,
        status="pending"
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)
    return request

@router.get("/my-status", response_model=MyDoctorStatusResponse)
async def get_my_doctor_status(
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Check current doctor connection status:
    - 'approved': active linked doctor in patients table
    - 'pending': active pending request in patient_requests
    - 'none': no active link or request
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        import anyio
        res = await anyio.to_thread.run_sync(SupabaseDbService.get_my_doctor_status, current_uid)
        return MyDoctorStatusResponse(
            status=res["status"],
            doctor=TherapistResponse.model_validate(res["doctor"]) if res.get("doctor") else None,
            request=PatientRequestResponse.model_validate(res["request"]) if res.get("request") else None
        )

    # 1. Check patients table
    patient_link = (await db.execute(
        select(Patient).where(Patient.patient_uid == current_uid)
    )).scalar_one_or_none()

    if patient_link:
        doctor = (await db.execute(
            select(Therapist).where(Therapist.id == patient_link.doctor_id)
        )).scalar_one_or_none()
        if doctor:
            return MyDoctorStatusResponse(
                status="approved",
                doctor=TherapistResponse.model_validate(doctor),
                request=None
            )

    # 2. Check pending patient_requests
    pending_req = (await db.execute(
        select(PatientRequest)
        .where(and_(PatientRequest.patient_uid == current_uid, PatientRequest.status == "pending"))
        .order_by(desc(PatientRequest.created_at))
    )).scalars().first()

    if pending_req:
        return MyDoctorStatusResponse(
            status="pending",
            doctor=None,
            request=PatientRequestResponse.model_validate(pending_req)
        )

    return MyDoctorStatusResponse(status="none", doctor=None, request=None)

@router.delete("/my-doctor", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_my_doctor(
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Unregister patient from current linked doctor or cancel any pending request.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        SupabaseDbService.unregister_my_doctor(current_uid)
        return None

    stmt = select(Patient).where(Patient.patient_uid == current_uid)
    res = await db.execute(stmt)
    patient_link = res.scalar_one_or_none()
    if patient_link:
        await db.delete(patient_link)

    pending_stmt = select(PatientRequest).where(
        and_(PatientRequest.patient_uid == current_uid, PatientRequest.status == "pending")
    )
    pending_requests = (await db.execute(pending_stmt)).scalars().all()
    for req in pending_requests:
        await db.delete(req)

    await db.commit()
    return None

@router.post("/requests/{request_id}/accept")
async def accept_patient_request(
    request_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Doctor/System accepts a patient registration request.
    Atomically links patient with the doctor, rejects other pending requests,
    and inserts an immediate in-app notification.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseDbService.accept_patient_request(request_id)

    # Local DB fallback
    req = (await db.execute(select(PatientRequest).where(PatientRequest.id == request_id))).scalar_one_or_none()
    if not req:
        raise NotFoundException("Patient registration request not found.")

    # Rule 1 & 12: Race condition protection
    active = (await db.execute(select(Patient).where(Patient.patient_uid == req.patient_uid))).scalar_one_or_none()
    if active and active.doctor_id != req.doctor_id:
        raise ConflictException("This patient is already registered with another active doctor.")

    req.status = "accepted"
    if not active:
        new_link = Patient(
            doctor_id=req.doctor_id,
            patient_uid=req.patient_uid,
            name=req.patient_name,
            phone=req.phone,
            age=req.age,
            parent_email=req.parent_email
        )
        db.add(new_link)

    # Reject other pending requests
    other_pending = (await db.execute(
        select(PatientRequest).where(
            and_(
                PatientRequest.patient_uid == req.patient_uid,
                PatientRequest.id != request_id,
                PatientRequest.status == "pending"
            )
        )
    )).scalars().all()
    for op_req in other_pending:
        op_req.status = "rejected"

    await db.commit()
    return {"success": True, "message": "Request accepted successfully.", "request_id": request_id}


@router.post("/requests/{request_id}/reject")
async def reject_patient_request(
    request_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Doctor/System rejects a patient registration request.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseDbService.reject_patient_request(request_id)

    req = (await db.execute(select(PatientRequest).where(PatientRequest.id == request_id))).scalar_one_or_none()
    if not req:
        raise NotFoundException("Patient registration request not found.")

    req.status = "rejected"
    await db.commit()
    return {"success": True, "message": "Request rejected.", "request_id": request_id}


@router.get("/{doctor_id}", response_model=TherapistResponse)
async def get_therapist_by_id(
    doctor_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed information about an approved therapist by doctor ID.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseDbService.get_therapist_by_id(doctor_id)

    stmt = select(Therapist).where(and_(Therapist.id == doctor_id, Therapist.status == "approved"))
    doctor = (await db.execute(stmt)).scalar_one_or_none()
    if not doctor:
        raise NotFoundException("Doctor not found")
    return doctor


