import pytest

@pytest.mark.asyncio
async def test_create_and_read_profile(client):
    headers = {"X-Patient-UID": "user_abc"}

    # Create profile
    payload = {
        "parent_name": "Fatima",
        "child_name": "Ahmad",
        "phone": "+92 300 1234567",
        "sound": "ب",
        "alphabet_name": "bay"
    }
    create_res = await client.post("/api/v1/profiles", json=payload, headers=headers)
    assert create_res.status_code == 201
    data = create_res.json()
    assert data["patient_uid"] == "user_abc"
    assert data["child_name"] == "Ahmad"
    assert data["focus_sound"]["sound"] == "ب"
    assert data["focus_sound"]["progress"] == 0.0

    # Read own profile
    read_res = await client.get("/api/v1/profiles/me", headers=headers)
    assert read_res.status_code == 200
    assert read_res.json()["child_name"] == "Ahmad"

@pytest.mark.asyncio
async def test_cross_user_profile_isolation(client):
    # User 1 creates profile
    await client.post(
        "/api/v1/profiles",
        json={"parent_name": "Mother 1", "child_name": "Child 1"},
        headers={"X-Patient-UID": "user_1"}
    )

    # User 2 queries /me -> must get 404 because user_2 has no profile
    res = await client.get("/api/v1/profiles/me", headers={"X-Patient-UID": "user_2"})
    assert res.status_code == 404

@pytest.mark.asyncio
async def test_update_profile_preserves_focus_sound_progress(client):
    headers = {"X-Patient-UID": "user_progress_test"}

    # 1. Create initial profile
    await client.post(
        "/api/v1/profiles",
        json={"parent_name": "Father", "child_name": "Zaid", "sound": "ب", "alphabet_name": "bay"},
        headers=headers
    )

    # 2. Simulate some progress via an attempt
    await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_0", "alphabet_name": "bay", "level_key": "words", "score": 85},
        headers=headers
    )

    # Verify progress > 0
    prof = (await client.get("/api/v1/profiles/me", headers=headers)).json()
    prev_progress = prof["focus_sound"]["progress"]
    assert prev_progress > 0

    # 3. Update profile names
    update_res = await client.put(
        "/api/v1/profiles",
        json={"parent_name": "Father Updated", "child_name": "Zaid Updated", "sound": "ب", "alphabet_name": "bay"},
        headers=headers
    )
    assert update_res.status_code == 200
    updated_data = update_res.json()
    assert updated_data["child_name"] == "Zaid Updated"
    # Ensure progress was preserved!
    assert updated_data["focus_sound"]["progress"] == prev_progress

@pytest.mark.asyncio
async def test_delete_profile_cascade(client):
    headers = {"X-Patient-UID": "user_delete_test"}

    # Create profile
    await client.post(
        "/api/v1/profiles",
        json={"parent_name": "Parent", "child_name": "Child", "sound": "ب", "alphabet_name": "bay"},
        headers=headers
    )

    # Delete profile
    del_res = await client.delete("/api/v1/profiles/me", headers=headers)
    assert del_res.status_code == 204

    # Verify profile is gone
    check_res = await client.get("/api/v1/profiles/me", headers=headers)
    assert check_res.status_code == 404
