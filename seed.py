import asyncio
import logging
from datetime import time
from sqlalchemy import select
from app.core.database import AsyncSessionLocal, engine, Base
from app.models.daily_tip import DailyTip
from app.models.therapist import Therapist, Availability

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed")

DEFAULT_TIPS = [
    {"tip_text": "Practice slowly and clearly — accuracy beats speed.", "sort_order": 1},
    {"tip_text": "Short daily sessions work better than long weekly ones.", "sort_order": 2},
    {"tip_text": "Celebrate small wins: every clear sound counts.", "sort_order": 3},
]

DEMO_THERAPIST = {
    "full_name": "Dr. Sarah Tariq",
    "qualification": "M.Sc. Speech-Language Pathology (SLP)",
    "years_of_experience": 6,
    "languages_spoken": "Urdu, English",
    "rating": 5.0,
    "consultation_fee": 2500.0,
    "doctor_code": "SPK-1234",
    "status": "approved",
}

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

async def seed_data():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # 1. Seed Daily Tips
        logger.info("Checking daily tips...")
        tip_count = (await session.execute(select(DailyTip))).scalars().first()
        if not tip_count:
            for item in DEFAULT_TIPS:
                tip = DailyTip(
                    tip_text=item["tip_text"],
                    sort_order=item["sort_order"],
                    is_active=True
                )
                session.add(tip)
            logger.info("Inserted 3 default daily tips.")
        else:
            logger.info("Daily tips already exist, skipping.")

        # 2. Seed Demo Therapist
        logger.info("Checking demo therapist...")
        therapist_stmt = select(Therapist).where(Therapist.doctor_code == DEMO_THERAPIST["doctor_code"])
        existing_therapist = (await session.execute(therapist_stmt)).scalar_one_or_none()

        if not existing_therapist:
            therapist = Therapist(**DEMO_THERAPIST)
            session.add(therapist)
            await session.flush()

            # Add availability Monday - Friday, 09:00 - 17:00
            for day in WEEKDAYS:
                avail = Availability(
                    doctor_id=therapist.id,
                    day=day,
                    start_time=time(9, 0),
                    end_time=time(17, 0),
                    is_active=True
                )
                session.add(avail)
            logger.info(f"Created demo therapist with code '{therapist.doctor_code}' and Mon-Fri availability.")
        else:
            logger.info(f"Demo therapist with code '{DEMO_THERAPIST['doctor_code']}' already exists.")

        await session.commit()
    logger.info("Database seeding completed successfully.")

if __name__ == "__main__":
    asyncio.run(seed_data())
