from typing import List
from sqlalchemy import select, and_, update, delete, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.notification import Notification

class NotificationService:
    @staticmethod
    async def get_notifications(
        session: AsyncSession,
        patient_uid: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Notification]:
        limit = min(max(1, limit), 100)
        stmt = (
            select(Notification)
            .where(Notification.patient_uid == patient_uid)
            .order_by(desc(Notification.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    async def get_unread_count(session: AsyncSession, patient_uid: str) -> int:
        stmt = select(func.count(Notification.id)).where(
            and_(Notification.patient_uid == patient_uid, Notification.is_read.is_(False))
        )
        count = (await session.execute(stmt)).scalar()
        return count or 0

    @staticmethod
    async def mark_all_read(session: AsyncSession, patient_uid: str) -> int:
        stmt = (
            update(Notification)
            .where(and_(Notification.patient_uid == patient_uid, Notification.is_read.is_(False)))
            .values(is_read=True)
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount

    @staticmethod
    async def delete_all(session: AsyncSession, patient_uid: str) -> int:
        stmt = delete(Notification).where(Notification.patient_uid == patient_uid)
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount
