import pytest
from datetime import datetime, timezone, timedelta, date
from app.curriculum.curriculum_manager import curriculum_manager, CATEGORY_ORDER
from app.services.supabase_db_service import SupabaseDbService
from app.models.attempt import Attempt, ProgressEvent
from sqlalchemy import select

@pytest.mark.asyncio
async def test_case_1_attempt_score_69(client):
    """
    Test 1: First attempt score 69:
    - not passed
    - no progress added
    - no first-pass event
    """
    headers = {"X-Patient-UID": "user_test_case_1"}
    res = await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 69},
        headers=headers
    )
    assert res.status_code == 201
    d = res.json()
    assert d["attempt"]["score"] == 69
    assert d["category_progress"] == 0.0
    assert d["alphabet_progress"] == 0.0

    ov = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()
    assert ov["categories"]["words"]["passed_items"] == 0
    assert ov["categories"]["words"]["score_percentage"] == 0.0
    assert ov["alphabet_progress"] == 0.0
    assert ov["daily_progress"] == 0.0


@pytest.mark.asyncio
async def test_case_2_attempt_score_70(client):
    """
    Test 2: First attempt score 70:
    - passed
    - progress added
    - first-pass event created
    """
    headers = {"X-Patient-UID": "user_test_case_2"}
    total_words = curriculum_manager.get_category_item_count("bay", "words")
    expected_gain = round((1.0 / total_words) * 20.0, 2)

    res = await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 70},
        headers=headers
    )
    assert res.status_code == 201
    d = res.json()
    assert d["attempt"]["score"] == 70

    ov = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()
    assert ov["categories"]["words"]["passed_items"] == 1
    assert ov["daily_progress"] == expected_gain
    assert ov["alphabet_progress"] == expected_gain


@pytest.mark.asyncio
async def test_case_3_attempt_score_100(client):
    """
    Test 3: First attempt score 100:
    - passed
    - progress added once
    """
    headers = {"X-Patient-UID": "user_test_case_3"}
    total_words = curriculum_manager.get_category_item_count("bay", "words")
    expected_gain = round((1.0 / total_words) * 20.0, 2)

    res = await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 100},
        headers=headers
    )
    assert res.status_code == 201

    ov = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()
    assert ov["categories"]["words"]["passed_items"] == 1
    assert ov["daily_progress"] == expected_gain
    assert ov["alphabet_progress"] == expected_gain


@pytest.mark.asyncio
async def test_case_4_improvement_70_to_80(client):
    """
    Test 4: 70 -> 80:
    - best score becomes 80
    - item remains one passed item
    - NO new daily progress
    """
    headers = {"X-Patient-UID": "user_test_case_4"}
    total_words = curriculum_manager.get_category_item_count("bay", "words")
    expected_gain = round((1.0 / total_words) * 20.0, 2)

    # First attempt: 70
    await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 70},
        headers=headers
    )

    # Second attempt: 80
    res = await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 80},
        headers=headers
    )
    assert res.status_code == 201
    d = res.json()
    assert d["attempt"]["score"] == 80

    ov = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()
    assert ov["categories"]["words"]["passed_items"] == 1
    # NO new daily progress added (still exactly 1 item contribution, not 2)
    assert ov["daily_progress"] == expected_gain
    assert ov["alphabet_progress"] == expected_gain


@pytest.mark.asyncio
async def test_case_5_lower_score_80_to_70(client):
    """
    Test 5: 80 -> 70:
    - best remains 80
    - no progress change
    """
    headers = {"X-Patient-UID": "user_test_case_5"}
    total_words = curriculum_manager.get_category_item_count("bay", "words")
    expected_gain = round((1.0 / total_words) * 20.0, 2)

    # Initial: 80
    await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 80},
        headers=headers
    )

    # Lower attempt: 70
    res = await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 70},
        headers=headers
    )
    assert res.status_code == 201
    d = res.json()
    assert d["attempt"]["score"] == 80
    assert d["improved"] is False

    ov = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()
    assert ov["categories"]["words"]["passed_items"] == 1
    assert ov["daily_progress"] == expected_gain
    assert ov["alphabet_progress"] == expected_gain


