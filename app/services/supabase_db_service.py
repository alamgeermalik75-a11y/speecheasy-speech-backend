import secrets
import string
import time as _sys_time
from threading import Lock
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, time, timezone
from typing import List, Optional, Dict, Any, Tuple
from app.core.supabase import get_supabase
from app.core.exceptions import NotFoundException, BadRequestException, ConflictException, ForbiddenException
from app.services.progress_service import URDU_ALPHABET_SEQUENCE, get_next_alphabet

# In-memory thread-safe micro-caches with TTL to eliminate redundant cloud DB latency
_cache_lock = Lock()
_daily_tips_cache: Dict[str, Any] = {"data": None, "expires_at": 0.0}
_therapists_list_cache: Dict[str, Any] = {}
_therapist_by_id_cache: Dict[str, Any] = {}
_therapist_by_code_cache: Dict[str, Any] = {}

def _clear_therapist_cache(doctor_id: Optional[str] = None):
    with _cache_lock:
        _therapists_list_cache.clear()
        if doctor_id:
            _therapist_by_id_cache.pop(doctor_id, None)
        else:
            _therapist_by_id_cache.clear()
            _therapist_by_code_cache.clear()

class SupabaseDbService:
    @staticmethod
    def list_daily_tips() -> List[Dict[str, Any]]:
        now = _sys_time.time()
        with _cache_lock:
            if _daily_tips_cache["data"] is not None and now < _daily_tips_cache["expires_at"]:
                return [dict(t) for t in _daily_tips_cache["data"]]

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
        sorted_tips = sorted(active_tips, key=lambda x: x.get("sort_order", 0))

        with _cache_lock:
            _daily_tips_cache["data"] = [dict(t) for t in sorted_tips]
            _daily_tips_cache["expires_at"] = now + 60.0  # 60s TTL

        return sorted_tips

    @staticmethod
    def list_therapists(status_filter: str = "approved", limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        cache_key = f"{status_filter}:{limit}:{offset}"
        now = _sys_time.time()
        with _cache_lock:
            entry = _therapists_list_cache.get(cache_key)
            if entry and now < entry["expires_at"]:
                return [dict(t) for t in entry["data"]]

        sb = get_supabase()
        res = (
            sb.table("therapists")
            .select("*")
            .eq("status", status_filter)
            .order("rating", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        data = res.data or []
        with _cache_lock:
            _therapists_list_cache[cache_key] = {
                "data": [dict(t) for t in data],
                "expires_at": now + 20.0  # 20s TTL
            }
            for d in data:
                if "id" in d:
                    _therapist_by_id_cache[d["id"]] = {
                        "data": dict(d),
                        "expires_at": now + 60.0
                    }
        return data

    @staticmethod
    def get_therapist_by_code(code: str) -> Dict[str, Any]:
        cleaned_code = code.strip().upper()
        now = _sys_time.time()
        with _cache_lock:
            entry = _therapist_by_code_cache.get(cleaned_code)
            if entry and now < entry["expires_at"]:
                return dict(entry["data"])

        sb = get_supabase()
        res = (
            sb.table("therapists")
            .select("*")
            .eq("doctor_code", cleaned_code)
            .eq("status", "approved")
            .execute()
        )
        if not res.data:
            raise NotFoundException("No approved doctor found with that code.")
        doc = res.data[0]
        with _cache_lock:
            _therapist_by_code_cache[cleaned_code] = {
                "data": dict(doc),
                "expires_at": now + 60.0
            }
            if "id" in doc:
                _therapist_by_id_cache[doc["id"]] = {
                    "data": dict(doc),
                    "expires_at": now + 60.0
                }
        return doc

    @staticmethod
    def get_therapist_by_id(doctor_id: str) -> Dict[str, Any]:
        now = _sys_time.time()
        with _cache_lock:
            entry = _therapist_by_id_cache.get(doctor_id)
            if entry and now < entry["expires_at"]:
                return dict(entry["data"])

        sb = get_supabase()
        res = sb.table("therapists").select("*").eq("id", doctor_id).execute()
        if not res.data:
            raise NotFoundException("Doctor not found")
        doc = res.data[0]
        with _cache_lock:
            _therapist_by_id_cache[doctor_id] = {
                "data": dict(doc),
                "expires_at": now + 60.0
            }
        return doc

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
            try:
                doc_data = SupabaseDbService.get_therapist_by_id(doc_id)
                return {
                    "status": "approved",
                    "doctor": doc_data,
                    "request": None
                }
            except Exception:
                pass

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
            try:
                doc_data = SupabaseDbService.get_therapist_by_id(doc_id)
                return {
                    "status": "approved",
                    "doctor": doc_data,
                    "request": None
                }
            except Exception:
                pass

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

        # Enforce 5 continuous cancellations limit server-side
        existing_appts = (
            sb.table("appointments")
            .select("id, status, created_at, appointment_date, start_time")
            .eq("patient_uid", current_uid)
            .execute()
        )
        _, is_restricted = SupabaseDbService._calculate_continuous_cancellations(existing_appts.data or [])
        if is_restricted:
            raise ForbiddenException(
                "Booking restricted: Your profile is locked due to 5 continuous appointment cancellations. Please contact support."
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
    def _calculate_continuous_cancellations(appts: List[Dict[str, Any]]) -> Tuple[int, bool]:
        if not appts:
            return 0, False

        sorted_appts = sorted(
            appts,
            key=lambda a: (
                str(a.get("created_at") or ""),
                str(a.get("appointment_date") or ""),
                str(a.get("start_time") or "")
            ),
            reverse=True
        )

        current_streak = 0
        max_streak = 0
        temp_streak = 0

        # Scan chronological order (oldest to newest) to detect any streak of 5
        for a in reversed(sorted_appts):
            st = (a.get("status") or "").lower()
            if st == "cancelled":
                temp_streak += 1
                if temp_streak > max_streak:
                    max_streak = temp_streak
            elif st in ("completed", "confirmed", "booked"):
                temp_streak = 0

        # Current continuous streak from latest backwards
        for a in sorted_appts:
            st = (a.get("status") or "").lower()
            if st == "cancelled":
                current_streak += 1
            elif st in ("completed", "confirmed", "booked"):
                break

        is_restricted = (max_streak >= 5) or (current_streak >= 5)
        return current_streak, is_restricted

    @staticmethod
    def get_my_appointments(current_uid: str) -> Dict[str, Any]:
        sb = get_supabase()

        # 1. Fetch appointments and patient profile concurrently
        def fetch_appts():
            return (
                sb.table("appointments")
                .select("*")
                .eq("patient_uid", current_uid)
                .order("appointment_date", desc=True)
                .order("start_time", desc=True)
                .execute()
            )

        def fetch_profile():
            return sb.table("profiles").select("*").eq("patient_uid", current_uid).execute()

        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_appts = executor.submit(fetch_appts)
            fut_prof = executor.submit(fetch_profile)
            appts_res = fut_appts.result()
            prof_res = fut_prof.result()

        appts = appts_res.data or []
        profile_data = prof_res.data[0] if prof_res.data else {}

        # 2. Count continuous cancellations to derive profile lock
        cancellation_count, is_restricted = SupabaseDbService._calculate_continuous_cancellations(appts)

        # 3. Fetch therapist info for all referenced doctors (leverage cache)
        doc_ids = list({a["doctor_id"] for a in appts if a.get("doctor_id")})
        doc_map = {}
        missing_doc_ids = []
        now = _sys_time.time()

        with _cache_lock:
            for did in doc_ids:
                entry = _therapist_by_id_cache.get(did)
                if entry and now < entry["expires_at"]:
                    doc_map[did] = dict(entry["data"])
                else:
                    missing_doc_ids.append(did)

        if missing_doc_ids:
            docs_res = sb.table("therapists").select("*").in_("id", missing_doc_ids).execute()
            fetched_docs = docs_res.data or []
            with _cache_lock:
                for d in fetched_docs:
                    doc_map[d["id"]] = d
                    _therapist_by_id_cache[d["id"]] = {
                        "data": dict(d),
                        "expires_at": now + 60.0
                    }

        # 4. Build enriched appointment list
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
                    "phone": doc.get("phone"),
                    "email": doc.get("email"),
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

        _clear_therapist_cache(doctor_id)
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
        from app.curriculum.curriculum_manager import curriculum_manager, CATEGORY_ORDER
        sb = get_supabase()
        now_iso = datetime.now(timezone.utc).isoformat()
        alpha = alphabet_name.strip()
        lvl = level_key.strip()
        item = item_id.strip()

        # 1. Query existing unique item record
        existing_res = sb.table("attempts").select("*").eq("patient_uid", current_uid).eq("item_id", item).eq("alphabet_name", alpha).eq("level_key", lvl).execute()
        existing_list = existing_res.data or []

        improved = False
        progress_earned = 0
        attempt_record: Dict[str, Any] = {}

        if not existing_list:
            # CASE A: UNIQUE ITEM -> INSERT
            ins_res = sb.table("attempts").insert({
                "patient_uid": current_uid,
                "item_id": item,
                "alphabet_name": alpha,
                "level_key": lvl,
                "score": score,
                "attempted_at": now_iso
            }).execute()
            if ins_res.data:
                attempt_record = dict(ins_res.data[0])
            else:
                attempt_record = {
                    "id": 0,
                    "patient_uid": current_uid,
                    "item_id": item,
                    "alphabet_name": alpha,
                    "level_key": lvl,
                    "score": score,
                    "attempted_at": now_iso
                }
            improved = True
            progress_earned = score

            # Insert into progress_events for new item improvement
            try:
                sb.table("progress_events").insert({
                    "patient_uid": current_uid,
                    "item_id": item,
                    "alphabet_name": alpha,
                    "level_key": lvl,
                    "previous_score": 0,
                    "new_score": score,
                    "progress_earned": progress_earned,
                    "earned_at": now_iso
                }).execute()
                print(f"[PROGRESS] progress_events INSERT (new item): score={score}, earned={progress_earned}")
            except Exception as pe_err:
                print(f"[PROGRESS] Failed to insert progress_events: {pe_err}")
        else:
            existing = existing_list[0]
            old_score = existing.get("score", 0)
            if score > old_score:
                # CASE B: SAME ITEM + HIGHER SCORE -> UPDATE
                progress_earned = score - old_score
                upd_res = sb.table("attempts").update({
                    "score": score,
                    "attempted_at": now_iso
                }).eq("id", existing["id"]).execute()
                if upd_res.data:
                    attempt_record = dict(upd_res.data[0])
                else:
                    attempt_record = dict(existing, score=score, attempted_at=now_iso)
                improved = True

                # Insert into progress_events for higher score improvement
                try:
                    sb.table("progress_events").insert({
                        "patient_uid": current_uid,
                        "item_id": item,
                        "alphabet_name": alpha,
                        "level_key": lvl,
                        "previous_score": old_score,
                        "new_score": score,
                        "progress_earned": progress_earned,
                        "earned_at": now_iso
                    }).execute()
                    print(f"[PROGRESS] progress_events INSERT (higher score): old={old_score}, new={score}, earned={progress_earned}")
                except Exception as pe_err:
                    print(f"[PROGRESS] Failed to insert progress_events: {pe_err}")
            else:
                # CASE C & D: SAME ITEM + EQUAL OR LOWER SCORE -> NO UPDATE
                attempt_record = dict(existing)
                improved = False
                progress_earned = 0
                print(f"[PROGRESS] NO progress_events (equal/lower score): current_best={old_score}, submitted={score}")

        # Milestone notification ONLY when improved to >= 70
        milestone_msg = None
        if improved and score >= 70:
            milestone_msg = f"Nice work! Score: {score}%"
            try:
                sb.table("notifications").insert({
                    "patient_uid": current_uid,
                    "icon": "🏆",
                    "message": milestone_msg,
                    "is_read": False
                }).execute()
            except Exception:
                pass

        # 3. Calculate category, alphabet, and overall progress
        history_res = sb.table("attempts").select("*").eq("patient_uid", current_uid).eq("alphabet_name", alpha).execute()
        attempts = history_res.data or []

        best_by_level: Dict[str, Dict[str, int]] = {c: {} for c in CATEGORY_ORDER}
        for a in attempts:
            k = a.get("level_key")
            if k in best_by_level:
                it = a.get("item_id")
                best_by_level[k][it] = max(best_by_level[k].get(it, 0), a.get("score", 0))

        alphabet_total_pct = 0.0
        all_categories_complete = True
        categories_res: Dict[str, Any] = {}
        previous_complete = True

        for c in CATEGORY_ORDER:
            item_scores = best_by_level[c]
            item_count = curriculum_manager.get_category_item_count(alpha, c)
            passed_count = sum(1 for s in item_scores.values() if s >= 70)

            if item_count > 0:
                score_sum = sum(item_scores.values())
                score_pct = round((score_sum / (item_count * 100)) * 100, 2)
                is_comp = (passed_count >= item_count)
            else:
                score_pct = 0.0
                is_comp = False

            is_unlocked = previous_complete
            previous_complete = is_comp
            if not is_comp:
                all_categories_complete = False

            alphabet_total_pct += score_pct * 0.20
            categories_res[c] = {
                "score_percentage": score_pct,
                "is_completed": is_comp,
                "is_unlocked": is_unlocked,
                "total_items": item_count,
                "passed_items": passed_count,
            }

        alphabet_progress = min(100.0, round(alphabet_total_pct, 2))
        category_progress = categories_res.get(lvl, {}).get("score_percentage", 0.0)
        is_cat_complete = categories_res.get(lvl, {}).get("is_completed", False)

        # Overall progress
        all_attempts_res = sb.table("attempts").select("score").eq("patient_uid", current_uid).execute()
        total_score = sum(r.get("score", 0) for r in (all_attempts_res.data or []))
        total_curriculum_items = curriculum_manager.get_total_curriculum_items()
        overall_progress = round((total_score / (total_curriculum_items * 100)) * 100, 2) if total_curriculum_items > 0 else 0.0

        # Safe diagnostic logging
        print(f"[PROGRESS] attempt received: patient_uid={current_uid}, item={item}, alpha={alpha}, level={lvl}, score={score}")
        print(f"[PROGRESS] existing best = {0 if not existing_list else existing_list[0].get('score', 0)}")
        print(f"[PROGRESS] submitted score = {score}")
        print(f"[PROGRESS] improvement = {progress_earned}")
        print(f"[PROGRESS] attempts DB result = {attempt_record}")
        print(f"[PROGRESS] calculated category progress = {category_progress}")

        # 4. Focus sound progression
        focus_res = sb.table("focus_sound").select("*").eq("patient_uid", current_uid).execute()
        advanced = False
        next_sound = None
        focus_progress = alphabet_progress / 100.0

        if focus_res.data:
            curr_focus = focus_res.data[0]
            if curr_focus.get("alphabet_name") == alpha:
                if all_categories_complete:
                    next_item = curriculum_manager.get_next_alphabet(alpha)
                    if next_item:
                        advanced = True
                        next_sound = next_item["name"]
                        sb.table("focus_sound").update({
                            "sound": next_item["letter"],
                            "alphabet_name": next_item["name"],
                            "progress": 0.0
                        }).eq("patient_uid", current_uid).execute()
                        focus_progress = 0.0

                        try:
                            sb.table("notifications").insert({
                                "patient_uid": current_uid,
                                "icon": "🎉",
                                "message": f"Sound '{alpha}' fully mastered! Moving on to '{next_item['name']}'.",
                                "is_read": False
                            }).execute()
                        except Exception:
                            pass
                    else:
                        sb.table("focus_sound").update({"progress": 1.0}).eq("patient_uid", current_uid).execute()
                        focus_progress = 1.0
                        try:
                            sb.table("notifications").insert({
                                "patient_uid": current_uid,
                                "icon": "🎉",
                                "message": "Congratulations! All Urdu speech sounds fully mastered!",
                                "is_read": False
                            }).execute()
                        except Exception:
                            pass
                else:
                    sb.table("focus_sound").update({"progress": round(focus_progress, 2)}).eq("patient_uid", current_uid).execute()

        # Determine next category unlock
        lvl_idx = CATEGORY_ORDER.index(lvl) if lvl in CATEGORY_ORDER else -1
        next_cat_unlocked = False
        if lvl_idx >= 0 and lvl_idx + 1 < len(CATEGORY_ORDER):
            next_cat = CATEGORY_ORDER[lvl_idx + 1]
            next_cat_unlocked = categories_res.get(next_cat, {}).get("is_unlocked", False)

        return {
            "attempt": attempt_record,
            "milestone_notification": milestone_msg,
            "sound_mastered": advanced,
            "next_sound": next_sound,
            "focus_progress": focus_progress,
            "category_progress": category_progress,
            "alphabet_progress": alphabet_progress,
            "overall_progress": overall_progress,
            "improved": improved,
            "progress_earned": progress_earned,
            "is_category_completed": is_cat_complete,
            "next_category_unlocked": next_cat_unlocked,
        }

    @staticmethod
    def _compute_sound_overall_for_patient_at_cutoff(
        patient_events: List[Dict[str, Any]],
        fallback_attempts: List[Dict[str, Any]],
        alphabet_name: str,
        cutoff_date: date,
        user_tz: timezone
    ) -> float:
        from app.curriculum.curriculum_manager import curriculum_manager, CATEGORY_ORDER

        items_best: Dict[str, Tuple[int, str]] = {}
        for ev in patient_events:
            if ev.get("alphabet_name") != alphabet_name:
                continue
            ts = ev.get("earned_at") or ev.get("created_at")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(user_tz)
                if dt.date() <= cutoff_date:
                    it = ev.get("item_id")
                    lvl = ev.get("level_key") or "words"
                    sc = int(ev.get("new_score") or 0)
                    if it not in items_best or sc > items_best[it][0]:
                        items_best[it] = (sc, lvl)
            except Exception:
                pass

        if not items_best and fallback_attempts:
            for a in fallback_attempts:
                if a.get("alphabet_name") != alphabet_name:
                    continue
                ts = a.get("attempted_at") or a.get("created_at")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(user_tz)
                    if dt.date() <= cutoff_date:
                        it = a.get("item_id")
                        lvl = a.get("level_key") or "words"
                        sc = int(a.get("score") or 0)
                        if it not in items_best or sc > items_best[it][0]:
                            items_best[it] = (sc, lvl)
                except Exception:
                    pass

        if not items_best:
            return 0.0

        sound_overall = 0.0
        for c in CATEGORY_ORDER:
            item_count = curriculum_manager.get_category_item_count(alphabet_name, c)
            c_scores = [sc for (it, (sc, lvl)) in items_best.items() if lvl == c]
            if item_count > 0:
                score_pct = round((sum(c_scores) / (item_count * 100)) * 100, 2)
                sound_overall += score_pct * 0.20

        return round(sound_overall, 2)

    @staticmethod
    def get_progress_overview(current_uid: str, alphabet_name: Optional[str] = None, tz_offset_minutes: int = 0) -> Dict[str, Any]:
        from app.curriculum.curriculum_manager import curriculum_manager, CATEGORY_ORDER
        sb = get_supabase()
        
        alpha = alphabet_name.strip() if alphabet_name else None
        if not alpha:
            try:
                fs_res = sb.table("focus_sound").select("alphabet_name").eq("patient_uid", current_uid).limit(1).execute()
                if fs_res.data and fs_res.data[0].get("alphabet_name"):
                    alpha = fs_res.data[0].get("alphabet_name")
            except Exception:
                pass
        if not alpha:
            alpha = "bay"

        history_res = sb.table("attempts").select("*").eq("patient_uid", current_uid).eq("alphabet_name", alpha).execute()
        attempts = history_res.data or []

        best_by_level: Dict[str, Dict[str, int]] = {c: {} for c in CATEGORY_ORDER}
        for a in attempts:
            k = a.get("level_key")
            if k in best_by_level:
                it = a.get("item_id")
                best_by_level[k][it] = max(best_by_level[k].get(it, 0), a.get("score", 0))

        alphabet_total_pct = 0.0
        categories_res: Dict[str, Any] = {}
        previous_complete = True

        for c in CATEGORY_ORDER:
            item_scores = best_by_level[c]
            item_count = curriculum_manager.get_category_item_count(alpha, c)
            passed_count = sum(1 for s in item_scores.values() if s >= 70)

            if item_count > 0:
                score_sum = sum(item_scores.values())
                score_pct = round((score_sum / (item_count * 100)) * 100, 2)
                is_comp = (passed_count >= item_count)
            else:
                score_pct = 0.0
                is_comp = False

            is_unlocked = previous_complete
            previous_complete = is_comp
            alphabet_total_pct += score_pct * 0.20

            categories_res[c] = {
                "score_percentage": score_pct,
                "is_completed": is_comp,
                "is_unlocked": is_unlocked,
                "total_items": item_count,
                "passed_items": passed_count,
            }

        all_attempts_res = sb.table("attempts").select("*").eq("patient_uid", current_uid).execute()
        all_attempts = all_attempts_res.data or []
        total_score = sum(r.get("score", 0) for r in all_attempts)
        total_curriculum_items = curriculum_manager.get_total_curriculum_items()
        overall_progress = round((total_score / (total_curriculum_items * 100)) * 100, 2) if total_curriculum_items > 0 else 0.0

        # Daily, weekly, monthly calculated from DAY-TO-DAY CHANGE of each alphabet's Sound Overall %
        user_tz = timezone(timedelta(minutes=tz_offset_minutes))
        now = datetime.now(user_tz)
        today_date = now.date()

        events: List[Dict[str, Any]] = []
        try:
            pe_res = sb.table("progress_events").select("*").eq("patient_uid", current_uid).execute()
            events = pe_res.data or []
        except Exception as pe_read_err:
            print(f"[PROGRESS] Error reading progress_events for overview: {pe_read_err}")

        # Collect all distinct alphabets ever practiced by this patient
        practiced_alphabets: Set[str] = set()
        for ev in events:
            a_name = ev.get("alphabet_name")
            if a_name:
                practiced_alphabets.add(a_name)
        for a in all_attempts:
            a_name = a.get("alphabet_name")
            if a_name:
                practiced_alphabets.add(a_name)

        # 1. Last 7 Days history breakdown in local time based on Sound Overall changes
        daily_history: List[Dict[str, Any]] = []
        for i in range(6, -1, -1):
            day_dt = today_date - timedelta(days=i)
            prev_dt = day_dt - timedelta(days=1)
            day_progress = 0.0
            for alpha_key in practiced_alphabets:
                so_today = SupabaseDbService._compute_sound_overall_for_patient_at_cutoff(
                    events, all_attempts, alpha_key, day_dt, user_tz
                )
                so_prev = SupabaseDbService._compute_sound_overall_for_patient_at_cutoff(
                    events, all_attempts, alpha_key, prev_dt, user_tz
                )
                sound_diff = max(round(so_today - so_prev, 2), 0.0)
                day_progress += sound_diff

            daily_history.append({
                "date": day_dt.isoformat(),
                "label": f"{day_dt.day}/{day_dt.month}",
                "progress": round(day_progress, 2),
            })

        # 2. Last 4 Weeks history breakdown (ordered from Wk 1 to Wk 4)
        weekly_history: List[Dict[str, Any]] = []
        for w in range(3, -1, -1):
            w_start_dt = today_date - timedelta(days=(w + 1) * 7)
            w_end_dt = today_date - timedelta(days=w * 7)
            week_progress = 0.0
            for alpha_key in practiced_alphabets:
                so_end = SupabaseDbService._compute_sound_overall_for_patient_at_cutoff(
                    events, all_attempts, alpha_key, w_end_dt, user_tz
                )
                so_start = SupabaseDbService._compute_sound_overall_for_patient_at_cutoff(
                    events, all_attempts, alpha_key, w_start_dt, user_tz
                )
                w_diff = max(round(so_end - so_start, 2), 0.0)
                week_progress += w_diff
            weekly_history.append({
                "label": f"Wk {4 - w}",
                "progress": round(week_progress, 2),
            })

        # Daily progress is today's total Sound Overall positive changes
        daily_progress_pct = daily_history[-1]["progress"] if daily_history else 0.0

        # Weekly progress is total positive changes across all sounds in last 7 days
        week_7d_ago = today_date - timedelta(days=7)
        weekly_progress_pct = 0.0
        for alpha_key in practiced_alphabets:
            so_now = SupabaseDbService._compute_sound_overall_for_patient_at_cutoff(
                events, all_attempts, alpha_key, today_date, user_tz
            )
            so_7d = SupabaseDbService._compute_sound_overall_for_patient_at_cutoff(
                events, all_attempts, alpha_key, week_7d_ago, user_tz
            )
            weekly_progress_pct += max(round(so_now - so_7d, 2), 0.0)
        weekly_progress_pct = round(weekly_progress_pct, 2)

        # Monthly progress is total positive changes across all sounds in last 30 days
        month_30d_ago = today_date - timedelta(days=30)
        monthly_progress_pct = 0.0
        for alpha_key in practiced_alphabets:
            so_now = SupabaseDbService._compute_sound_overall_for_patient_at_cutoff(
                events, all_attempts, alpha_key, today_date, user_tz
            )
            so_30d = SupabaseDbService._compute_sound_overall_for_patient_at_cutoff(
                events, all_attempts, alpha_key, month_30d_ago, user_tz
            )
            monthly_progress_pct += max(round(so_now - so_30d, 2), 0.0)
        monthly_progress_pct = round(monthly_progress_pct, 2)

        return {
            "overall_progress": overall_progress,
            "alphabet_name": alpha,
            "alphabet_progress": min(100.0, round(alphabet_total_pct, 2)),
            "categories": categories_res,
            "daily_progress": daily_progress_pct,
            "weekly_progress": weekly_progress_pct,
            "monthly_progress": monthly_progress_pct,
            "daily_history": daily_history,
            "weekly_history": weekly_history,
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
        attempts = res.data or []
        for a in attempts:
            if not a.get("attempted_at"):
                a["attempted_at"] = a.get("created_at")
        return attempts

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
