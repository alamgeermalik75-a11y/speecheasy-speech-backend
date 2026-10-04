import pytest
from datetime import datetime, timezone, timedelta
from app.curriculum.curriculum_manager import curriculum_manager, URDU_ALPHABET_SEQUENCE, CATEGORY_ORDER

@pytest.mark.asyncio
async def test_attempt_score_validation(client):
    headers = {"X-Patient-UID": "user_att_val"}
    # Score 105 invalid
    res_high = await client.post(
        "/api/v1/attempts",
        json={"item_id": "item_1", "alphabet_name": "bay", "level_key": "words", "score": 105},
        headers=headers
    )
    assert res_high.status_code == 422

    # Score -1 invalid
    res_low = await client.post(
        "/api/v1/attempts",
        json={"item_id": "item_1", "alphabet_name": "bay", "level_key": "words", "score": -1},
        headers=headers
    )
    assert res_low.status_code == 422

    # Invalid level_key rejected
    res_bad_lvl = await client.post(
        "/api/v1/attempts",
        json={"item_id": "item_1", "alphabet_name": "bay", "level_key": "invalid_level", "score": 80},
        headers=headers
    )
    assert res_bad_lvl.status_code == 422

    # Score 0 is valid
    res_zero = await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 0},
        headers=headers
    )
    assert res_zero.status_code == 201

    # Score 100 is valid
    res_hundred = await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_1", "alphabet_name": "bay", "level_key": "words", "score": 100},
        headers=headers
    )
    assert res_hundred.status_code == 201


@pytest.mark.asyncio
async def test_unique_item_and_score_rules(client):
    """
    Covers:
    TEST 1 — UNIQUE ITEM: score 60 -> 1 record, best_score=60, is_passed=false
    TEST 2 — HIGHER SCORE: 60 -> 80 -> same record, best_score=80, is_passed=true
    TEST 3 — LOWER SCORE: 80 -> 70 -> best_score remains 80
    TEST 4 — SAME SCORE: 80 -> 80 -> best_score remains 80
    TEST 5 — HIGHER AGAIN: 80 -> 100 -> best_score=100
    TEST 6 — DUPLICATE SUBMISSION: 100 -> 100 -> no progress increase, no duplicate record
    """
    headers = {"X-Patient-UID": "user_test_unique_rules"}
    item_id = "bay_initial_0"
    alpha = "bay"
    lvl = "words"

    # TEST 1: New unique item with score 60
    r1 = await client.post(
        "/api/v1/attempts",
        json={"item_id": item_id, "alphabet_name": alpha, "level_key": lvl, "score": 60},
        headers=headers
    )
    assert r1.status_code == 201
    d1 = r1.json()
    assert d1["attempt"]["score"] == 60
    assert d1["improved"] is True
    assert d1["progress_earned"] == 60

    # Verify history has exactly 1 record
    hist1 = (await client.get(f"/api/v1/attempts/history?alphabet_name={alpha}&level_key={lvl}", headers=headers)).json()
    assert len(hist1) == 1
    assert hist1[0]["score"] == 60

    # TEST 2: Higher score (60 -> 80)
    r2 = await client.post(
        "/api/v1/attempts",
        json={"item_id": item_id, "alphabet_name": alpha, "level_key": lvl, "score": 80},
        headers=headers
    )
    assert r2.status_code == 201
    d2 = r2.json()
    assert d2["attempt"]["score"] == 80
    assert d2["improved"] is True
    assert d2["progress_earned"] == 20
    # Must still be only 1 record
    hist2 = (await client.get(f"/api/v1/attempts/history?alphabet_name={alpha}&level_key={lvl}", headers=headers)).json()
    assert len(hist2) == 1
    assert hist2[0]["score"] == 80

    # TEST 3: Lower score (80 -> 70)
    r3 = await client.post(
        "/api/v1/attempts",
        json={"item_id": item_id, "alphabet_name": alpha, "level_key": lvl, "score": 70},
        headers=headers
    )
    assert r3.status_code == 201
    d3 = r3.json()
    assert d3["attempt"]["score"] == 80  # Remains 80!
    assert d3["improved"] is False
    assert d3["progress_earned"] == 0
    hist3 = (await client.get(f"/api/v1/attempts/history?alphabet_name={alpha}&level_key={lvl}", headers=headers)).json()
    assert len(hist3) == 1
    assert hist3[0]["score"] == 80

    # TEST 4: Same score (80 -> 80)
    r4 = await client.post(
        "/api/v1/attempts",
        json={"item_id": item_id, "alphabet_name": alpha, "level_key": lvl, "score": 80},
        headers=headers
    )
    assert r4.status_code == 201
    d4 = r4.json()
    assert d4["attempt"]["score"] == 80
    assert d4["improved"] is False
    assert d4["progress_earned"] == 0

    # TEST 5: Higher again (80 -> 100)
    r5 = await client.post(
        "/api/v1/attempts",
        json={"item_id": item_id, "alphabet_name": alpha, "level_key": lvl, "score": 100},
        headers=headers
    )
    assert r5.status_code == 201
    d5 = r5.json()
    assert d5["attempt"]["score"] == 100
    assert d5["improved"] is True
    assert d5["progress_earned"] == 20

    # TEST 6: Duplicate submission (100 -> 100)
    r6 = await client.post(
        "/api/v1/attempts",
        json={"item_id": item_id, "alphabet_name": alpha, "level_key": lvl, "score": 100},
        headers=headers
    )
    assert r6.status_code == 201
    d6 = r6.json()
    assert d6["attempt"]["score"] == 100
    assert d6["improved"] is False
    assert d6["progress_earned"] == 0
    hist6 = (await client.get(f"/api/v1/attempts/history?alphabet_name={alpha}&level_key={lvl}", headers=headers)).json()
    assert len(hist6) == 1