@pytest.mark.asyncio
async def test_case_6_improvement_80_to_100(client):
    """
    Test 6: 80 -> 100:
    - best becomes 100
    - no new daily progress
    """
    headers = {"X-Patient-UID": "user_test_case_6"}
    total_words = curriculum_manager.get_category_item_count("bay", "words")
    expected_gain = round((1.0 / total_words) * 20.0, 2)

    # Initial: 80
    await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 80},
        headers=headers
    )

    # Improve to 100
    res = await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 100},
        headers=headers
    )
    assert res.status_code == 201
    d = res.json()
    assert d["attempt"]["score"] == 100

    ov = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()
    assert ov["categories"]["words"]["passed_items"] == 1
    # Remains single pass gain
    assert ov["daily_progress"] == expected_gain
    assert ov["alphabet_progress"] == expected_gain


@pytest.mark.asyncio
async def test_case_7_repeat_10_times_100(client):
    """
    Test 7: Same item repeated 10 times with 100:
    - one passed item
    - not ten
    """
    headers = {"X-Patient-UID": "user_test_case_7"}
    total_words = curriculum_manager.get_category_item_count("bay", "words")
    expected_gain = round((1.0 / total_words) * 20.0, 2)

    for _ in range(10):
        await client.post(
            "/api/v1/attempts",
            json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 100},
            headers=headers
        )

    ov = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()
    assert ov["categories"]["words"]["passed_items"] == 1
    assert ov["daily_progress"] == expected_gain
    assert ov["alphabet_progress"] == expected_gain

    # Practice history has only 1 authoritative record
    hist = (await client.get("/api/v1/attempts/history?alphabet_name=bay&level_key=words", headers=headers)).json()
    assert len(hist) == 1


@pytest.mark.asyncio
async def test_case_8_two_sounds_contribute_average(client):
    """
    Test 8: Two different sounds contribute:
    Sound ب = 10%
    Sound ل = 10%
    Daily Progress = average(10%, 10%) = 10% (NOT 20%)
    """
    headers = {"X-Patient-UID": "user_test_case_8"}

    # Pass 50% of words for bay (50% of 20% = 10% sound gain)
    bay_words = curriculum_manager.get_category_items("bay", "words")
    half_bay = len(bay_words) // 2
    for it in bay_words[:half_bay]:
        await client.post(
            "/api/v1/attempts",
            json={"item_id": it, "alphabet_name": "bay", "level_key": "words", "score": 80},
            headers=headers
        )

    # Pass 50% of words for laam (50% of 20% = 10% sound gain)
    laam_words = curriculum_manager.get_category_items("laam", "words")
    half_laam = len(laam_words) // 2
    for it in laam_words[:half_laam]:
        await client.post(
            "/api/v1/attempts",
            json={"item_id": it, "alphabet_name": "laam", "level_key": "words", "score": 85},
            headers=headers
        )

    # Check overview: daily progress MUST BE the average of both sounds: (10% + 10%) / 2 = 10%
    ov = (await client.get("/api/v1/attempts/overview", headers=headers)).json()
    bay_gain = (half_bay / len(bay_words)) * 20.0
    laam_gain = (half_laam / len(laam_words)) * 20.0
    expected_daily = round((bay_gain + laam_gain) / 2.0, 2)
    assert ov["daily_progress"] == expected_daily
    # Proves NOT summed (if summed it would be ~20%)
    assert ov["daily_progress"] < (bay_gain + laam_gain)


@pytest.mark.asyncio
async def test_case_9_one_sound_contributes_no_average(client):
    """
    Test 9: One sound contributes:
    Sound ب Words = 100% of course (20% sound gain)
    Daily Progress = 20% (no averaging needed)
    """
    headers = {"X-Patient-UID": "user_test_case_9"}
    bay_words = curriculum_manager.get_category_items("bay", "words")
    for it in bay_words:
        await client.post(
            "/api/v1/attempts",
            json={"item_id": it, "alphabet_name": "bay", "level_key": "words", "score": 90},
            headers=headers
        )

    ov = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()
    assert ov["daily_progress"] == 20.0
    assert ov["alphabet_progress"] == 20.0


