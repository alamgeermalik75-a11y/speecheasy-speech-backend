from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user_uid
from app.schemas.patient import PatientCreate, PatientUpdate, PatientResponse
from app.services.patient_service import PatientService
from app.services.supabase_db_service import SupabaseDbService
from app.config import settings

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.post("", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
async def create_patient_record(
    data: PatientCreate,
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a patient record in the patients table with strict foreign key references:
    - patient_uid references authenticated user's canonical ID (users.id)
    - doctor_id references verified approved therapist (therapists.id)
    - All fields (doctor_id, name, age, phone, parent_email, accuracy) are strictly required.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        res = SupabaseDbService.create_patient(
            current_uid=current_uid,
            doctor_id=data.doctor_id,
            name=data.name,
            age=data.age,
            phone=data.phone,
            parent_email=str(data.parent_email),
            accuracy=data.accuracy
        )
        return PatientResponse.model_validate(res)

    return await PatientService.create_patient(db, current_uid, data)


@router.get("/me", response_model=PatientResponse)
async def get_my_patient_record(
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetch the currently authenticated patient's clinical link and doctor information.
    Strictly isolated to authenticated user's ID.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        res = SupabaseDbService.get_patient_me(current_uid)
        return PatientResponse.model_validate(res)

    return await PatientService.get_patient_me(db, current_uid)


@router.put("/me", response_model=PatientResponse)
async def update_my_patient_record(
    data: PatientUpdate,
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Update the authenticated patient's clinical record and doctor assignment.
    All fields are strictly required; nothing is optional.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        res = SupabaseDbService.update_patient_me(
            current_uid=current_uid,
            doctor_id=data.doctor_id,
            name=data.name,
            age=data.age,
            phone=data.phone,
            parent_email=str(data.parent_email),
            accuracy=data.accuracy
        )
        return PatientResponse.model_validate(res)

    return await PatientService.update_patient_me(db, current_uid, data)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_patient_record(
    current_uid: str = Depends(get_current_user_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    Unregister and remove the authenticated patient's record from the patients table.
    """
    if settings.SUPABASE_SERVICE_ROLE_KEY:
        SupabaseDbService.delete_patient_me(current_uid)
        return None

    await PatientService.delete_patient_me(db, current_uid)
    return None
