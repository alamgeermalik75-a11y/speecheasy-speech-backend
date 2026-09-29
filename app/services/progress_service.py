from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict
from sqlalchemy import select, and_, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.attempt import Attempt
from app.models.profile import FocusSound
from app.models.notification import Notification
from app.schemas.attempt import CreateAttemptRequest, AttemptResultResponse, AttemptResponse
from app.core.exceptions import BadRequestException

# --- Rule C: Isolated Urdu Alphabet Sequence ---
# Ordered curriculum sequence of Urdu sounds for speech therapy progression
URDU_ALPHABET_SEQUENCE = [
    {"name": "bay", "letter": "ب"},
    {"name": "pay", "letter": "پ"},
    {"name": "tay", "letter": "ت"},
    {"name": "ttay", "letter": "ٹ"},
    {"name": "say", "letter": "ث"},
    {"name": "jeem", "letter": "ج"},
    {"name": "chay", "letter": "چ"},
    {"name": "bari_hay", "letter": "ح"},
    {"name": "khay", "letter": "خ"},
    {"name": "daal", "letter": "د"},
    {"name": "daal_hard", "letter": "ڈ"},
    {"name": "zaal", "letter": "ذ"},
    {"name": "ray", "letter": "ر"},
    {"name": "aray", "letter": "ڑ"},
    {"name": "zay", "letter": "ز"},
    {"name": "zhe", "letter": "ژ"},
    {"name": "seen", "letter": "س"},
    {"name": "sheen", "letter": "ش"},
    {"name": "suad", "letter": "ص"},
    {"name": "zuad", "letter": "ض"},
    {"name": "toay", "letter": "ط"},
    {"name": "zoay", "letter": "ظ"},
    {"name": "ain", "letter": "ع"},
    {"name": "ghain", "letter": "غ"},
    {"name": "fay", "letter": "ف"},
    {"name": "qaaf", "letter": "ق"},
    {"name": "kaaf", "letter": "ک"},
    {"name": "gaaf", "letter": "گ"},
    {"name": "laam", "letter": "ل"},
    {"name": "meem", "letter": "م"},
    {"name": "noon", "letter": "ن"},
    {"name": "wao", "letter": "و"},
    {"name": "choti_hay", "letter": "ہ"},
    {"name": "hamza", "letter": "ء"},
    {"name": "choti_yay", "letter": "ی"},
    {"name": "bari_yay", "letter": "ے"},
]

def get_next_alphabet(current_name: str) -> Optional[Dict[str, str]]:
    current_lower = current_name.lower().strip()
    for idx, item in enumerate(URDU_ALPHABET_SEQUENCE):
        if item["name"].lower() == current_lower or item["letter"] == current_name:
            if idx + 1 < len(URDU_ALPHABET_SEQUENCE):
                return URDU_ALPHABET_SEQUENCE[idx + 1]
            return None
    return None


class ProgressService:
    PASSING_SCORE_THRESHOLD = 70
    # Expected target unique items per practice level to measure authentic mastery
    TARGET_UNIQUE_ITEMS_PER_LEVEL = 4

    @staticmethod
    async def record_attempt(
        session: AsyncSession,
        patient_uid: str,
        data: CreateAttemptRequest
    ) -> AttemptResultResponse:
        # 1. Insert Attempt
        attempt_time = data.client_timestamp or datetime.now(timezone.utc)
        attempt = Attempt(
            patient_uid=patient_uid,
            item_id=data.item_id,
            alphabet_name=data.alphabet_name,
            level_key=data.level_key,
            score=data.score,
            attempted_at=attempt_time
        )
        session.add(attempt)
        await session.flush()

        milestone_msg: Optional[str] = None
        # 2. Achievement Notification for high score
        if data.score >= ProgressService.PASSING_SCORE_THRESHOLD:
            milestone_msg = f"Nice work! Score: {data.score}%"
            notif = Notification(
                patient_uid=patient_uid,
                icon="🏆",
                message=milestone_msg,
                is_read=False
            )
            session.add(notif)

        # 3. Check and update focus sound
        focus_stmt = select(FocusSound).where(FocusSound.patient_uid == patient_uid)
        focus = (await session.execute(focus_stmt)).scalar_one_or_none()

        sound_mastered = False
        next_sound_name: Optional[str] = None
        new_progress = 0.0

        if focus and focus.alphabet_name and focus.alphabet_name.lower() == data.alphabet_name.lower():
            # Rule B: Calculate authentic mastery based on passed unique items across levels
            # Query all attempts for this user on this alphabet
            all_attempts_stmt = select(Attempt).where(
                and_(
                    Attempt.patient_uid == patient_uid,
                    Attempt.alphabet_name == data.alphabet_name
                )
            )
            attempts = (await session.execute(all_attempts_stmt)).scalars().all()

            # Find best score for each unique item_id per level
            best_by_level: Dict[str, Dict[str, int]] = {
                "words": {},
                "sentences": {},
                "fillBlanks": {},
                "poems": {},
                "story": {}
            }
            for a in attempts:
                if a.level_key in best_by_level:
                    current_best = best_by_level[a.level_key].get(a.item_id, 0)
                    if a.score > current_best:
                        best_by_level[a.level_key][a.item_id] = a.score

            # Calculate completion percentage
            level_ratios = []
            for lvl, item_scores in best_by_level.items():
                passed_count = sum(1 for s in item_scores.values() if s >= ProgressService.PASSING_SCORE_THRESHOLD)
                ratio = min(1.0, passed_count / ProgressService.TARGET_UNIQUE_ITEMS_PER_LEVEL)
                level_ratios.append(ratio)

            overall_ratio = sum(level_ratios) / len(level_ratios) if level_ratios else 0.0
            new_progress = round(overall_ratio, 2)

            if new_progress >= 1.0:
                sound_mastered = True
                next_item = get_next_alphabet(focus.alphabet_name)
                if next_item:
                    next_sound_name = next_item["name"]
                    focus.sound = next_item["letter"]
                    focus.alphabet_name = next_item["name"]
                    focus.progress = 0.0
                    new_progress = 0.0

                    # Mastery Notification
                    session.add(Notification(
                        patient_uid=patient_uid,
                        icon="🎉",
                        message=f"Sound '{data.alphabet_name}' fully mastered! Moving on to '{next_item['name']}'.",
                        is_read=False
                    ))
                else:
                    focus.progress = 1.0
                    new_progress = 1.0
                    session.add(Notification(
                        patient_uid=patient_uid,
                        icon="🎉",
                        message="Congratulations! All Urdu speech sounds fully mastered!",
                        is_read=False
                    ))
            else:
                focus.progress = new_progress

        await session.commit()
        await session.refresh(attempt)

        return AttemptResultResponse(
            attempt=AttemptResponse.model_validate(attempt),
            milestone_notification=milestone_msg,
            sound_mastered=sound_mastered,
            next_sound=next_sound_name,
            focus_progress=new_progress
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

        limit = min(max(1, limit), 100) # enforce maximum 100 items
        stmt = (
            select(Attempt)
            .where(and_(*conditions))
            .order_by(asc(Attempt.attempted_at))
            .limit(limit)
            .offset(offset)
        )
        return list((await session.execute(stmt)).scalars().all())