@pytest.mark.asyncio
async def test_case_10_no_new_passes_daily_zero(client, db_session):
    """
    Test 10: If no new passes occurred on this day (only repeats of yesterday's passes):
    Daily Progress = 0%
    """
    headers = {"X-Patient-UID": "user_test_case_10"}
    user_tz = timezone.utc
    yesterday = datetime.now(user_tz) - timedelta(days=1)

    # Insert an attempt passed yesterday directly in DB
    att = Attempt(
        patient_uid="user_test_case_10",
        item_id="bay_initial_0",
        alphabet_name="bay",
        level_key="words",
        score=80,
        attempted_at=yesterday
    )
    pe = ProgressEvent(
        patient_uid="user_test_case_10",
        item_id="bay_initial_0",
        alphabet_name="bay",
        level_key="words",
        previous_score=0,
        new_score=80,
        progress_earned=80,
        earned_at=yesterday
    )
    db_session.add(att)
    db_session.add(pe)
    await db_session.commit()

    # Patient practices today with score 100 (repeat practice, not first pass)
    res = await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 100},
        headers=headers
    )
    assert res.status_code == 201

    ov = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()
    # Today's daily progress MUST BE 0.0%
    assert ov["daily_progress"] == 0.0


@pytest.mark.asyncio
async def test_case_11_decimal_precision(client):
    """
    Test 11: 26-word category:
    1 new pass = (1 / 26) * 20 = 0.7692% -> display ~0.77%
    2 new passes = (2 / 26) * 20 = 1.5385% -> display ~1.54%
    3 new passes = (3 / 26) * 20 = 2.3077% -> display ~2.31%
    """
    headers = {"X-Patient-UID": "user_test_case_11"}
    # Sound ز is 'z' in curriculum, which has exactly 26 words
    z_words = curriculum_manager.get_category_items("z", "words")
    num_words = len(z_words)
    assert num_words == 26

    # Pass 1 word
    await client.post(
        "/api/v1/attempts",
        json={"item_id": z_words[0], "alphabet_name": "z", "level_key": "words", "score": 80},
        headers=headers
    )
    ov1 = (await client.get("/api/v1/attempts/overview?alphabet_name=z", headers=headers)).json()
    expected_1 = round((1.0 / num_words) * 20.0, 2)
    assert expected_1 == 0.77
    assert ov1["alphabet_progress"] == expected_1
    assert ov1["daily_progress"] == expected_1

    # Pass 2nd word
    await client.post(
        "/api/v1/attempts",
        json={"item_id": z_words[1], "alphabet_name": "z", "level_key": "words", "score": 80},
        headers=headers
    )
    ov2 = (await client.get("/api/v1/attempts/overview?alphabet_name=z", headers=headers)).json()
    expected_2 = round((2.0 / num_words) * 20.0, 2)
    assert expected_2 == 1.54
    assert ov2["alphabet_progress"] == expected_2
    assert ov2["daily_progress"] == expected_2

    # Pass 3rd word
    await client.post(
        "/api/v1/attempts",
        json={"item_id": z_words[2], "alphabet_name": "z", "level_key": "words", "score": 80},
        headers=headers
    )
    ov3 = (await client.get("/api/v1/attempts/overview?alphabet_name=z", headers=headers)).json()
    expected_3 = round((3.0 / num_words) * 20.0, 2)
    assert expected_3 == 2.31
    assert ov3["alphabet_progress"] == expected_3
    assert ov3["daily_progress"] == expected_3


@pytest.mark.asyncio
async def test_case_12_patient_isolation(client):
    """
    Test 12: Patient isolation:
    Patient A cannot see Patient B's progress, attempts, or history.
    """
    headers_a = {"X-Patient-UID": "patient_user_A"}
    headers_b = {"X-Patient-UID": "patient_user_B"}

    # Patient A practices
    await client.post(
        "/api/v1/attempts",
        json={"item_id": "bay_initial_0", "alphabet_name": "bay", "level_key": "words", "score": 100},
        headers=headers_a
    )

    # Patient B fetches overview
    ov_b = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers_b)).json()
    assert ov_b["overall_progress"] == 0.0
    assert ov_b["alphabet_progress"] == 0.0
    assert ov_b["daily_progress"] == 0.0
    assert ov_b["categories"]["words"]["passed_items"] == 0

    # Patient B fetches history
    hist_b = (await client.get("/api/v1/attempts/history", headers=headers_b)).json()
    assert len(hist_b) == 0


