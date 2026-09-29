from typing import Optional
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.therapist import Therapist, Patient
from app.models.appointment import Appointment
from app.models.rating import Rating
from app.models.profile import Profile
from app.schemas.rating import SubmitRatingRequest, MyRatingResponse
from app.core.exceptions import NotFoundException, BadRequestException, ForbiddenException

class RatingService:
    @staticmethod
    async def get_my_rating(session: AsyncSession, patient_uid: str, doctor_id: str) -> MyRatingResponse:
        stmt = select(Rating).where(
            and_(Rating.doctor_id == doctor_id, Rating.patient_uid == patient_uid)
        )
        rating_obj = (await session.execute(stmt)).scalar_one_or_none()
        return MyRatingResponse(
            doctor_id=doctor_id,
            rating=rating_obj.rating if rating_obj else None
        )

    @staticmethod
    async def submit_rating(
        session: AsyncSession,
        patient_uid: str,
        data: SubmitRatingRequest,
        require_prior_interaction: bool = False
    ) -> float:
        # 1. Verify patient profile exists
        profile = (await session.execute(select(Profile).where(Profile.patient_uid == patient_uid))).scalar_one_or_none()
        if not profile:
            raise NotFoundException("Patient profile not found")

        # 2. Verify doctor exists and is approved
        doctor = (await session.execute(select(Therapist).where(Therapist.id == data.doctor_id))).scalar_one_or_none()
        if not doctor:
            raise NotFoundException("Doctor not found")
        if doctor.status != "approved":
            raise BadRequestException("Cannot submit rating for an unapproved doctor")

        # 3. Rating Eligibility check (Rule A)
        if require_prior_interaction:
            # Verify if patient has a record in patients or appointments
            linked = (await session.execute(
                select(Patient).where(and_(Patient.doctor_id == data.doctor_id, Patient.patient_uid == patient_uid))
            )).scalar_one_or_none()

            has_appt = (await session.execute(
                select(Appointment).where(and_(Appointment.doctor_id == data.doctor_id, Appointment.patient_uid == patient_uid))
            )).scalar_one_or_none()

            if not linked and not has_appt:
                raise ForbiddenException("You can only rate a doctor after registering or booking an appointment with them.")

        # 4. Upsert rating (guarantee one rating per patient/doctor)
        stmt_rating = select(Rating).where(
            and_(Rating.doctor_id == data.doctor_id, Rating.patient_uid == patient_uid)
        )
        existing_rating = (await session.execute(stmt_rating)).scalar_one_or_none()

        if existing_rating:
            existing_rating.rating = data.rating
        else:
            new_rating = Rating(
                doctor_id=data.doctor_id,
                patient_uid=patient_uid,
                rating=data.rating
            )
            session.add(new_rating)

        await session.flush()

        # 5. Recalculate doctor aggregate average rating
        avg_stmt = select(func.avg(Rating.rating)).where(Rating.doctor_id == data.doctor_id)
        avg_result = (await session.execute(avg_stmt)).scalar()
        new_avg = round(float(avg_result), 2) if avg_result is not None else float(data.rating)

        doctor.rating = new_avg
        await session.commit()
        return new_avg
