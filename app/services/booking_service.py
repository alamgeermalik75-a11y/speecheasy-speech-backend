from datetime import date, time, datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy import select, and_, func, desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.therapist import Therapist, Availability
from app.models.appointment import Appointment
from app.models.profile import Profile
from app.models.notification import Notification
from app.schemas.appointment import CreateAppointmentRequest
from app.core.exceptions import NotFoundException, BadRequestException, ConflictException, ForbiddenException

class BookingService:
    @staticmethod
    def _format_time_slot(t: time) -> str:
        dummy = datetime.combine(date(2000, 1, 1), t)
        formatted = dummy.strftime("%I:%M %p")
        if formatted.startswith("0"):
            return formatted[1:]
        return formatted

    @staticmethod
    async def get_available_slots(session: AsyncSession, doctor_id: str, slot_date: date) -> Dict[str, Any]:
        if slot_date < date.today():
            return {"slots": [], "all_slots": []}

        # 1. Check doctor exists and is approved
        stmt = select(Therapist).where(Therapist.id == doctor_id)
        doctor = (await session.execute(stmt)).scalar_one_or_none()
        if not doctor:
            raise NotFoundException("Doctor not found")
        if doctor.status != "approved":
            raise BadRequestException("Doctor is not currently approved for bookings")

        # 2. Get active availability for the day of week (recurring schedule)
        day_name = slot_date.strftime("%A")
        stmt_avail = select(Availability).where(
            and_(
                Availability.doctor_id == doctor_id,
                Availability.day == day_name,
                Availability.is_active.is_(True)
            )
        )
        availabilities = (await session.execute(stmt_avail)).scalars().all()
        if not availabilities:
            return {"slots": [], "all_slots": []}

        # 3. Generate candidate 30-minute intervals
        candidate_blocks = []
        dummy_date = date(2000, 1, 1)

        for block in availabilities:
            current = datetime.combine(dummy_date, block.start_time)
            end = datetime.combine(dummy_date, block.end_time)

            while current + timedelta(minutes=30) <= end:
                candidate_blocks.append((current.time(), (current + timedelta(minutes=30)).time()))
                current += timedelta(minutes=30)

        candidate_blocks = sorted(list(set(candidate_blocks)), key=lambda x: x[0])
        if not candidate_blocks:
            return {"slots": [], "all_slots": []}

        # 4. Query active booked appointments for doctor on slot_date
        stmt_appts = select(Appointment).where(
            and_(
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_date == slot_date,
                Appointment.status.notin_(["cancelled", "rejected", "expired"])
            )
        )
        booked_appts = (await session.execute(stmt_appts)).scalars().all()
        now = datetime.now()

        available_slots: List[str] = []
        all_slots: List[Dict[str, Any]] = []

        for slot_start, slot_end in candidate_blocks:
            slot_start_dt = datetime.combine(slot_date, slot_start)
            slot_end_dt = datetime.combine(slot_date, slot_end)

            is_booked = False
            for appt in booked_appts:
                appt_start_dt = datetime.combine(slot_date, appt.start_time)
                appt_end_dt = datetime.combine(slot_date, appt.end_time)
                if slot_start_dt < appt_end_dt and slot_end_dt > appt_start_dt:
                    is_booked = True
                    break

            is_past = (slot_date == date.today() and slot_start_dt <= now)
            formatted_time = BookingService._format_time_slot(slot_start)

            if is_booked:
                slot_status = "booked"
                is_available = False
            elif is_past:
                slot_status = "past"
                is_available = False
            else:
                slot_status = "available"
                is_available = True
                available_slots.append(formatted_time)

            all_slots.append({
                "time": formatted_time,
                "start_time": slot_start.strftime("%H:%M:%S"),
                "end_time": slot_end.strftime("%H:%M:%S"),
                "is_available": is_available,
                "status": slot_status,
            })

        return {"slots": available_slots, "all_slots": all_slots}

    @staticmethod
    async def create_appointment(
        session: AsyncSession,
        patient_uid: str,
        data: CreateAppointmentRequest
    ) -> Appointment:
        # Enforce 5-cancellation limit server-side
        cancelled_stmt = select(func.count(Appointment.id)).where(
            and_(
                Appointment.patient_uid == patient_uid,
                Appointment.status == "cancelled"
            )
        )
        cancelled_count = (await session.execute(cancelled_stmt)).scalar() or 0
        if cancelled_count >= 5:
            raise ForbiddenException(
                "Booking restricted: You have reached the maximum limit of 5 appointment cancellations. Please contact support."
            )

        # 1. Verify profile exists
        profile_stmt = select(Profile).where(Profile.patient_uid == patient_uid)
        profile = (await session.execute(profile_stmt)).scalar_one_or_none()
        if not profile:
            raise NotFoundException("Patient profile not found. Please complete child profile first.")

        # 2. Verify doctor exists and is approved
        doctor_stmt = select(Therapist).where(Therapist.id == data.doctor_id)
        doctor = (await session.execute(doctor_stmt)).scalar_one_or_none()
        if not doctor:
            raise NotFoundException("Doctor not found")
        if doctor.status != "approved":
            raise BadRequestException("Doctor is not available for appointments")

        # 3. Verify date and times
        if data.appointment_date < date.today():
            raise BadRequestException("Cannot book appointment in the past")

        now = datetime.now()
        req_start_dt = datetime.combine(data.appointment_date, data.start_time)
        if data.appointment_date == date.today() and req_start_dt <= now:
            raise BadRequestException("Cannot book a time slot that has already passed")

        day_name = data.appointment_date.strftime("%A")
        avail_stmt = select(Availability).where(
            and_(
                Availability.doctor_id == data.doctor_id,
                Availability.day == day_name,
                Availability.is_active.is_(True),
                Availability.start_time <= data.start_time,
                Availability.end_time >= data.end_time
            )
        )
        is_available = (await session.execute(avail_stmt)).scalars().first()
        if not is_available:
            raise BadRequestException(f"Selected time is outside doctor's active availability on {day_name}")

        # 4. Check for overlapping active appointments to prevent double booking
        overlap_stmt = select(Appointment).where(
            and_(
                Appointment.doctor_id == data.doctor_id,
                Appointment.appointment_date == data.appointment_date,
                Appointment.status.notin_(["cancelled", "rejected", "expired"]),
                and_(
                    Appointment.start_time < data.end_time,
                    Appointment.end_time > data.start_time
                )
            )
        )
        existing = (await session.execute(overlap_stmt)).scalars().first()
        if existing:
            raise ConflictException("This appointment slot has already been booked.")

        # 5. Insert appointment
        patient_name = profile.child_name or profile.parent_name or "Patient"
        appointment = Appointment(
            doctor_id=data.doctor_id,
            patient_uid=patient_uid,
            patient_name=patient_name,
            appointment_date=data.appointment_date,
            start_time=data.start_time,
            end_time=data.end_time,
            status="pending"
        )
        session.add(appointment)

        # 6. Generate confirmation notification
        time_label = BookingService._format_time_slot(data.start_time)
        notification = Notification(
            patient_uid=patient_uid,
            icon="📅",
            message=f"Session booked with {doctor.full_name} for {data.appointment_date.strftime('%B %d')} at {time_label}.",
            is_read=False
        )
        session.add(notification)

        # 7. Commit with unique constraint / concurrency protection
        try:
            await session.commit()
            await session.refresh(appointment)
        except IntegrityError:
            await session.rollback()
            raise ConflictException("This appointment slot has already been booked.")

        return appointment

    @staticmethod
    async def get_my_appointments(session: AsyncSession, patient_uid: str) -> Dict[str, Any]:
        stmt = (
            select(Appointment)
            .where(Appointment.patient_uid == patient_uid)
            .order_by(desc(Appointment.appointment_date), desc(Appointment.start_time))
        )
        appts = (await session.execute(stmt)).scalars().all()
        cancellation_count = sum(1 for a in appts if a.status == "cancelled")
        is_restricted = cancellation_count >= 5

        profile = (await session.execute(
            select(Profile).where(Profile.patient_uid == patient_uid)
        )).scalar_one_or_none()

        doc_ids = list({a.doctor_id for a in appts if a.doctor_id})
        doc_map = {}
        if doc_ids:
            docs = (await session.execute(
                select(Therapist).where(Therapist.id.in_(doc_ids))
            )).scalars().all()
            for d in docs:
                doc_map[d.id] = d

        items = []
        for a in appts:
            doc = doc_map.get(a.doctor_id)
            items.append({
                "id": str(a.id),
                "appointment_date": a.appointment_date,
                "start_time": a.start_time.strftime("%H:%M:%S") if hasattr(a.start_time, "strftime") else str(a.start_time),
                "end_time": a.end_time.strftime("%H:%M:%S") if hasattr(a.end_time, "strftime") else str(a.end_time),
                "status": a.status,
                "created_at": a.created_at,
                "patient": {
                    "patient_uid": patient_uid,
                    "child_name": a.patient_name or (profile.child_name if profile else "Child"),
                    "parent_name": profile.parent_name if profile else None,
                    "age": profile.age if profile else None,
                    "phone": profile.phone if profile else None,
                },
                "doctor": {
                    "id": doc.id if doc else a.doctor_id,
                    "full_name": doc.full_name if doc else "Therapist",
                    "qualification": doc.qualification if doc else None,
                    "years_of_experience": doc.years_of_experience if doc else None,
                    "languages_spoken": doc.languages_spoken if doc else None,
                    "consultation_fee": doc.consultation_fee if doc else None,
                    "doctor_code": doc.doctor_code if doc else None,
                    "rating": doc.rating if doc else None,
                    "phone": getattr(doc, "phone", None) if doc else None,
                    "email": getattr(doc, "email", None) if doc else None,
                }
            })
        return {
            "appointments": items,
            "total_count": len(items),
            "cancellation_count": cancellation_count,
            "is_restricted": is_restricted
        }

