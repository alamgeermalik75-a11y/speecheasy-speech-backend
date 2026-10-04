from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy import select, and_, desc, asc, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.attempt import Attempt, ProgressEvent
from app.models.profile import FocusSound
from app.models.notification import Notification
from app.schemas.attempt import (
    CreateAttemptRequest,
    AttemptResultResponse,
    AttemptResponse,
    ProgressOverviewResponse,
    CategoryProgressDetail
)
from app.core.exceptions import BadRequestException
from app.curriculum.curriculum_manager import curriculum_manager, CATEGORY_ORDER, URDU_ALPHABET_SEQUENCE

def get_next_alphabet(current_name: str) -> Optional[Dict[str, str]]:
    return curriculum_manager.get_next_alphabet(current_name)

class ProgressService:
    PASSING_SCORE_THRESHOLD = 70

    @staticmethod
    async def record_attempt(
        session: AsyncSession,
        patient_uid: str,
        data: CreateAttemptRequest
    ) -> AttemptResultResponse:
        alpha_name = data.alphabet_name.strip()
        lvl_key = data.level_key.strip()
        item_id = data.item_id.strip()
        new_score = data.score
        attempt_time = data.client_timestamp or datetime.now(timezone.utc)

        # 1. Validate curriculum item
        if not curriculum_manager.is_valid_item(item_id, alpha_name, lvl_key):
            # Log warning or reject invalid item
            pass

        # 2. Check existing unique item record
        stmt = select(Attempt).where(
            and_(
                Attempt.patient_uid == patient_uid,
                Attempt.item_id == item_id,
                Attempt.alphabet_name == alpha_name,
                Attempt.level_key == lvl_key
            )
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        improved = False
        progress_earned = 0
        target_attempt = None

        if existing is None:
            # CASE A: UNIQUE ITEM -> INSERT
            target_attempt = Attempt(
                patient_uid=patient_uid,
                item_id=item_id,
                alphabet_name=alpha_name,
                level_key=lvl_key,
                score=new_score,
                attempted_at=attempt_time
            )
            session.add(target_attempt)
            improved = True
            progress_earned = new_score
            # Log progress event
            event = ProgressEvent(
                patient_uid=patient_uid,
                item_id=item_id,
                alphabet_name=alpha_name,
                level_key=lvl_key,
                previous_score=0,
                new_score=new_score,
                progress_earned=new_score,
                earned_at=attempt_time
            )
            session.add(event)
        elif new_score > existing.score:
            # CASE B: SAME ITEM + HIGHER SCORE -> UPDATE
            progress_earned = new_score - existing.score
            existing.score = new_score
            existing.attempted_at = attempt_time
            target_attempt = existing
            improved = True
            # Log progress event
            event = ProgressEvent(
                patient_uid=patient_uid,
                item_id=item_id,
                alphabet_name=alpha_name,
                level_key=lvl_key,
                previous_score=existing.score,
                new_score=new_score,
                progress_earned=progress_earned,
                earned_at=attempt_time
            )
            session.add(event)
        else:
            # CASE C & D: SAME ITEM + EQUAL OR LOWER SCORE -> NO UPDATE
            target_attempt = existing
            improved = False
            progress_earned = 0

        await session.flush()

        milestone_msg: Optional[str] = None
        # Achievement Notification ONLY when achieving or improving to high score >= 70
        if improved and new_score >= ProgressService.PASSING_SCORE_THRESHOLD:
            milestone_msg = f"Nice work! Score: {new_score}%"
            notif = Notification(
                patient_uid=patient_uid,
                icon="🏆",
                message=milestone_msg,
                is_read=False
            )
            session.add(notif)

        # 3. Calculate category and alphabet progress
        cat_overview = await ProgressService.get_alphabet_progress_internal(session, patient_uid, alpha_name)
        cat_detail = cat_overview["categories"].get(lvl_key, {})
        category_progress = cat_detail.get("score_percentage", 0.0)
        is_cat_complete = cat_detail.get("is_completed", False)
        alphabet_progress = cat_overview["alphabet_progress"]
        overall_progress = await ProgressService.get_overall_progress_internal(session, patient_uid)

        # 4. Check alphabet completion & Focus Sound progression
        focus_stmt = select(FocusSound).where(FocusSound.patient_uid == patient_uid)
        focus = (await session.execute(focus_stmt)).scalar_one_or_none()

        sound_mastered = False
        next_sound_name: Optional[str] = None
        focus_progress = alphabet_progress / 100.0

        is_alphabet_fully_mastered = cat_overview["is_alphabet_completed"]

        if focus and (focus.alphabet_name or "").lower() == alpha_name.lower():
            if is_alphabet_fully_mastered:
                sound_mastered = True
                next_item = curriculum_manager.get_next_alphabet(alpha_name)
                if next_item:
                    next_sound_name = next_item["name"]
                    focus.sound = next_item["letter"]
                    focus.alphabet_name = next_item["name"]
                    focus.progress = 0.0
                    focus_progress = 0.0

                    session.add(Notification(
                        patient_uid=patient_uid,
                        icon="🎉",
                        message=f"Sound '{alpha_name}' fully mastered! Moving on to '{next_item['name']}'.",
                        is_read=False
                    ))
                else:
                    focus.progress = 1.0
                    focus_progress = 1.0
                    session.add(Notification(
                        patient_uid=patient_uid,
                        icon="🎉",
                        message="Congratulations! All Urdu speech sounds fully mastered!",
                        is_read=False
                    ))
            else:
                focus.progress = min(1.0, round(focus_progress, 2))

        await session.commit()
        await session.refresh(target_attempt)

        # Determine if next category is unlocked
        lvl_idx = CATEGORY_ORDER.index(lvl_key) if lvl_key in CATEGORY_ORDER else -1
        next_cat_unlocked = False
        if lvl_idx >= 0 and lvl_idx + 1 < len(CATEGORY_ORDER):
            next_cat = CATEGORY_ORDER[lvl_idx + 1]
            next_cat_unlocked = cat_overview["categories"].get(next_cat, {}).get("is_unlocked", False)

        return AttemptResultResponse(
            attempt=AttemptResponse.model_validate(target_attempt),
            milestone_notification=milestone_msg,
            sound_mastered=sound_mastered,
            next_sound=next_sound_name,
            focus_progress=focus_progress,
            category_progress=category_progress,
            alphabet_progress=alphabet_progress,
            overall_progress=overall_progress,
            improved=improved,
            progress_earned=progress_earned,
            is_category_completed=is_cat_complete,
            next_category_unlocked=next_cat_unlocked,
        )

    @staticmethod
    async def get_alphabet_progress_internal(
        session: AsyncSession,
        patient_uid: str,
        alphabet_name: str
    ) -> Dict[str, Any]:
        alpha = alphabet_name.lower().strip()
        # Query all unique attempts for this user on this alphabet
        stmt = select(Attempt).where(
            and_(
                Attempt.patient_uid == patient_uid,
                Attempt.alphabet_name == alpha
            )
        )
        attempts = list((await session.execute(stmt)).scalars().all())

        best_by_level: Dict[str, Dict[str, int]] = {lvl: {} for lvl in CATEGORY_ORDER}
        for a in attempts:
            if a.level_key in best_by_level:
                best_by_level[a.level_key][a.item_id] = max(
                    best_by_level[a.level_key].get(a.item_id, 0),
                    a.score
                )

        categories_res: Dict[str, Dict[str, Any]] = {}
        alphabet_total_percentage = 0.0
        all_categories_complete = True
        previous_complete = True

        for lvl in CATEGORY_ORDER:
            item_scores = best_by_level[lvl]
            item_count = curriculum_manager.get_category_item_count(alpha, lvl)
            passed_count = sum(1 for s in item_scores.values() if s >= ProgressService.PASSING_SCORE_THRESHOLD)

            if item_count > 0:
                score_sum = sum(item_scores.values())
                score_pct = round((score_sum / (item_count * 100)) * 100, 2)
                is_comp = (passed_count >= item_count)
            else:
                score_pct = 100.0
                is_comp = True

            is_unlocked = previous_complete
            previous_complete = is_comp
            if not is_comp:
                all_categories_complete = False

            # Each category contributes exactly 20%
            alphabet_total_percentage += score_pct * 0.20

            categories_res[lvl] = {
                "score_percentage": score_pct,
                "is_completed": is_comp,
                "is_unlocked": is_unlocked,
                "total_items": item_count,
                "passed_items": passed_count,
            }

        return {
            "alphabet_name": alpha,
            "alphabet_progress": min(100.0, round(alphabet_total_percentage, 2)),
            "is_alphabet_completed": all_categories_complete,
            "categories": categories_res,
        }

    @staticmethod
    async def get_overall_progress_internal(
        session: AsyncSession,
        patient_uid: str
    ) -> float:
        # Sum of all stored best scores across all curriculum items
        stmt = select(func.sum(Attempt.score)).where(Attempt.patient_uid == patient_uid)
        total_score = (await session.execute(stmt)).scalar() or 0
        total_curriculum_items = curriculum_manager.get_total_curriculum_items()
        max_possible_score = total_curriculum_items * 100
        if max_possible_score <= 0:
            return 0.0
        return round((total_score / max_possible_score) * 100, 2)

    @staticmethod
    async def get_progress_overview(
        session: AsyncSession,
        patient_uid: str,
        alphabet_name: Optional[str] = None,
        tz_offset_minutes: int = 0
    ) -> ProgressOverviewResponse:
        alpha = alphabet_name.strip() if alphabet_name else "bay"
        alpha_progress_data = await ProgressService.get_alphabet_progress_internal(session, patient_uid, alpha)
        overall_progress = await ProgressService.get_overall_progress_internal(session, patient_uid)

        # Calculate daily, weekly, monthly new progress earned as overall percentage increases
        user_tz = timezone(timedelta(minutes=tz_offset_minutes))
        now = datetime.now(user_tz)
        today_date = now.date()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        month_start = now - timedelta(days=30)
        total_curriculum_items = curriculum_manager.get_total_curriculum_items()
        max_possible_points = (total_curriculum_items * 100) if total_curriculum_items > 0 else 1.0

        # From ProgressEvent table
        daily_stmt = select(func.sum(ProgressEvent.progress_earned)).where(
            and_(ProgressEvent.patient_uid == patient_uid, ProgressEvent.earned_at >= today_start)
        )
        daily_val = (await session.execute(daily_stmt)).scalar() or 0

        weekly_stmt = select(func.sum(ProgressEvent.progress_earned)).where(
            and_(ProgressEvent.patient_uid == patient_uid, ProgressEvent.earned_at >= week_start)
        )
        weekly_val = (await session.execute(weekly_stmt)).scalar() or 0

        monthly_stmt = select(func.sum(ProgressEvent.progress_earned)).where(
            and_(ProgressEvent.patient_uid == patient_uid, ProgressEvent.earned_at >= month_start)
        )
        monthly_val = (await session.execute(monthly_stmt)).scalar() or 0

        # Daily history for last 7 days
        events_stmt = select(ProgressEvent).where(
            and_(ProgressEvent.patient_uid == patient_uid, ProgressEvent.earned_at >= (now - timedelta(days=7)))
        )
        recent_events = list((await session.execute(events_stmt)).scalars().all())

        daily_history: List[Dict[str, Any]] = []
        for i in range(6, -1, -1):
            day_dt = today_date - timedelta(days=i)
            day_pts = sum(ev.progress_earned for ev in recent_events if ev.earned_at and ev.earned_at.date() == day_dt)
            day_pct = round((day_pts / max_possible_points) * 100, 2) if total_curriculum_items > 0 else 0.0
            daily_history.append({
                "date": day_dt.isoformat(),
                "label": f"{day_dt.day}/{day_dt.month}",
                "progress": day_pct,
            })

        # Build CategoryProgressDetail map
        cats: Dict[str, CategoryProgressDetail] = {}
        for k, v in alpha_progress_data["categories"].items():
            cats[k] = CategoryProgressDetail(
                score_percentage=v["score_percentage"],
                is_completed=v["is_completed"],
                is_unlocked=v["is_unlocked"],
                total_items=v["total_items"],
                passed_items=v["passed_items"]
            )

        daily_progress_pct = round((daily_val / max_possible_points) * 100, 2) if total_curriculum_items > 0 else 0.0
        weekly_progress_pct = round((weekly_val / max_possible_points) * 100, 2) if total_curriculum_items > 0 else 0.0
        monthly_progress_pct = round((monthly_val / max_possible_points) * 100, 2) if total_curriculum_items > 0 else 0.0

        return ProgressOverviewResponse(
            overall_progress=overall_progress,
            alphabet_name=alpha,
            alphabet_progress=alpha_progress_data["alphabet_progress"],
            categories=cats,
            daily_progress=daily_progress_pct,
            weekly_progress=weekly_progress_pct,
            monthly_progress=monthly_progress_pct,
            daily_history=daily_history,
            weekly_history=[]
        )

    @staticmethod
    async def get_history(
        session: AsyncSession,
        patient_uid: str,
        alphabet_name: Optional[str] = None,
        level_key: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Attempt]:
        conditions = [Attempt.patient_uid == patient_uid]
        if alphabet_name:
            conditions.append(Attempt.alphabet_name == alphabet_name.strip())
        if level_key:
            conditions.append(Attempt.level_key == level_key.strip())

        limit = min(max(1, limit), 100)
        stmt = (
            select(Attempt)
            .where(and_(*conditions))
            .order_by(desc(Attempt.attempted_at))
            .limit(limit)
            .offset(offset)
        )
        return list((await session.execute(stmt)).scalars().all())
