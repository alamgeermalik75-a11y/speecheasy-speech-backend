import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_patients_endpoints_unauthenticated(client: AsyncClient):
    # Unauthenticated requests must be rejected
    res = await client.get("/api/v1/patients/me")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_patients_create_validation_nothing_optional(client: AsyncClient):
    headers = {"X-Patient-UID": "patient_user_a"}

    # Missing required fields must be rejected (422) - nothing is optional
    incomplete_payload = {
        "doctor_id": "doc-1234-uuid",
        "name": "Hamza"
        # missing age, phone, parent_email, accuracy
    }
    res = await client.post("/api/v1/patients", json=incomplete_payload, headers=headers)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patients_crud_and_references(client: AsyncClient):
    headers_a = {"X-Patient-UID": "patient_user_a"}
    headers_b = {"X-Patient-UID": "patient_user_b"}
    doctor_id = "doc-1234-uuid"

    # Pre-create profile for patient_user_a
    await client.post(
        "/api/v1/profiles",
        json={"parent_name": "Ahmad", "child_name": "Hamza"},
        headers=headers_a
    )

    # 1. Create Patient record with all required fields
    patient_data = {
        "doctor_id": doctor_id,
        "name": "Hamza Ali",
        "age": 6,
        "phone": "+92 300 1234567",
        "parent_email": "parent@example.com",
        "accuracy": 75.5
    }
    create_res = await client.post("/api/v1/patients", json=patient_data, headers=headers_a)
    assert create_res.status_code == 201
    body = create_res.json()
    assert body["name"] == "Hamza Ali"
    assert body["age"] == 6
    assert body["phone"] == "+92 300 1234567"
    assert body["parent_email"] == "parent@example.com"
    assert body["accuracy"] == 75.5
    assert body["doctor_id"] == doctor_id
    assert "doctor" in body

    # 2. Prevent duplicate registration
    dup_res = await client.post("/api/v1/patients", json=patient_data, headers=headers_a)
    assert dup_res.status_code == 409

    # 3. Get my patient record
    get_res = await client.get("/api/v1/patients/me", headers=headers_a)
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Hamza Ali"

    # 4. Strict isolation: User B cannot see User A's patient record
    user_b_get = await client.get("/api/v1/patients/me", headers=headers_b)
    assert user_b_get.status_code == 404

    # 5. Update patient record (all required fields)
    update_data = {
        "doctor_id": doctor_id,
        "name": "Hamza Ali Updated",
        "age": 7,
        "phone": "+92 300 9876543",
        "parent_email": "parent_updated@example.com",
        "accuracy": 82.0
    }
    update_res = await client.put("/api/v1/patients/me", json=update_data, headers=headers_a)
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Hamza Ali Updated"
    assert update_res.json()["age"] == 7
    assert update_res.json()["accuracy"] == 82.0

    # 6. Delete patient record
    del_res = await client.delete("/api/v1/patients/me", headers=headers_a)
    assert del_res.status_code == 204

    # 7. Confirm deleted
    confirm_get = await client.get("/api/v1/patients/me", headers=headers_a)
    assert confirm_get.status_code == 404
