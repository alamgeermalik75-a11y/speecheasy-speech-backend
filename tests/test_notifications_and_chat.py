import pytest

@pytest.mark.asyncio
async def test_notifications_crud_and_isolation(client):
    headers1 = {"X-Patient-UID": "user_notif_1"}
    headers2 = {"X-Patient-UID": "user_notif_2"}

    # Setup profiles
    await client.post("/api/v1/profiles", json={"parent_name": "P1", "child_name": "C1"}, headers=headers1)
    await client.post("/api/v1/profiles", json={"parent_name": "P2", "child_name": "C2"}, headers=headers2)

    # User 1 performs attempt that generates notification
    await client.post(
        "/api/v1/attempts",
        json={"item_id": "i1", "alphabet_name": "bay", "level_key": "words", "score": 85},
        headers=headers1
    )

    # 1. User 1 has 1 unread notification
    count1 = (await client.get("/api/v1/notifications/unread-count", headers=headers1)).json()
    assert count1["count"] == 1

    # 2. User 2 has 0 notifications (Cross-user isolation)
    count2 = (await client.get("/api/v1/notifications/unread-count", headers=headers2)).json()
    assert count2["count"] == 0

    # 3. Mark all read for User 1
    mark_res = await client.patch("/api/v1/notifications/mark-read", headers=headers1)
    assert mark_res.status_code == 200
    assert mark_res.json()["count"] == 1

    count1_after = (await client.get("/api/v1/notifications/unread-count", headers=headers1)).json()
    assert count1_after["count"] == 0

    # 4. Clear all notifications for User 1
    del_res = await client.delete("/api/v1/notifications", headers=headers1)
    assert del_res.status_code == 200
    assert del_res.json()["count"] == 1

    notifs1 = (await client.get("/api/v1/notifications", headers=headers1)).json()
    assert len(notifs1) == 0

@pytest.mark.asyncio
async def test_chat_endpoint_validation_and_reply(client):
    headers = {"X-Patient-UID": "user_chat"}

    # 1. Empty message -> 422
    empty_res = await client.post("/api/v1/chat", json={"message": "   "}, headers=headers)
    assert empty_res.status_code == 422

    # 2. >1000 characters -> 422
    long_res = await client.post("/api/v1/chat", json={"message": "a" * 1005}, headers=headers)
    assert long_res.status_code == 422

    # 3. Valid question -> 200 with reply
    res = await client.post(
        "/api/v1/chat",
        json={"message": "How do I help my child pronounce the letter Bay?"},
        headers=headers
    )
    assert res.status_code == 200
    assert "reply" in res.json()
    assert len(res.json()["reply"]) > 10

@pytest.mark.asyncio
async def test_health_endpoints(client):
    # Liveness probe
    live = await client.get("/health")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"

    # Readiness probe
    ready = await client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
