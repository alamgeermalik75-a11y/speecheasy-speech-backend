import uuid
from typing import Dict, Any
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.therapist import Patient, Therapist
from app.models.profile import Profile
from app.schemas.patient import PatientCreate, PatientUpdate, PatientResponse
from app.schemas.therapist import TherapistResponse
from app.core.exceptions import NotFoundException, BadRequestException, ConflictException


class PatientService:
    @staticmethod
    async def create_patient(
        session: AsyncSession,
        current_uid: str,
        data: PatientCreate
    ) -> PatientResponse:
        # 1. Verify doctor exists and is approved
        doctor_stmt = select(Therapist).where(and_(Therapist.id == data.doctor_id, Therapist.status == "approved"))
        doctor = (await session.execute(doctor_stmt)).scalar_one_or_none()
        if not doctor:
            raise NotFoundException("Doctor not found or not approved")

        # 2. Check if already registered
        existing_stmt = select(Patient).where(Patient.patient_uid == current_uid)
        existing = (await session.execute(existing_stmt)).scalar_one_or_none()
        if existing:
            raise ConflictException("Patient is already registered with a therapist. Unlink first or update.")

        # 3. Insert record with foreign key references
        patient = Patient(
            id=str(uuid.uuid4()),
            doctor_id=data.doctor_id,
            patient_uid=current_uid,
            name=data.name.strip(),
            age=data.age,
            phone=data.phone.strip(),
            parent_email=str(data.parent_email).strip().lower(),
            accuracy=data.accuracy,
        )
        session.add(patient)

        # 4. Sync profile table doctor_uid, child_name, phone, age
        prof_stmt = select(Profile).where(Profile.patient_uid == current_uid)
        prof = (await session.execute(prof_stmt)).scalar_one_or_none()
        if prof:
            prof.child_name = data.name.strip()
            prof.phone = data.phone.strip()
            prof.age = data.age
            prof.doctor_uid = data.doctor_id

        await session.commit()
        await session.refresh(patient)

        return PatientResponse(
            id=patient.id,
            doctor_id=patient.doctor_id,
            patient_uid=patient.patient_uid,
            name=patient.name,
            age=patient.age,
            phone=patient.phone,
            parent_email=patient.parent_email,
            accuracy=float(patient.accuracy or 0.0),
            doctor=TherapistResponse.model_validate(doctor),
            created_at=patient.created_at,
            updated_at=patient.updated_at
        )

    @staticmethod
    async def get_patient_me(
        session: AsyncSession,
        current_uid: str
    ) -> PatientResponse:
        stmt = select(Patient).where(Patient.patient_uid == current_uid)
        patient = (await session.execute(stmt)).scalar_one_or_none()
        if not patient:
            raise NotFoundException("Patient record not found. You are not currently registered with a therapist.")

        doctor_stmt = select(Therapist).where(Therapist.id == patient.doctor_id)
        doctor = (await session.execute(doctor_stmt)).scalar_one_or_none()

        return PatientResponse(
            id=patient.id,
            doctor_id=patient.doctor_id,
            patient_uid=patient.patient_uid,
            name=patient.name,
            age=patient.age,
            phone=patient.phone,
            parent_email=patient.parent_email,
            accuracy=float(patient.accuracy or 0.0),
            doctor=TherapistResponse.model_validate(doctor) if doctor else None,
            created_at=patient.created_at,
            updated_at=patient.updated_at
        )

    @staticmethod
    async def update_patient_me(
        session: AsyncSession,
        current_uid: str,
        data: PatientUpdate
    ) -> PatientResponse:
        stmt = select(Patient).where(Patient.patient_uid == current_uid)
        patient = (await session.execute(stmt)).scalar_one_or_none()
        if not patient:
            raise NotFoundException("Patient record not found. You must create one first.")

        doctor_stmt = select(Therapist).where(and_(Therapist.id == data.doctor_id, Therapist.status == "approved"))
        doctor = (await session.execute(doctor_stmt)).scalar_one_or_none()
        if not doctor:
            raise NotFoundException("Doctor not found or not approved")

        patient.doctor_id = data.doctor_id
        patient.name = data.name.strip()
        patient.age = data.age
        patient.phone = data.phone.strip()
        patient.parent_email = str(data.parent_email).strip().lower()
        patient.accuracy = data.accuracy

        # Sync profile table child_name, phone, age, doctor_uid
        prof_stmt = select(Profile).where(Profile.patient_uid == current_uid)
        prof = (await session.execute(prof_stmt)).scalar_one_or_none()
        if prof:
            prof.child_name = data.name.strip()
            prof.phone = data.phone.strip()
            prof.age = data.age
            prof.doctor_uid = data.doctor_id

        await session.commit()
        await session.refresh(patient)

        return PatientResponse(
            id=patient.id,
            doctor_id=patient.doctor_id,
            patient_uid=patient.patient_uid,
            name=patient.name,
            age=patient.age,
            phone=patient.phone,
            parent_email=patient.parent_email,
            accuracy=float(patient.accuracy or 0.0),
            doctor=TherapistResponse.model_validate(doctor),
            created_at=patient.created_at,
            updated_at=patient.updated_at
        )

    @staticmethod
    async def delete_patient_me(
        session: AsyncSession,
        current_uid: str
    ) -> None:
        stmt = select(Patient).where(Patient.patient_uid == current_uid)
        patient = (await session.execute(stmt)).scalar_one_or_none()
        if patient:
            await session.delete(patient)
            await session.commit()
