import pytest

@pytest.mark.asyncio
async def test_therapists_list_and_code_lookup(client):
    # 1. List therapists
    res = await client.get("/api/v1/therapists")
    assert res.status_code == 200
    doctors = res.json()
    assert len(doctors) >= 1
    assert doctors[0]["doctor_code"] == "SPK-1234"

    # 2. Lookup by valid code (case-insensitive)
    code_res = await client.get("/api/v1/therapists/by-code/spk-1234")
    assert code_res.status_code == 200
    assert code_res.json()["doctor_code"] == "SPK-1234"

    # 3. Lookup non-existent code
    not_found = await client.get("/api/v1/therapists/by-code/NONEXISTENT-999")
    assert not_found.status_code == 404

@pytest.mark.asyncio
async def test_therapist_request_flow_and_conflict(client):
    headers = {"X-Patient-UID": "user_doctor_req"}

    # Must create profile first
    await client.post(
        "/api/v1/profiles",
        json={"parent_name": "Parent A", "child_name": "Child A"},
        headers=headers
    )

    # Status before request should be 'none'
    status_res = await client.get("/api/v1/therapists/my-status", headers=headers)
    assert status_res.status_code == 200
    assert status_res.json()["status"] == "none"

    # 1. Send registration request
    req_res = await client.post(
        "/api/v1/therapists/request",
        json={"doctor_id": "doc-1234-uuid"},
        headers=headers
    )
    assert req_res.status_code == 201
    assert req_res.json()["status"] == "pending"
    assert req_res.json()["patient_name"] == "Child A"

    # Status after request should be 'pending'
    status_pending = await client.get("/api/v1/therapists/my-status", headers=headers)
    assert status_pending.json()["status"] == "pending"

    # 2. Duplicate pending request must return 409 Conflict
    dup_res = await client.post(
        "/api/v1/therapists/request",
        json={"doctor_id": "doc-1234-uuid"},
        headers=headers
    )
    assert dup_res.status_code == 409
    assert "pending" in dup_res.json()["detail"].lower()

@pytest.mark.asyncio
async def test_therapist_request_missing_doctor_and_profile(client):
    # 1. Missing profile
    res_no_prof = await client.post(
        "/api/v1/therapists/request",
        json={"doctor_id": "doc-1234-uuid"},
        headers={"X-Patient-UID": "user_without_profile"}
    )
    assert res_no_prof.status_code == 404

    # 2. Missing doctor
    headers = {"X-Patient-UID": "user_with_prof_bad_doc"}
    await client.post("/api/v1/profiles", json={"parent_name": "P", "child_name": "C"}, headers=headers)
    res_bad_doc = await client.post(
        "/api/v1/therapists/request",
        json={"doctor_id": "nonexistent-doc-id"},
        headers=headers
    )
    assert res_bad_doc.status_code == 404
