import secrets
import string
from datetime import date, datetime, timedelta, time
from typing import List, Optional, Dict, Any
from app.core.supabase import get_supabase
from app.core.exceptions import NotFoundException, BadRequestException, ConflictException, ForbiddenException
from app.services.progress_service import URDU_ALPHABET_SEQUENCE, get_next_alphabet

class SupabaseDbService:
    @staticmethod
    def list_daily_tips() -> List[Dict[str, Any]]:
        sb = get_supabase()
        res = sb.table("daily_tips").select("*").execute()
        tips = res.data or []
        active_tips = [t for t in tips if t.get("is_active", True) is not False]
        for idx, t in enumerate(active_tips):
            if "id" in t:
                t["id"] = str(t["id"])
            if "sort_order" not in t or t["sort_order"] is None:
                t["sort_order"] = idx + 1
            if "is_active" not in t or t["is_active"] is None:
                t["is_active"] = True
        return sorted(active_tips, key=lambda x: x.get("sort_order", 0))

    @staticmethod
    def list_therapists(status_filter: str = "approved", limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        sb = get_supabase()
        res = (
            sb.table("therapists")
            .select("*")
            .eq("status", status_filter)
            .order("rating", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return res.data or []

    @staticmethod
    def get_therapist_by_code(code: str) -> Dict[str, Any]:
        sb = get_supabase()
        cleaned_code = code.strip().upper()
        res = (
            sb.table("therapists")
            .select("*")
            .eq("doctor_code", cleaned_code)
            .eq("status", "approved")
            .execute()
        )
        if not res.data:
            raise NotFoundException("No approved doctor found with that code.")
        return res.data[0]

    @staticmethod
    def get_therapist_by_id(doctor_id: str) -> Dict[str, Any]:
        sb = get_supabase()
        res = sb.table("therapists").select("*").eq("id", doctor_id).execute()
        if not res.data:
            raise NotFoundException("Doctor not found")
        return res.data[0]

    @staticmethod
    def request_therapist_registration(current_uid: str, doctor_id: str) -> Dict[str, Any]:
        sb = get_supabase()
        # 1. Fetch patient profile
        prof_res = sb.table("profiles").select("*").eq("patient_uid", current_uid).execute()
        if not prof_res.data:
            raise NotFoundException("Please complete your child's profile before requesting a doctor.")
        profile = prof_res.data[0]

        # 2. Check doctor exists and is approved
        doc_res = sb.table("therapists").select("*").eq("id", doctor_id).execute()
        if not doc_res.data:
            raise NotFoundException("Doctor not found")
        if doc_res.data[0].get("status") != "approved":
            raise BadRequestException("Cannot request an unapproved doctor")

        # 3. Rule 1, 2, 4: Enforce that a patient can have only ONE active doctor.
        # If already registered with ANY doctor, reject immediately.
        active_link = sb.table("patients").select("*").eq("patient_uid", current_uid).execute()
        if active_link.data:
            cur_doc_id = active_link.data[0].get("doctor_id")
            cur_doc_name = "your current doctor"
            try:
                cur_doc = sb.table("therapists").select("full_name").eq("id", cur_doc_id).execute()
                if cur_doc.data and cur_doc.data[0].get("full_name"):
                    cur_doc_name = f"Dr. {cur_doc.data[0].get('full_name')}"
            except Exception:
                pass
            raise ConflictException(
                f"You are already registered with {cur_doc_name}. You must first unregister from your current doctor before requesting another doctor."
            )

        # 4. Rule 5: Prevent duplicate or parallel doctor requests.
        # A patient can only have ONE pending request at a time across the entire system.
        existing_pending = (
            sb.table("patient_requests")
            .select("*")
            .eq("patient_uid", current_uid)
            .eq("status", "pending")
            .execute()
        )
        if existing_pending.data:
            pending_doc_id = existing_pending.data[0].get("doctor_id")
            if pending_doc_id == doctor_id:
                raise ConflictException("You already have a pending registration request with this doctor.")
            else:
                pending_doc_name = "another doctor"
                try:
                    pdoc = sb.table("therapists").select("full_name").eq("id", pending_doc_id).execute()
                    if pdoc.data and pdoc.data[0].get("full_name"):
                        pending_doc_name = f"Dr. {pdoc.data[0].get('full_name')}"
                except Exception:
                    pass
                raise ConflictException(
                    f"You already have a pending registration request with {pending_doc_name}. You can only request one doctor at a time. Please wait for a response or unregister/cancel it first."
                )

        # 5. Insert request
        child_name = profile.get("child_name") or profile.get("parent_name") or "Child"
        parent_email = None
        try:
            user_res = sb.table("users").select("email").eq("id", current_uid).execute()
            if user_res.data:
                parent_email = user_res.data[0].get("email")
        except Exception:
            pass

        phone_val = profile.get("phone")
        age_val = profile.get("age")
        if not phone_val or age_val is None:
            try:
                p_res = sb.table("patients").select("phone, age").eq("patient_uid", current_uid).execute()
                if p_res.data:
                    if not phone_val:
                        phone_val = p_res.data[0].get("phone")
                    if age_val is None:
                        age_val = p_res.data[0].get("age")
            except Exception:
                pass

        insert_res = sb.table("patient_requests").insert({
            "doctor_id": doctor_id,
            "patient_uid": current_uid,
            "patient_name": child_name,
            "parent_email": parent_email,
            "phone": phone_val,
            "age": age_val,
            "status": "pending"
        }).execute()
        return insert_res.data[0]

    @staticmethod
    def get_my_doctor_status(current_uid: str) -> Dict[str, Any]:
        sb = get_supabase()
        # 1. Check patients table for active linked doctor
        patient_link = sb.table("patients").select("*").eq("patient_uid", current_uid).execute()
        if patient_link.data:
            doc_id = patient_link.data[0].get("doctor_id")
            doc = sb.table("therapists").select("*").eq("id", doc_id).execute()
            if doc.data:
                return {
                    "status": "approved",
                    "doctor": doc.data[0],
                    "request": None
                }

        # 2. Check if a doctor has accepted the request (synchronization guarantee)
        accepted_req = (
            sb.table("patient_requests")
            .select("*")
            .eq("patient_uid", current_uid)
            .eq("status", "accepted")
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        if accepted_req.data:
            req = accepted_req.data[0]
            doc_id = req.get("doctor_id")
            # Ensure patients table row exists and profile is synced
            try:
                sb.table("patients").insert({
                    "doctor_id": doc_id,
                    "patient_uid": current_uid,
                    "name": req.get("patient_name") or "Child",
                    "phone": req.get("phone"),
                    "age": req.get("age"),
                    "parent_email": req.get("parent_email"),
                }).execute()
            except Exception:
                pass
            try:
                sb.table("profiles").update({"doctor_uid": doc_id}).eq("patient_uid", current_uid).execute()
            except Exception:
                pass
            doc = sb.table("therapists").select("*").eq("id", doc_id).execute()
            if doc.data:
                return {
                    "status": "approved",
                    "doctor": doc.data[0],
                    "request": None
                }

        # 3. Check pending requests
        pending = (
            sb.table("patient_requests")
            .select("*")
            .eq("patient_uid", current_uid)
            .eq("status", "pending")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if pending.data:
            return {
                "status": "pending",
                "doctor": None,
                "request": pending.data[0]
            }

        return {"status": "none", "doctor": None, "request": None}

    @staticmethod
    def unregister_my_doctor(current_uid: str) -> None:
        sb = get_supabase()
        # 1. Remove all records for this patient from patients table
        sb.table("patients").delete().eq("patient_uid", current_uid).execute()
        # 2. Remove / clear all requests for this patient from patient_requests table
        sb.table("patient_requests").delete().eq("patient_uid", current_uid).execute()
        # 3. Clear doctor_uid reference from profile
        try:
            sb.table("profiles").update({"doctor_uid": None}).eq("patient_uid", current_uid).execute()
        except Exception:
            pass
        # 4. Insert in-app notification confirming unregistration
        try:
            sb.table("notifications").insert({
                "patient_uid": current_uid,
                "icon": "ℹ️",
                "message": "You have unregistered from your doctor. You can now choose and register with another doctor.",
                "is_read": False
            }).execute()
        except Exception:
            pass

    @staticmethod
    def accept_patient_request(request_id: str) -> Dict[str, Any]:
        sb = get_supabase()
        req_res = sb.table("patient_requests").select("*").eq("id", request_id).execute()
        if not req_res.data:
            raise NotFoundException("Patient registration request not found.")
        req = req_res.data[0]
        patient_uid = req.get("patient_uid")
        doctor_id = req.get("doctor_id")

        if not patient_uid or not doctor_id:
            raise BadRequestException("Invalid request data: missing patient_uid or doctor_id.")

        # Rule 1 & 12: Race condition protection — check if patient is already active with another doctor
        existing_patient = sb.table("patients").select("*").eq("patient_uid", patient_uid).execute()
        if existing_patient.data:
            active_doc_id = existing_patient.data[0].get("doctor_id")
            if active_doc_id != doctor_id:
                raise ConflictException("This patient is already registered with another active doctor.")

        # Mark request as accepted
        now_str = datetime.now(timezone.utc).isoformat()
        sb.table("patient_requests").update({
            "status": "accepted",
            "updated_at": now_str
        }).eq("id", request_id).execute()

        # Link patient in patients table (ensuring single active doctor)
        if not existing_patient.data:
            try:
                sb.table("patients").insert({
                    "doctor_id": doctor_id,
                    "patient_uid": patient_uid,
                    "name": req.get("patient_name") or "Child",
                    "phone": req.get("phone"),
                    "age": req.get("age"),
                    "parent_email": req.get("parent_email"),
                }).execute()
            except Exception as e:
                logger.warning(f"Error inserting into patients table during accept: {e}")

        # Update profile table doctor_uid
        try:
            sb.table("profiles").update({"doctor_uid": doctor_id}).eq("patient_uid", patient_uid).execute()
        except Exception:
            pass

        # Reject any other pending requests for this patient (Rule 1 & 5)
        try:
            sb.table("patient_requests").update({
                "status": "rejected",
                "updated_at": now_str
            }).eq("patient_uid", patient_uid).eq("status", "pending").execute()
        except Exception:
            pass

        # Fetch doctor name for notification
        doc_name = "Your therapist"
        try:
            doc_res = sb.table("therapists").select("full_name").eq("id", doctor_id).execute()
            if doc_res.data and doc_res.data[0].get("full_name"):
                doc_name = f"Dr. {doc_res.data[0].get('full_name')}"
        except Exception:
            pass

        # Insert immediate in-app notification for patient (Rule 7)
        try:
            sb.table("notifications").insert({
                "patient_uid": patient_uid,
                "icon": "👨‍⚕️",
                "message": f"{doc_name} has accepted your registration request! You are now connected.",
                "is_read": False
            }).execute()
        except Exception as e:
            logger.warning(f"Failed to create in-app notification on request acceptance: {e}")

        return {
            "success": True,
            "message": f"Registration request accepted. Patient is now linked with {doc_name}.",
            "request_id": request_id,
            "doctor_id": doctor_id,
            "patient_uid": patient_uid,
            "status": "accepted"
        }

    @staticmethod
    def reject_patient_request(request_id: str) -> Dict[str, Any]:
        sb = get_supabase()
        req_res = sb.table("patient_requests").select("*").eq("id", request_id).execute()
        if not req_res.data:
            raise NotFoundException("Patient registration request not found.")
        req = req_res.data[0]
        patient_uid = req.get("patient_uid")
        doctor_id = req.get("doctor_id")

        now_str = datetime.now(timezone.utc).isoformat()
        sb.table("patient_requests").update({
            "status": "rejected",
            "updated_at": now_str
        }).eq("id", request_id).execute()

        doc_name = "Your therapist"
        try:
            doc_res = sb.table("therapists").select("full_name").eq("id", doctor_id).execute()
            if doc_res.data and doc_res.data[0].get("full_name"):
                doc_name = f"Dr. {doc_res.data[0].get('full_name')}"
        except Exception:
            pass

        try:
            if patient_uid:
                sb.table("notifications").insert({
                    "patient_uid": patient_uid,
                    "icon": "❌",
                    "message": f"Your registration request with {doc_name} was declined.",
                    "is_read": False
                }).execute()
        except Exception:
            pass

        return {
            "success": True,
            "message": "Registration request rejected.",
            "request_id": request_id,
            "status": "rejected"
        }

    @staticmethod
    def _parse_time(val: Any) -> time:
        if isinstance(val, time):
            return val
        s = str(val).split("+")[0].split(".")[0].strip()
        parts = [int(p) for p in s.split(":")[:3]]
        if len(parts) == 1:
            return time(parts[0], 0)
        elif len(parts) == 2:
            return time(parts[0], parts[1])
        else:
            return time(parts[0], parts[1], parts[2])

    @staticmethod
    def _format_time_slot(t: time) -> str:
        dummy = datetime.combine(date(2000, 1, 1), t)
        formatted = dummy.strftime("%I:%M %p")
        if formatted.startswith("0"):
            return formatted[1:]
        return formatted

    @staticmethod
    def get_doctor_available_slots(doctor_id: str, slot_date: date) -> Dict[str, Any]:
        if slot_date < date.today():
            return {"slots": [], "all_slots": []}

        sb = get_supabase()
        doc_res = sb.table("therapists").select("*").eq("id", doctor_id).execute()
        if not doc_res.data:
            raise NotFoundException("Doctor not found")
        if doc_res.data[0].get("status") != "approved":
            raise BadRequestException("Doctor is not currently approved for bookings")

        day_name = slot_date.strftime("%A")
        avail_res = (
            sb.table("availability")
            .select("*")
            .eq("doctor_id", doctor_id)
            .eq("day", day_name)
            .eq("is_active", True)
            .execute()
        )
        if not avail_res.data:
            return {"slots": [], "all_slots": []}

        # Generate 30-min candidate slots from doctor's active recurring schedule
        candidate_blocks = []
        for block in avail_res.data:
            b_start = SupabaseDbService._parse_time(block["start_time"])
            b_end = SupabaseDbService._parse_time(block["end_time"])
            curr = datetime.combine(slot_date, b_start)
            end_dt = datetime.combine(slot_date, b_end)
            while curr + timedelta(minutes=30) <= end_dt:
                slot_start = curr.time()
                slot_end = (curr + timedelta(minutes=30)).time()
                candidate_blocks.append((slot_start, slot_end))
                curr += timedelta(minutes=30)

        candidate_blocks = sorted(list(set(candidate_blocks)), key=lambda x: x[0])
        if not candidate_blocks:
            return {"slots": [], "all_slots": []}

        # Check existing appointments for this doctor on this specific date
        app_res = (
            sb.table("appointments")
            .select("id, start_time, end_time, status")
            .eq("doctor_id", doctor_id)
            .eq("appointment_date", str(slot_date))
            .execute()
        )
        # Blocked if status is pending, confirmed, booked, completed (any active booking)
        INACTIVE_STATUSES = {"cancelled", "rejected", "expired"}
        active_appts = []
        for a in (app_res.data or []):
            if a.get("status") not in INACTIVE_STATUSES:
                a_start = SupabaseDbService._parse_time(a["start_time"])
                if a.get("end_time"):
                    a_end = SupabaseDbService._parse_time(a["end_time"])
                else:
                    a_end = (datetime.combine(slot_date, a_start) + timedelta(minutes=30)).time()
                active_appts.append((a_start, a_end))

        now = datetime.now()
        available_slots: List[str] = []
        all_slots: List[Dict[str, Any]] = []

        for slot_start, slot_end in candidate_blocks:
            slot_start_dt = datetime.combine(slot_date, slot_start)
            slot_end_dt = datetime.combine(slot_date, slot_end)

            # Check overlap against any active appointment
            is_booked = False
            for a_start, a_end in active_appts:
                a_start_dt = datetime.combine(slot_date, a_start)
                a_end_dt = datetime.combine(slot_date, a_end)
                if slot_start_dt < a_end_dt and slot_end_dt > a_start_dt:
                    is_booked = True
                    break

            is_past = (slot_date == date.today() and slot_start_dt <= now)
            formatted_time = SupabaseDbService._format_time_slot(slot_start)

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
    def book_appointment(current_uid: str, doctor_id: str, appointment_date: date, start_time: time, end_time: time) -> Dict[str, Any]:
        if appointment_date < date.today():
            raise BadRequestException("Cannot book appointments in the past.")

        now = datetime.now()
        req_start_dt = datetime.combine(appointment_date, start_time)
        req_end_dt = datetime.combine(appointment_date, end_time)

        if appointment_date == date.today() and req_start_dt <= now:
            raise BadRequestException("Cannot book a time slot that has already passed.")

        if start_time >= end_time:
            raise BadRequestException("end_time must be strictly after start_time.")

        sb = get_supabase()

        # Enforce 5-cancellation limit server-side
        cancellation_check = (
            sb.table("appointments")
            .select("id")
            .eq("patient_uid", current_uid)
            .eq("status", "cancelled")
            .execute()
        )
        cancellation_count = len(cancellation_check.data or [])
        if cancellation_count >= 5:
            raise ForbiddenException(
                "Booking restricted: You have reached the maximum limit of 5 appointment cancellations. Please contact support."
            )

        # 1. Check doctor
        doc_res = sb.table("therapists").select("*").eq("id", doctor_id).execute()
        if not doc_res.data or doc_res.data[0].get("status") != "approved":
            raise BadRequestException("Doctor not available for bookings.")

        # 2. Check doctor's recurring working schedule (never mutate availability table)
        day_name = appointment_date.strftime("%A")
        avail_res = (
            sb.table("availability")
            .select("*")
            .eq("doctor_id", doctor_id)
            .eq("day", day_name)
            .eq("is_active", True)
            .execute()
        )
        if not avail_res.data:
            raise BadRequestException(f"Doctor does not have active working hours on {day_name}.")

        within_schedule = False
        for block in avail_res.data:
            b_start = SupabaseDbService._parse_time(block["start_time"])
            b_end = SupabaseDbService._parse_time(block["end_time"])
            if b_start <= start_time and b_end >= end_time:
                within_schedule = True
                break
        if not within_schedule:
            raise BadRequestException(f"Selected time is outside doctor's active availability on {day_name}.")

        # 3. Check existing active appointments to prevent double booking
        app_res = (
            sb.table("appointments")
            .select("id, start_time, end_time, status")
            .eq("doctor_id", doctor_id)
            .eq("appointment_date", str(appointment_date))
            .execute()
        )
        INACTIVE_STATUSES = {"cancelled", "rejected", "expired"}
        for a in (app_res.data or []):
            if a.get("status") in INACTIVE_STATUSES:
                continue
            a_start = SupabaseDbService._parse_time(a["start_time"])
            if a.get("end_time"):
                a_end = SupabaseDbService._parse_time(a["end_time"])
            else:
                a_end = (datetime.combine(appointment_date, a_start) + timedelta(minutes=30)).time()
            a_start_dt = datetime.combine(appointment_date, a_start)
            a_end_dt = datetime.combine(appointment_date, a_end)
            if req_start_dt < a_end_dt and req_end_dt > a_start_dt:
                raise ConflictException("This appointment slot has already been booked.")

        # 4. Fetch patient profile name
        prof_res = sb.table("profiles").select("child_name, parent_name").eq("patient_uid", current_uid).execute()
        patient_name = "Patient"
        if prof_res.data:
            patient_name = prof_res.data[0].get("child_name") or prof_res.data[0].get("parent_name") or "Patient"

        # 5. Insert appointment with database unique constraint enforcement against race conditions
        try:
            ins_res = sb.table("appointments").insert({
                "doctor_id": doctor_id,
                "patient_uid": current_uid,
                "patient_name": patient_name,
                "appointment_date": str(appointment_date),
                "start_time": str(start_time),
                "end_time": str(end_time),
                "status": "pending"
            }).execute()
        except Exception as e:
            err_str = str(e).lower()
            if "duplicate" in err_str or "unique" in err_str or "23505" in err_str or "conflict" in err_str:
                raise ConflictException("This appointment slot has already been booked.")
            raise

        if not ins_res.data:
            raise BadRequestException("Failed to create appointment.")

        appointment = ins_res.data[0]

        # 6. Insert notification for patient
        try:
            sb.table("notifications").insert({
                "patient_uid": current_uid,
                "icon": "⏳",
                "message": f"Appointment request sent to {doc_res.data[0].get('full_name')} for {appointment_date} at {start_time} (Pending therapist confirmation).",
                "is_read": False
            }).execute()
        except Exception:
            pass

        return appointment

    @staticmethod
    def update_appointment_status(appointment_id: str, new_status: str, patient_uid: Optional[str] = None) -> Dict[str, Any]:
        sb = get_supabase()
        existing = sb.table("appointments").select("*").eq("id", appointment_id).execute()
        if not existing.data:
            raise NotFoundException("Appointment not found")

        appt = existing.data[0]

        # Ownership: a patient may only update their own appointment.
        if patient_uid is not None and appt.get("patient_uid") != patient_uid:
            raise ForbiddenException("You do not have access to this appointment.")

        if appt.get("status") == "cancelled" and new_status == "cancelled":
            raise BadRequestException("Appointment is already cancelled.")

        upd = sb.table("appointments").update({
            "status": new_status,
        }).eq("id", appointment_id).execute()

        # Send notification to patient when therapist confirms or cancels
        try:
            doc = sb.table("therapists").select("full_name").eq("id", appt.get("doctor_id")).execute()
            doc_name = doc.data[0].get("full_name") if doc.data else "Therapist"
            if new_status == "confirmed":
                sb.table("notifications").insert({
                    "patient_uid": appt.get("patient_uid"),
                    "icon": "✅",
                    "message": f"Good news! Your appointment with {doc_name} on {appt.get('appointment_date')} at {appt.get('start_time')} has been accepted.",
                    "is_read": False
                }).execute()
            elif new_status == "cancelled":
                sb.table("notifications").insert({
                    "patient_uid": appt.get("patient_uid"),
                    "icon": "❌",
                    "message": f"Your appointment with {doc_name} on {appt.get('appointment_date')} at {appt.get('start_time')} was cancelled.",
                    "is_read": False
                }).execute()
        except Exception:
            pass

        return upd.data[0]

    @staticmethod
    def get_my_appointments(current_uid: str) -> Dict[str, Any]:
        sb = get_supabase()
        # 1. Fetch appointments for patient
        appts_res = (
            sb.table("appointments")
            .select("*")
            .eq("patient_uid", current_uid)
            .order("appointment_date", desc=True)
            .order("start_time", desc=True)
            .execute()
        )
        appts = appts_res.data or []

        # 2. Count cancellations to derive restriction
        cancellation_count = sum(1 for a in appts if a.get("status") == "cancelled")
        is_restricted = cancellation_count >= 5

        # 3. Fetch patient profile
        prof_res = sb.table("profiles").select("*").eq("patient_uid", current_uid).execute()
        profile_data = prof_res.data[0] if prof_res.data else {}

        # 4. Fetch therapist info for all referenced doctors
        doc_ids = list({a["doctor_id"] for a in appts if a.get("doctor_id")})
        doc_map = {}
        if doc_ids:
            docs_res = sb.table("therapists").select("*").in_("id", doc_ids).execute()
            for d in (docs_res.data or []):
                doc_map[d["id"]] = d

        # 5. Build enriched appointment list
        items = []
        for a in appts:
            doc = doc_map.get(a.get("doctor_id"), {})
            items.append({
                "id": str(a.get("id")),
                "appointment_date": a.get("appointment_date"),
                "start_time": str(a.get("start_time")),
                "end_time": str(a.get("end_time")),
                "status": a.get("status", "pending"),
                "created_at": a.get("created_at"),
                "patient": {
                    "patient_uid": current_uid,
                    "child_name": a.get("patient_name") or profile_data.get("child_name") or "Child",
                    "parent_name": profile_data.get("parent_name"),
                    "age": profile_data.get("age"),
                    "phone": profile_data.get("phone"),
                },
                "doctor": {
                    "id": doc.get("id") or a.get("doctor_id"),
                    "full_name": doc.get("full_name") or "Therapist",
                    "qualification": doc.get("qualification"),
                    "years_of_experience": doc.get("years_of_experience"),
                    "languages_spoken": doc.get("languages_spoken"),
                    "consultation_fee": doc.get("consultation_fee"),
                    "doctor_code": doc.get("doctor_code"),
                    "rating": doc.get("rating"),
                }
            })

        return {
            "appointments": items,
            "total_count": len(items),
            "cancellation_count": cancellation_count,
            "is_restricted": is_restricted
        }

    @staticmethod
    def get_my_rating(current_uid: str, doctor_id: str) -> Optional[int]:
        sb = get_supabase()
        try:
            res = (
                sb.table("ratings")
                .select("rating")
                .eq("doctor_id", doctor_id)
                .eq("patient_uid", current_uid)
                .execute()
            )
            if res.data:
                return res.data[0].get("rating")
        except Exception:
            pass
        return None

    @staticmethod
    def submit_rating(current_uid: str, doctor_id: str, stars: int) -> Dict[str, Any]:
        if stars < 1 or stars > 5:
            raise BadRequestException("Rating must be between 1 and 5 stars.")

        sb = get_supabase()
        doc = sb.table("therapists").select("id").eq("id", doctor_id).execute()
        if not doc.data:
            raise NotFoundException("Doctor not found")

        # Upsert rating if ratings table exists in Supabase
        try:
            existing = (
                sb.table("ratings")
                .select("id")
                .eq("doctor_id", doctor_id)
                .eq("patient_uid", current_uid)
                .execute()
            )
            if existing.data:
                sb.table("ratings").update({"rating": stars}).eq("id", existing.data[0]["id"]).execute()
            else:
                sb.table("ratings").insert({
                    "doctor_id": doctor_id,
                    "patient_uid": current_uid,
                    "rating": stars
                }).execute()

            # Recalculate average
            all_ratings = sb.table("ratings").select("rating").eq("doctor_id", doctor_id).execute()
            if all_ratings.data:
                vals = [r["rating"] for r in all_ratings.data]
                avg = round(sum(vals) / len(vals), 1)
                sb.table("therapists").update({"rating": avg}).eq("id", doctor_id).execute()
        except Exception:
            # Fallback: directly update doctor rating
            try:
                sb.table("therapists").update({"rating": float(stars)}).eq("id", doctor_id).execute()
            except Exception:
                pass

        return {"doctor_id": doctor_id, "rating": stars}

    @staticmethod
    def get_profile(current_uid: str) -> Optional[Dict[str, Any]]:
        sb = get_supabase()
        prof_res = sb.table("profiles").select("*").eq("patient_uid", current_uid).execute()
        if not prof_res.data:
            return None

        profile = prof_res.data[0]
        focus_res = sb.table("focus_sound").select("*").eq("patient_uid", current_uid).execute()
        if not focus_res.data:
            # Initialize baseline focus sound
            first_sound = URDU_ALPHABET_SEQUENCE[0]
            try:
                sb.table("focus_sound").insert({
                    "patient_uid": current_uid,
                    "sound": first_sound["letter"],
                    "alphabet_name": first_sound["name"],
                    "progress": 0.0
                }).execute()
                focus_res = sb.table("focus_sound").select("*").eq("patient_uid", current_uid).execute()
            except Exception:
                pass

        focus = focus_res.data[0] if focus_res.data else None

        phone_val = profile.get("phone")
        age_val = profile.get("age")
        if not phone_val or age_val is None:
            try:
                p_res = sb.table("patients").select("phone, age").eq("patient_uid", current_uid).execute()
                if p_res.data:
                    if not phone_val and p_res.data[0].get("phone"):
                        phone_val = p_res.data[0].get("phone")
                    if age_val is None and p_res.data[0].get("age") is not None:
                        age_val = p_res.data[0].get("age")
            except Exception:
                pass

        return {
            "patient_uid": profile["patient_uid"],
            "parent_name": profile.get("parent_name"),
            "child_name": profile.get("child_name"),
            "phone": phone_val,
            "age": age_val,
            "sound": focus.get("sound") if focus else None,
            "alphabet_name": focus.get("alphabet_name") if focus else None,
            "focus_progress": float(focus.get("progress") or 0.0) if focus else 0.0,
            "focus_sound": focus,
            "created_at": profile.get("created_at"),
            "updated_at": focus.get("updated_at") if focus else profile.get("created_at")
        }

    @staticmethod
    def save_profile(
        current_uid: str,
        parent_name: str,
        child_name: str,
        phone: Optional[str] = None,
        sound: Optional[str] = None,
        alphabet_name: Optional[str] = None,
        age: Optional[int] = None
    ) -> Dict[str, Any]:
        sb = get_supabase()

        # Check existing profile
        existing_prof = sb.table("profiles").select("*").eq("patient_uid", current_uid).execute()
        existing_data = existing_prof.data[0] if existing_prof.data else {}

        # Check compulsory phone
        final_phone = phone.strip() if phone and phone.strip() else existing_data.get("phone")
        if not final_phone:
            raise BadRequestException("Phone number is compulsory and cannot be blank.")
        final_age = age if age is not None else existing_data.get("age")

        prof_data = {
            "patient_uid": current_uid,
            "parent_name": parent_name.strip(),
            "child_name": child_name.strip(),
            "phone": final_phone,
        }
        if final_age is not None:
            prof_data["age"] = final_age

        try:
            if existing_prof.data:
                sb.table("profiles").update(prof_data).eq("patient_uid", current_uid).execute()
            else:
                sb.table("profiles").insert(prof_data).execute()
        except Exception as e:
            # If Supabase table does not yet have 'age' column, retry without 'age' in profiles
            if "age" in str(e):
                prof_data.pop("age", None)
                if existing_prof.data:
                    sb.table("profiles").update(prof_data).eq("patient_uid", current_uid).execute()
                else:
                    sb.table("profiles").insert(prof_data).execute()
            else:
                raise e

        # Also sync phone and age to patients table if linked
        patient_sync = {}
        if final_phone:
            patient_sync["phone"] = final_phone
        if final_age is not None:
            patient_sync["age"] = final_age
        if patient_sync:
            try:
                sb.table("patients").update(patient_sync).eq("patient_uid", current_uid).execute()
            except Exception:
                pass

        # Update or insert focus sound
        existing_focus = sb.table("focus_sound").select("id").eq("patient_uid", current_uid).execute()
        if sound and alphabet_name:
            focus_payload = {
                "patient_uid": current_uid,
                "sound": sound.strip(),
                "alphabet_name": alphabet_name.strip(),
                "progress": 0.0
            }
            if existing_focus.data:
                sb.table("focus_sound").update(focus_payload).eq("patient_uid", current_uid).execute()
            else:
                sb.table("focus_sound").insert(focus_payload).execute()
        elif not existing_focus.data:
            first_sound = URDU_ALPHABET_SEQUENCE[0]
            sb.table("focus_sound").insert({
                "patient_uid": current_uid,
                "sound": first_sound["letter"],
                "alphabet_name": first_sound["name"],
                "progress": 0.0
            }).execute()

        return SupabaseDbService.get_profile(current_uid)

    @staticmethod
    def delete_profile(current_uid: str) -> None:
        sb = get_supabase()
        sb.table("attempts").delete().eq("patient_uid", current_uid).execute()
        sb.table("notifications").delete().eq("patient_uid", current_uid).execute()
        sb.table("focus_sound").delete().eq("patient_uid", current_uid).execute()
        sb.table("patient_requests").delete().eq("patient_uid", current_uid).execute()
        sb.table("patients").delete().eq("patient_uid", current_uid).execute()
        sb.table("profiles").delete().eq("patient_uid", current_uid).execute()

    @staticmethod
    def record_attempt(current_uid: str, item_id: str, alphabet_name: str, level_key: str, score: int) -> Dict[str, Any]:
        sb = get_supabase()
        # 1. Insert attempt
        ins_res = sb.table("attempts").insert({
            "patient_uid": current_uid,
            "item_id": item_id,
            "alphabet_name": alphabet_name,
            "level_key": level_key,
            "score": score
        }).execute()
        attempt_record = dict(ins_res.data[0])
        if not attempt_record.get("attempted_at"):
            attempt_record["attempted_at"] = attempt_record.get("created_at") or datetime.now().isoformat()

        # 2. Score notification if >= 70
        if score >= 70:
            try:
                sb.table("notifications").insert({
                    "patient_uid": current_uid,
                    "icon": "🏆",
                    "message": f"Nice work! Score: {score}%",
                    "is_read": False
                }).execute()
            except Exception:
                pass

        # 3. Check focus sound progression
        focus_res = sb.table("focus_sound").select("*").eq("patient_uid", current_uid).execute()
        new_progress = 0.0
        advanced = False
        next_sound = None

        if focus_res.data:
            curr_focus = focus_res.data[0]
            if curr_focus.get("alphabet_name") == alphabet_name:
                # Calculate overall completion across levels
                history = sb.table("attempts").select("*").eq("patient_uid", current_uid).eq("alphabet_name", alphabet_name).execute()
                levels = set()
                for h in history.data or []:
                    if h.get("score", 0) >= 70:
                        levels.add(h.get("level_key"))

                # 5 levels total: letter, word, sentence, poem, story
                num_passed = len(levels)
                new_progress = min(1.0, round(num_passed / 5.0, 2))

                if new_progress >= 1.0:
                    next_item = get_next_alphabet(alphabet_name)
                    if next_item:
                        advanced = True
                        next_sound = next_item["letter"]
                        sb.table("focus_sound").update({
                            "sound": next_item["letter"],
                            "alphabet_name": next_item["name"],
                            "progress": 0.0
                        }).eq("patient_uid", current_uid).execute()

                        sb.table("notifications").insert({
                            "patient_uid": current_uid,
                            "icon": "🎉",
                            "message": f"Sound '{curr_focus.get('sound')}' fully mastered! Moving on to '{next_item['letter']}'.",
                            "is_read": False
                        }).execute()
                else:
                    sb.table("focus_sound").update({"progress": new_progress}).eq("patient_uid", current_uid).execute()

        return {
            "attempt": attempt_record,
            "milestone_notification": f"Nice work! Score: {score}%" if score >= 70 else None,
            "sound_mastered": advanced,
            "next_sound": next_sound,
            "focus_progress": new_progress
        }

    @staticmethod
    def get_attempt_history(
        current_uid: str,
        alphabet_name: Optional[str] = None,
        level_key: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        sb = get_supabase()
        query = sb.table("attempts").select("*").eq("patient_uid", current_uid)
        if alphabet_name:
            query = query.eq("alphabet_name", alphabet_name)
        if level_key:
            query = query.eq("level_key", level_key)
        res = query.order("attempted_at", desc=True).range(offset, offset + limit - 1).execute()
        return res.data or []

    @staticmethod
    def get_notifications(current_uid: str) -> List[Dict[str, Any]]:
        sb = get_supabase()
        res = sb.table("notifications").select("*").eq("patient_uid", current_uid).order("created_at", desc=True).execute()
        return res.data or []

    @staticmethod
    def get_unread_count(current_uid: str) -> int:
        sb = get_supabase()
        res = sb.table("notifications").select("id", count="exact").eq("patient_uid", current_uid).eq("is_read", False).execute()
        return res.count or 0

    @staticmethod
    def mark_notifications_read(current_uid: str) -> None:
        sb = get_supabase()
        sb.table("notifications").update({"is_read": True}).eq("patient_uid", current_uid).eq("is_read", False).execute()

    @staticmethod
    def clear_notifications(current_uid: str) -> None:
        sb = get_supabase()
        sb.table("notifications").delete().eq("patient_uid", current_uid).execute()

    @staticmethod
    def create_patient(
        current_uid: str,
        doctor_id: str,
        name: str,
        age: int,
        phone: str,
        parent_email: str,
        accuracy: float = 0.0
    ) -> Dict[str, Any]:
        sb = get_supabase()

        # 1. Validate doctor exists and is approved
        doc_res = sb.table("therapists").select("*").eq("id", doctor_id).execute()
        if not doc_res.data:
            raise NotFoundException("Doctor not found")
        if doc_res.data[0].get("status") != "approved":
            raise BadRequestException("Cannot register with an unapproved doctor")

        doctor = doc_res.data[0]

        # 2. Check if already linked with this doctor or another
        existing = sb.table("patients").select("*").eq("patient_uid", current_uid).execute()
        if existing.data:
            raise ConflictException("Patient is already registered with a therapist. Unlink first or use update.")

        # 3. Insert into patients table with strict foreign key reference to patient_uid and doctor_id
        patient_payload: Dict[str, Any] = {
            "doctor_id": doctor_id,
            "patient_uid": current_uid,
            "name": name.strip(),
            "age": int(age),
            "phone": phone.strip(),
            "parent_email": parent_email.strip().lower(),
        }
        try:
            ins_res = sb.table("patients").insert(patient_payload).execute()
        except Exception as e:
            if "accuracy" in str(e).lower() and accuracy is not None:
                patient_payload["accuracy"] = int(round(float(accuracy)))
                ins_res = sb.table("patients").insert(patient_payload).execute()
            else:
                raise
        if not ins_res.data:
            raise BadRequestException("Failed to create patient record")

        patient_record = ins_res.data[0]

        # 4. Sync profile table reference (doctor_uid, child_name, phone, age)
        try:
            prof_sync = {
                "doctor_uid": doctor_id,
                "child_name": name.strip(),
            }
            if phone:
                prof_sync["phone"] = phone.strip()
            if age is not None:
                prof_sync["age"] = int(age)
            try:
                sb.table("profiles").update(prof_sync).eq("patient_uid", current_uid).execute()
            except Exception as e:
                if "age" in str(e):
                    prof_sync.pop("age", None)
                    sb.table("profiles").update(prof_sync).eq("patient_uid", current_uid).execute()
                else:
                    pass
        except Exception:
            pass

        # 5. Clean up pending request if any
        try:
            sb.table("patient_requests").delete().eq("patient_uid", current_uid).eq("doctor_id", doctor_id).execute()
        except Exception:
            pass

        patient_record["doctor"] = doctor
        return patient_record

    @staticmethod
    def get_patient_me(current_uid: str) -> Dict[str, Any]:
        sb = get_supabase()
        res = sb.table("patients").select("*").eq("patient_uid", current_uid).execute()
        if not res.data:
            raise NotFoundException("Patient record not found. You are not currently registered with a therapist.")

        patient_record = res.data[0]
        # Attach doctor reference
        doc_res = sb.table("therapists").select("*").eq("id", patient_record.get("doctor_id")).execute()
        patient_record["doctor"] = doc_res.data[0] if doc_res.data else None
        return patient_record

    @staticmethod
    def update_patient_me(
        current_uid: str,
        doctor_id: str,
        name: str,
        age: int,
        phone: str,
        parent_email: str,
        accuracy: Optional[float] = None
    ) -> Dict[str, Any]:
        sb = get_supabase()
        existing = sb.table("patients").select("*").eq("patient_uid", current_uid).execute()
        if not existing.data:
            raise NotFoundException("Patient record not found. You must create one first.")

        # Validate doctor exists and is approved
        doc_res = sb.table("therapists").select("*").eq("id", doctor_id).execute()
        if not doc_res.data:
            raise NotFoundException("Doctor not found")
        if doc_res.data[0].get("status") != "approved":
            raise BadRequestException("Cannot register with an unapproved doctor")

        doctor = doc_res.data[0]

        update_payload: Dict[str, Any] = {
            "doctor_id": doctor_id,
            "name": name.strip(),
            "age": int(age),
            "phone": phone.strip(),
            "parent_email": parent_email.strip().lower(),
        }
        try:
            upd_res = sb.table("patients").update(update_payload).eq("patient_uid", current_uid).execute()
        except Exception as e:
            if "accuracy" in str(e).lower() and accuracy is not None:
                update_payload["accuracy"] = int(round(float(accuracy)))
                upd_res = sb.table("patients").update(update_payload).eq("patient_uid", current_uid).execute()
            else:
                raise
        if not upd_res.data:
            raise BadRequestException("Failed to update patient record")

        patient_record = upd_res.data[0]

        # Sync profile table (doctor_uid, child_name, phone, age)
        try:
            prof_sync = {
                "doctor_uid": doctor_id,
                "child_name": name.strip(),
            }
            if phone:
                prof_sync["phone"] = phone.strip()
            if age is not None:
                prof_sync["age"] = int(age)
            try:
                sb.table("profiles").update(prof_sync).eq("patient_uid", current_uid).execute()
            except Exception as e:
                if "age" in str(e):
                    prof_sync.pop("age", None)
                    sb.table("profiles").update(prof_sync).eq("patient_uid", current_uid).execute()
                else:
                    pass
        except Exception:
            pass

        patient_record["doctor"] = doctor
        return patient_record

    @staticmethod
    def delete_patient_me(current_uid: str) -> None:
        sb = get_supabase()
        sb.table("patients").delete().eq("patient_uid", current_uid).execute()
        try:
            sb.table("profiles").update({"doctor_uid": None}).eq("patient_uid", current_uid).execute()
        except Exception:
            pass