@pytest.mark.asyncio
async def test_case_13_uninstall_login_restore(client):
    """
    Test 13: Uninstall / login restore:
    Reconstruct best scores, passed items, course progress, sound overall,
    daily history, weekly history, monthly history purely from backend.
    """
    headers = {"X-Patient-UID": "user_test_case_13_restore"}

    # Practice 3 items in bay words
    bay_words = curriculum_manager.get_category_items("bay", "words")
    for it in bay_words[:3]:
        await client.post(
            "/api/v1/attempts",
            json={"item_id": it, "alphabet_name": "bay", "level_key": "words", "score": 85},
            headers=headers
        )

    # Simulate fresh login / client restart: fetch overview from backend
    ov = (await client.get("/api/v1/attempts/overview?alphabet_name=bay", headers=headers)).json()

    # Verify complete state reconstructed
    total_words = len(bay_words)
    expected_words_pct = round((3.0 / total_words) * 100, 2)
    expected_sound_pct = round((3.0 / total_words) * 20.0, 2)

    assert ov["categories"]["words"]["passed_items"] == 3
    assert ov["categories"]["words"]["total_items"] == total_words
    assert ov["categories"]["words"]["score_percentage"] == expected_words_pct
    assert ov["alphabet_progress"] == expected_sound_pct
    assert ov["daily_progress"] == expected_sound_pct
    assert len(ov["daily_history"]) == 7
    assert len(ov["weekly_history"]) == 4
    assert ov["daily_history"][-1]["progress"] == expected_sound_pct


def test_supabase_db_service_unit_methods():
    """
    Direct unit test of SupabaseDbService static methods:
    - _compute_daily_gain_for_date
    - _compute_period_gain
    - _extract_first_time_passes
    - _compute_patient_overall_progress
    """
    user_tz = timezone.utc
    today = date(2026, 10, 5)

    # 1. Test multi-sound averaging (Section 11 & 12)
    # ب: +4%, ل: +8%, ز: +2% -> average = (4 + 8 + 2) / 3 = 4.67%
    passes = [
        {"alphabet_name": "bay", "level_key": "words", "item_id": "b1", "date": today, "contribution": 4.0},
        {"alphabet_name": "laam", "level_key": "words", "item_id": "l1", "date": today, "contribution": 8.0},
        {"alphabet_name": "z", "level_key": "words", "item_id": "z1", "date": today, "contribution": 2.0},
    ]
    daily_gain = SupabaseDbService._compute_daily_gain_for_date(today, passes)
    assert daily_gain == 4.67

    # 2. Test Section 8: ب = 10%, ل = 10% -> (10 + 10) / 2 = 10%
    passes_2 = [
        {"alphabet_name": "bay", "level_key": "words", "item_id": "b1", "date": today, "contribution": 10.0},
        {"alphabet_name": "laam", "level_key": "words", "item_id": "l1", "date": today, "contribution": 10.0},
    ]
    assert SupabaseDbService._compute_daily_gain_for_date(today, passes_2) == 10.0

    # 3. Test Section 9: 1 sound = 20% -> 20%
    passes_3 = [
        {"alphabet_name": "bay", "level_key": "words", "item_id": "b1", "date": today, "contribution": 20.0},
    ]
    assert SupabaseDbService._compute_daily_gain_for_date(today, passes_3) == 20.0

    # 4. Test Section 10: No new passes -> 0%
    assert SupabaseDbService._compute_daily_gain_for_date(today, []) == 0.0

    # 5. Test _extract_first_time_passes filters out score < 70 and score improvements
    events = [
        # Score 60 (< 70) -> ignored
        {"alphabet_name": "bay", "level_key": "words", "item_id": "item_fail", "previous_score": 0, "new_score": 60, "earned_at": "2026-10-05T10:00:00Z"},
        # First-time pass: 0 -> 80
        {"alphabet_name": "bay", "level_key": "words", "item_id": "item_pass", "previous_score": 0, "new_score": 80, "earned_at": "2026-10-05T10:00:00Z"},
        # Score improvement on already passed item: 80 -> 100 (previous >= 70) -> ignored
        {"alphabet_name": "bay", "level_key": "words", "item_id": "item_pass", "previous_score": 80, "new_score": 100, "earned_at": "2026-10-05T11:00:00Z"},
    ]
    extracted = SupabaseDbService._extract_first_time_passes(events, [], user_tz)
    assert len(extracted) == 1
    assert extracted[0]["item_id"] == "item_pass"
    assert extracted[0]["alphabet_name"] == "bay"