@pytest.mark.asyncio
async def test_category_gating_and_calculation(client):
    """
    Covers:
    TEST 7 — CATEGORY CALCULATION: real item count, 20% weighting
    TEST 8 — CATEGORY LOCK: incomplete category keeps next category locked
    TEST 9 — CATEGORY UNLOCK: all items >= 70 unlocks next category
    """
    headers = {"X-Patient-UID": "user_category_gating"}
    alpha = "bay"
    word_items = curriculum_manager.get_category_items(alpha, "words")
    total_words = len(word_items)
    assert total_words > 0

    # Initial overview: Words is unlocked, Sentences is locked
    ov0 = (await client.get(f"/api/v1/attempts/overview?alphabet_name={alpha}", headers=headers)).json()
    assert ov0["categories"]["words"]["is_unlocked"] is True
    assert ov0["categories"]["sentences"]["is_unlocked"] is False

    # TEST 8: Submit score 100 for all items EXCEPT the last one (remains unpracticed / < 70)
    for it in word_items[:-1]:
        await client.post(
            "/api/v1/attempts",
            json={"item_id": it, "alphabet_name": alpha, "level_key": "words", "score": 100},
            headers=headers
        )

    # Submit 65 (< 70) for the last word item
    last_item = word_items[-1]
    res_last = await client.post(
        "/api/v1/attempts",
        json={"item_id": last_item, "alphabet_name": alpha, "level_key": "words", "score": 65},
        headers=headers
    )
    assert res_last.status_code == 201

    # Check overview: Words is NOT completed, Sentences is still locked
    ov1 = (await client.get(f"/api/v1/attempts/overview?alphabet_name={alpha}", headers=headers)).json()
    assert ov1["categories"]["words"]["is_completed"] is False
    assert ov1["categories"]["sentences"]["is_unlocked"] is False

    # TEST 7: Check category score percentage formula:
    # (sum_best_scores / (total_words * 100)) * 100
    expected_sum = (total_words - 1) * 100 + 65
    expected_pct = round((expected_sum / (total_words * 100)) * 100, 2)
    assert ov1["categories"]["words"]["score_percentage"] == expected_pct

    # TEST 9: Improve last item to 80 (>= 70) -> Words becomes complete, Sentences unlocks!
    res_unlock = await client.post(
        "/api/v1/attempts",
        json={"item_id": last_item, "alphabet_name": alpha, "level_key": "words", "score": 80},
        headers=headers
    )
    assert res_unlock.status_code == 201
    ov2 = (await client.get(f"/api/v1/attempts/overview?alphabet_name={alpha}", headers=headers)).json()
    assert ov2["categories"]["words"]["is_completed"] is True
    assert ov2["categories"]["sentences"]["is_unlocked"] is True


