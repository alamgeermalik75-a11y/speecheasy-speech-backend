import pytest

@pytest.mark.asyncio
async def test_get_daily_tips(client):
    res = await client.get("/api/v1/daily-tips")
    assert res.status_code == 200
    tips = res.json()
    assert len(tips) >= 1
    assert "tip_text" in tips[0]
    assert tips[0]["sort_order"] == 1

@pytest.mark.asyncio
async def test_ratings_lifecycle_and_average(client):
    doctor_id = "doc-1234-uuid"

    # User 1 sets up profile
    await client.post(
        "/api/v1/profiles",
        json={"parent_name": "P1", "child_name": "C1"},
        headers={"X-Patient-UID": "user_r1"}
    )

    # User 1 submits rating 5
    res1 = await client.post(
        "/api/v1/ratings",
        json={"doctor_id": doctor_id, "rating": 5},
        headers={"X-Patient-UID": "user_r1"}
    )
    assert res1.status_code == 200
    assert res1.json()["new_average_rating"] == 5.0

    # User 1 queries own rating
    my_r = await client.get(f"/api/v1/ratings/{doctor_id}/my-rating", headers={"X-Patient-UID": "user_r1"})
    assert my_r.json()["rating"] == 5

    # User 2 sets up profile and rates 3
    await client.post(
        "/api/v1/profiles",
        json={"parent_name": "P2", "child_name": "C2"},
        headers={"X-Patient-UID": "user_r2"}
    )
    res2 = await client.post(
        "/api/v1/ratings",
        json={"doctor_id": doctor_id, "rating": 3},
        headers={"X-Patient-UID": "user_r2"}
    )
    assert res2.status_code == 200
    # Average of 5 and 3 should be 4.0
    assert res2.json()["new_average_rating"] == 4.0

    # User 1 updates rating from 5 to 1 (Upsert test)
    res1_updated = await client.post(
        "/api/v1/ratings",
        json={"doctor_id": doctor_id, "rating": 1},
        headers={"X-Patient-UID": "user_r1"}
    )
    assert res1_updated.status_code == 200
    # Average of 1 and 3 should be 2.0
    assert res1_updated.json()["new_average_rating"] == 2.0

@pytest.mark.asyncio
async def test_ratings_bounds_validation(client):
    headers = {"X-Patient-UID": "user_r_bounds"}

    # Rating 0 is invalid
    res_zero = await client.post("/api/v1/ratings", json={"doctor_id": "doc-1234-uuid", "rating": 0}, headers=headers)
    assert res_zero.status_code == 422

    # Rating 6 is invalid
    res_six = await client.post("/api/v1/ratings", json={"doctor_id": "doc-1234-uuid", "rating": 6}, headers=headers)
    assert res_six.status_code == 422
