import pytest

@pytest.mark.asyncio
async def test_attempt_score_validation(client):
    headers = {"X-Patient-UID": "user_att_val"}
    # Score 105 invalid
    res_high = await client.post(
        "/api/v1/attempts",
        json={"item_id": "item_1", "alphabet_name": "alif", "level_key": "words", "score": 105},
        headers=headers
    )
    assert res_high.status_code == 422

    # Score -1 invalid
    res_low = await client.post(
        "/api/v1/attempts",
        json={"item_id": "item_1", "alphabet_name": "alif", "level_key": "words", "score": -1},
        headers=headers
    )
    assert res_low.status_code == 422

    # Invalid level_key rejected
    res_bad_lvl = await client.post(
        "/api/v1/attempts",
        json={"item_id": "item_1", "alphabet_name": "alif", "level_key": "invalid_level", "score": 80},
        headers=headers
    )
    assert res_bad_lvl.status_code == 422

    # Score 0 is valid
    res_zero = await client.post(
        "/api/v1/attempts",
        json={"item_id": "item_0", "alphabet_name": "alif", "level_key": "words", "score": 0},
        headers=headers
    )
    assert res_zero.status_code == 201

    # Score 100 is valid
    res_hundred = await client.post(
        "/api/v1/attempts",
        json={"item_id": "item_100", "alphabet_name": "alif", "level_key": "words", "score": 100},
        headers=headers
    )
    assert res_hundred.status_code == 201

@pytest.mark.asyncio
async def test_attempt_achievement_notification_and_history(client):
    headers = {"X-Patient-UID": "user_att_prog"}

    # Setup profile with focus sound 'alif'
    await client.post(
        "/api/v1/profiles",
        json={"parent_name": "Parent", "child_name": "Kid", "sound": "ا", "alphabet_name": "alif"},
        headers=headers
    )

    # 1. Log attempt with score 80 (>= 70)
    att_res = await client.post(
        "/api/v1/attempts",
        json={"item_id": "alif_w_1", "alphabet_name": "alif", "level_key": "words", "score": 80},
        headers=headers
    )
    assert att_res.status_code == 201
    data = att_res.json()
    assert data["attempt"]["score"] == 80
    assert "Nice work" in data["milestone_notification"]

    # 2. Check notification in list
    notifs = (await client.get("/api/v1/notifications", headers=headers)).json()
    assert len(notifs) >= 1
    assert "Score: 80%" in notifs[0]["message"]

    # 3. Check history endpoint
    hist_res = await client.get("/api/v1/attempts/history?alphabet_name=alif", headers=headers)
    assert hist_res.status_code == 200
    assert len(hist_res.json()) == 1

@pytest.mark.asyncio
async def test_alphabet_mastery_advances_focus_sound(client):
    headers = {"X-Patient-UID": "user_mastery"}

    # Setup profile starting with 'alif' (names >= 2 chars)
    prof_res = await client.post(
        "/api/v1/profiles",
        json={"parent_name": "Parent User", "child_name": "Child User", "sound": "ا", "alphabet_name": "alif"},
        headers=headers
    )
    assert prof_res.status_code == 201

    # Submit 4 unique passing items across all 5 levels to reach authentic 100% completion
    levels = ["words", "sentences", "fillBlanks", "poems", "story"]
    last_res = None
    for lvl in levels:
        for i in range(4):
            last_res = await client.post(
                "/api/v1/attempts",
                json={"item_id": f"alif_{lvl}_{i}", "alphabet_name": "alif", "level_key": lvl, "score": 90},
                headers=headers
            )

    assert last_res.status_code == 201
    result = last_res.json()
    # Check sound was mastered!
    assert result["sound_mastered"] is True
    # Next sound in sequence after 'alif' is 'bay' ('ب')
    assert result["next_sound"] == "bay"

    # Verify profile now reflects next sound 'bay'
    profile = (await client.get("/api/v1/profiles/me", headers=headers)).json()
    assert profile["focus_sound"]["alphabet_name"] == "bay"
    assert profile["focus_sound"]["sound"] == "ب"
    assert profile["focus_sound"]["progress"] == 0.0