@pytest.mark.asyncio
async def test_patient_isolation(client):
    """
    Covers:
    TEST 16 — OWNERSHIP: Patient A cannot see or modify Patient B's progress.
    """
    user_a = {"X-Patient-UID": "patient_alpha_1"}
    user_b = {"X-Patient-UID": "patient_beta_2"}

    # User A records score 90
    await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 90},
        headers=user_a
    )

    # User B checks history: must be empty
    hist_b = (await client.get("/api/v1/attempts/history?alphabet_name=bay", headers=user_b)).json()
    assert len(hist_b) == 0

    # User B checks overview: 0% overall progress
    ov_b = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=user_b)).json()
    assert ov_b["overall_progress"] == 0.0


@pytest.mark.asyncio
async def test_alphabet_completion_and_next_sound(client):
    """
    Covers:
    TEST 10 — ALPHABET COMPLETION: all 5 categories complete -> Alphabet = 100%, next alphabet unlocks
    TEST 11 — OVERALL PROGRESS: progress across multiple alphabets
    """
    headers = {"X-Patient-UID": "user_alphabet_completion"}
    alpha = "bay"

    # Setup profile starting with 'bay'
    await client.post(
        "/api/v1/profiles",
        json={"parent_name": "Parent User", "child_name": "Child User", "phone": "+923001234567", "sound": "ب", "alphabet_name": "bay"},
        headers=headers
    )

    # Complete all items across all 5 categories for 'bay'
    last_res = None
    for lvl in CATEGORY_ORDER:
        items = curriculum_manager.get_category_items(alpha, lvl)
        for it in items:
            last_res = await client.post(
                "/api/v1/attempts",
                json={"item_id": it, "alphabet_name": alpha, "level_key": lvl, "score": 100},
                headers=headers
            )

    assert last_res is not None
    assert last_res.status_code == 201
    d = last_res.json()
    assert d["sound_mastered"] is True
    assert d["next_sound"] == "pay"

    # Verify overview for 'bay' is 100%
    ov_bay = (await client.get(f"/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()
    assert ov_bay["alphabet_progress"] == 100.0

    # Practice first item of next alphabet 'pay'
    res_pay = await client.post(
        "/api/v1/attempts",
        json={"item_id": "pay_initial_0", "alphabet_name": "pay", "level_key": "words", "score": 90},
        headers=headers
    )
    assert res_pay.status_code == 201
    # Verify overall progress preserves bay (100%) + pay progress
    ov_pay = (await client.get(f"/api/v1/attempts/overview?alphabet_name=pay", headers=headers)).json()
    assert ov_pay["overall_progress"] > 0.0


@pytest.mark.asyncio
async def test_daily_and_weekly_progress(client):
    """
    Covers:
    TEST 12 — DAILY PROGRESS: genuine score improvements contribute
    TEST 13 — WEEKLY PROGRESS: genuine score improvements contribute
    """
    headers = {"X-Patient-UID": "user_analytics_daily"}

    # 1. First practice: score 60
    r1 = await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 60},
        headers=headers
    )
    assert r1.status_code == 201
    ov1 = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()
    assert ov1["daily_progress"] == 60
    assert ov1["weekly_progress"] == 60

    # 2. Same score (60 -> 60): daily progress does NOT increase
    r2 = await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 60},
        headers=headers
    )
    assert r2.status_code == 201
    ov2 = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()
    assert ov2["daily_progress"] == 60

    # 3. Improvement (60 -> 85): daily progress increases by +25
    r3 = await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 85},
        headers=headers
    )
    assert r3.status_code == 201
    ov3 = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()
    assert ov3["daily_progress"] == 85
    assert ov3["weekly_progress"] == 85
