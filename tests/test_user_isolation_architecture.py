import pytest
import jwt
from datetime import datetime, timezone, timedelta, date
from app.config import settings

def make_test_token(uid: str, email: str = "user@example.com") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": uid,
        "email": email,
        "role": "patient",
        "token_type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


@pytest.mark.asyncio
async def test_section_25_user_isolation_architecture(client):
    """
    Mandatory Security Verification (Section 25):
    Two users:
      USER A: UID = AAA111
      USER B: UID = BBB222
    Verify complete cross-user data isolation across:
      1. Profiles
      2. Practice Attempts & History
      3. Notifications
      4. Ratings
      5. Appointments
      6. Doctor Registration Requests
      7. Account Deletion Cascade Isolation
    """
    uid_a = "AAA111"
    uid_b = "BBB222"
    token_a = make_test_token(uid_a, "user_a@example.com")
    token_b = make_test_token(uid_b, "user_b@example.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    doctor_id = "doc-1234-uuid"

    # =========================================================================
    # 1. PROFILE CREATION & ISOLATION
    # =========================================================================
    # User A creates Profile A
    res_a = await client.post(
        "/api/v1/profiles",
        json={
            "parent_name": "Ali Parent A",
            "child_name": "Ahmed Child A",
            "phone": "+923001111111",
            "sound": "ب",
            "alphabet_name": "bay",
        },
        headers=headers_a,
    )
    assert res_a.status_code == 201
    profile_a = res_a.json()
    assert profile_a["patient_uid"] == uid_a
    assert profile_a["child_name"] == "Ahmed Child A"
    assert profile_a["focus_sound"]["sound"] == "ب"

    # User B queries /profiles/me -> MUST return 404 (B has no profile yet)
    res_b_me = await client.get("/api/v1/profiles/me", headers=headers_b)
    assert res_b_me.status_code == 404

    # User B creates Profile B
    res_b = await client.post(
        "/api/v1/profiles",
        json={
            "parent_name": "Bilal Parent B",
            "child_name": "Basit Child B",
            "phone": "+923002222222",
            "sound": "ت",
            "alphabet_name": "tay",
        },
        headers=headers_b,
    )
    assert res_b.status_code == 201
    profile_b = res_b.json()
    assert profile_b["patient_uid"] == uid_b
    assert profile_b["child_name"] == "Basit Child B"
    assert profile_b["focus_sound"]["sound"] == "ت"

    # User A reads /profiles/me -> Sees Profile A ONLY
    read_a = await client.get("/api/v1/profiles/me", headers=headers_a)
    assert read_a.status_code == 200
    assert read_a.json()["patient_uid"] == uid_a
    assert read_a.json()["child_name"] == "Ahmed Child A"

    # User B reads /profiles/me -> Sees Profile B ONLY
    read_b = await client.get("/api/v1/profiles/me", headers=headers_b)
    assert read_b.status_code == 200
    assert read_b.json()["patient_uid"] == uid_b
    assert read_b.json()["child_name"] == "Basit Child B"

    # =========================================================================
    # 2. PRACTICE ATTEMPTS & HISTORY ISOLATION
    # =========================================================================
    # User A records an attempt
    att_a = await client.post(
        "/api/v1/attempts",
        json={
            "item_id": "word_item_a1",
            "alphabet_name": "bay",
            "level_key": "words",
            "score": 85,
        },
        headers=headers_a,
    )
    assert att_a.status_code == 201
    assert att_a.json()["attempt"]["patient_uid"] == uid_a

    # User B records an attempt
    att_b = await client.post(
        "/api/v1/attempts",
        json={
            "item_id": "word_item_b1",
            "alphabet_name": "tay",
            "level_key": "words",
            "score": 95,
        },
        headers=headers_b,
    )
    assert att_b.status_code == 201
    assert att_b.json()["attempt"]["patient_uid"] == uid_b

    # History check: User A must see only A's attempt
    hist_a = await client.get("/api/v1/attempts/history", headers=headers_a)
    assert hist_a.status_code == 200
    items_a = hist_a.json()
    assert len(items_a) == 1
    assert items_a[0]["patient_uid"] == uid_a
    assert items_a[0]["item_id"] == "word_item_a1"

    # History check: User B must see only B's attempt
    hist_b = await client.get("/api/v1/attempts/history", headers=headers_b)
    assert hist_b.status_code == 200
    items_b = hist_b.json()
    assert len(items_b) == 1
    assert items_b[0]["patient_uid"] == uid_b
    assert items_b[0]["item_id"] == "word_item_b1"

    # =========================================================================
    # 3. NOTIFICATIONS ISOLATION
    # =========================================================================
    # High score attempts (> 70) generated milestone notifications
    notifs_a = (await client.get("/api/v1/notifications", headers=headers_a)).json()
    assert len(notifs_a) >= 1
    assert all(n["patient_uid"] == uid_a for n in notifs_a)
    assert "85%" in notifs_a[0]["message"]

    notifs_b = (await client.get("/api/v1/notifications", headers=headers_b)).json()
    assert len(notifs_b) >= 1
    assert all(n["patient_uid"] == uid_b for n in notifs_b)
    assert "95%" in notifs_b[0]["message"]

    # =========================================================================
    # 4. DOCTOR RATINGS ISOLATION
    # =========================================================================
    # User A rates doctor with 4 stars
    rate_a_res = await client.post(
        "/api/v1/ratings",
        json={"doctor_id": doctor_id, "rating": 4},
        headers=headers_a,
    )
    assert rate_a_res.status_code == 200

    # User B checks rating for same doctor -> Must be None (B hasn't rated yet)
    b_rating_check = await client.get(
        f"/api/v1/ratings/{doctor_id}/my-rating",
        headers=headers_b,
    )
    assert b_rating_check.status_code == 200
    assert b_rating_check.json()["rating"] is None

    # User B rates same doctor with 5 stars
    rate_b_res = await client.post(
        "/api/v1/ratings",
        json={"doctor_id": doctor_id, "rating": 5},
        headers=headers_b,
    )
    assert rate_b_res.status_code == 200

    # User A's rating check must still return 4
    a_rating_check = await client.get(
        f"/api/v1/ratings/{doctor_id}/my-rating",
        headers=headers_a,
    )
    assert a_rating_check.status_code == 200
    assert a_rating_check.json()["rating"] == 4

    # User B's rating check must return 5
    b_rating_check2 = await client.get(
        f"/api/v1/ratings/{doctor_id}/my-rating",
        headers=headers_b,
    )
    assert b_rating_check2.status_code == 200
    assert b_rating_check2.json()["rating"] == 5

    # =========================================================================
    # 5. APPOINTMENTS & CLINICAL BOOKING ISOLATION
    # =========================================================================
    # User A books 10:00 - 10:30 on next Monday
    today = date.today()
    days_ahead = (0 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    target_date = (today + timedelta(days=days_ahead)).isoformat()

    appt_a_res = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": doctor_id,
            "appointment_date": target_date,
            "start_time": "10:00:00",
            "end_time": "10:30:00",
        },
        headers=headers_a,
    )
    assert appt_a_res.status_code == 201
    appt_a = appt_a_res.json()
    assert appt_a["patient_uid"] == uid_a
    # Patient name was authoritatively pulled from Profile A ("Ahmed Child A")
    assert appt_a["patient_name"] == "Ahmed Child A"

    # User B attempts to book the same slot -> 409 Conflict
    appt_b_collision = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": doctor_id,
            "appointment_date": target_date,
            "start_time": "10:00:00",
            "end_time": "10:30:00",
        },
        headers=headers_b,
    )
    assert appt_b_collision.status_code == 409

    # User B books a different slot (11:00 - 11:30)
    appt_b_res = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": doctor_id,
            "appointment_date": target_date,
            "start_time": "11:00:00",
            "end_time": "11:30:00",
        },
        headers=headers_b,
    )
    assert appt_b_res.status_code == 201
    appt_b = appt_b_res.json()
    assert appt_b["patient_uid"] == uid_b
    assert appt_b["patient_name"] == "Basit Child B"

    # =========================================================================
    # 6. DOCTOR REGISTRATION REQUESTS ISOLATION
    # =========================================================================
    # User A requests registration with doctor
    req_a_res = await client.post(
        "/api/v1/therapists/request",
        json={"doctor_id": doctor_id},
        headers=headers_a,
    )
    assert req_a_res.status_code == 201
    req_a = req_a_res.json()
    assert req_a["patient_uid"] == uid_a
    assert req_a["patient_name"] == "Ahmed Child A"

    # User A status check -> pending
    status_a = await client.get("/api/v1/therapists/my-status", headers=headers_a)
    assert status_a.status_code == 200
    assert status_a.json()["status"] == "pending"

    # User B status check -> still 'none'
    status_b = await client.get("/api/v1/therapists/my-status", headers=headers_b)
    assert status_b.status_code == 200
    assert status_b.json()["status"] == "none"

    # =========================================================================
    # 7. ACCOUNT DELETION CASCADE & NON-INTERFERENCE
    # =========================================================================
    # User A deletes their account
    del_a = await client.delete("/api/v1/profiles/me", headers=headers_a)
    assert del_a.status_code == 204

    # User A profile is gone
    check_a_deleted = await client.get("/api/v1/profiles/me", headers=headers_a)
    assert check_a_deleted.status_code == 404

    # User B profile, history, notifications, rating remain completely intact!
    check_b_intact = await client.get("/api/v1/profiles/me", headers=headers_b)
    assert check_b_intact.status_code == 200
    assert check_b_intact.json()["patient_uid"] == uid_b

    b_hist_intact = await client.get("/api/v1/attempts/history", headers=headers_b)
    assert len(b_hist_intact.json()) == 1

    b_notifs_intact = await client.get("/api/v1/notifications", headers=headers_b)
    assert len(b_notifs_intact.json()) >= 1


