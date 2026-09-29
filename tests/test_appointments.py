import pytest
from datetime import date, timedelta

def get_next_monday() -> date:
    today = date.today()
    days_ahead = (0 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)

@pytest.mark.asyncio
async def test_appointment_slots_and_booking(client):
    headers = {"X-Patient-UID": "user_appt_1"}
    doctor_id = "doc-1234-uuid"

    # Setup profile
    await client.post(
        "/api/v1/profiles",
        json={"parent_name": "Amina", "child_name": "Hamza"},
        headers=headers
    )

    test_date = get_next_monday()
    date_str = test_date.isoformat()

    # 1. Query available slots
    slots_res = await client.get(f"/api/v1/therapists/{doctor_id}/slots?date={date_str}")
    assert slots_res.status_code == 200
    slots = slots_res.json()["slots"]
    assert "9:00 AM" in slots
    assert "9:30 AM" in slots

    # 2. Book 09:00 - 09:30 slot
    book_payload = {
        "doctor_id": doctor_id,
        "appointment_date": date_str,
        "start_time": "09:00:00",
        "end_time": "09:30:00"
    }
    book_res = await client.post("/api/v1/appointments", json=book_payload, headers=headers)
    assert book_res.status_code == 201
    appt = book_res.json()
    assert appt["patient_name"] == "Hamza"
    assert appt["status"] == "booked"

    # 3. Verify notification was generated
    notif_res = await client.get("/api/v1/notifications", headers=headers)
    assert notif_res.status_code == 200
    notifs = notif_res.json()
    assert len(notifs) >= 1
    assert "booked" in notifs[0]["message"].lower()

    # 4. Verify "9:00 AM" is now removed from available slots
    updated_slots_res = await client.get(f"/api/v1/therapists/{doctor_id}/slots?date={date_str}")
    updated_slots = updated_slots_res.json()["slots"]
    assert "9:00 AM" not in updated_slots
    assert "9:30 AM" in updated_slots

    # 5. Concurrency / Double-booking collision test: User 2 tries to book the same slot
    headers_user2 = {"X-Patient-UID": "user_appt_2"}
    await client.post(
        "/api/v1/profiles",
        json={"parent_name": "Parent 2", "child_name": "Child 2"},
        headers=headers_user2
    )
    collision_res = await client.post("/api/v1/appointments", json=book_payload, headers=headers_user2)
    assert collision_res.status_code == 409
    assert "already been booked" in collision_res.json()["detail"].lower()

@pytest.mark.asyncio
async def test_appointment_duration_validation(client):
    headers = {"X-Patient-UID": "user_appt_dur"}
    doctor_id = "doc-1234-uuid"
    test_date = get_next_monday().isoformat()

    # Duration = 45 minutes instead of 30 minutes -> must be rejected with 422
    payload_45min = {
        "doctor_id": doctor_id,
        "appointment_date": test_date,
        "start_time": "09:00:00",
        "end_time": "09:45:00"
    }
    res = await client.post("/api/v1/appointments", json=payload_45min, headers=headers)
    assert res.status_code == 422
    assert "30 minutes" in str(res.json()).lower()

@pytest.mark.asyncio
async def test_appointment_slots_past_date_and_missing_doctor(client):
    # Past date returns empty slots
    res_past = await client.get("/api/v1/therapists/doc-1234-uuid/slots?date=2020-01-01")
    assert res_past.status_code == 200
    assert res_past.json()["slots"] == []

    # Non-existent doctor returns 404
    test_date = get_next_monday().isoformat()
    res_missing = await client.get(f"/api/v1/therapists/nonexistent-doctor-id/slots?date={test_date}")
    assert res_missing.status_code == 404

@pytest.mark.asyncio
async def test_appointment_booking_past_date_and_outside_availability(client):
    headers = {"X-Patient-UID": "user_appt_invalid_times"}
    doctor_id = "doc-1234-uuid"

    await client.post(
        "/api/v1/profiles",
        json={"parent_name": "Parent", "child_name": "Child"},
        headers=headers
    )

    # 1. Past date rejected
    res_past = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": doctor_id,
            "appointment_date": "2020-01-01",
            "start_time": "09:00:00",
            "end_time": "09:30:00"
        },
        headers=headers
    )
    assert res_past.status_code == 422

    # 2. Outside availability rejected (e.g. at 02:00 AM)
    test_date = get_next_monday().isoformat()
    res_outside = await client.post(
        "/api/v1/appointments",
        json={
            "doctor_id": doctor_id,
            "appointment_date": test_date,
            "start_time": "02:00:00",
            "end_time": "02:30:00"
        },
        headers=headers
    )
    assert res_outside.status_code == 400
    assert "outside" in res_outside.json()["detail"].lower()