@pytest.mark.asyncio
async def test_jwt_authoritative_and_header_mismatch_rejected(client):
    """
    Spec section 3: JWT identity > X-Patient-UID. A header that contradicts
    the authenticated JWT must be rejected; a matching header is tolerated.
    """
    uid_a = "AAA333"
    token_a = make_test_token(uid_a, "auth_user@example.com")

    # Matching header: accepted (backward compatibility)
    res_match = await client.post(
        "/api/v1/profiles",
        json={"parent_name": "Auth Parent", "child_name": "Auth Child"},
        headers={"Authorization": f"Bearer {token_a}", "X-Patient-UID": uid_a},
    )
    assert res_match.status_code == 201
    assert res_match.json()["patient_uid"] == uid_a

    # Mismatched header: rejected with 403
    res_mismatch = await client.get(
        "/api/v1/profiles/me",
        headers={"Authorization": f"Bearer {token_a}", "X-Patient-UID": "SOMEONE_ELSE"},
    )
    assert res_mismatch.status_code == 403


@pytest.mark.asyncio
async def test_patient_appointment_status_rules(client):
    """
    Spec section 20: patients may only cancel their own appointment.
    Cross-patient updates are rejected; therapist-only statuses are rejected.
    """
    today = date.today()
    days_ahead = (0 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    target_date = (today + timedelta(days=days_ahead)).isoformat()

    token_a = make_test_token("AAA444", "pat_a@example.com")
    token_b = make_test_token("BBB444", "pat_b@example.com")

    for uid, token, child in (("AAA444", token_a, "Kid A"), ("BBB444", token_b, "Kid B")):
        res = await client.post(
            "/api/v1/profiles",
            json={"parent_name": f"Parent {uid}", "child_name": child},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 201

    book_res = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": "doc-1234-uuid",
            "appointment_date": target_date,
            "start_time": "12:00:00",
            "end_time": "12:30:00",
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert book_res.status_code == 201
    appt_id = book_res.json()["id"]

    # User B cannot modify User A's appointment
    foreign = await client.patch(
        f"/api/v1/appointments/{appt_id}/status",
        json={"status": "cancelled"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert foreign.status_code == 403

    # Therapist-controlled status rejected for patients
    confirmed = await client.patch(
        f"/api/v1/appointments/{appt_id}/status",
        json={"status": "confirmed"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert confirmed.status_code == 403

    # Owner cancels successfully
    cancel = await client.patch(
        f"/api/v1/appointments/{appt_id}/status",
        json={"status": "cancelled"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    # Slot freed: User B can now book it
    rebook = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": "doc-1234-uuid",
            "appointment_date": target_date,
            "start_time": "12:00:00",
            "end_time": "12:30:00",
        },
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert rebook.status_code == 201
