import uuid
from sqlalchemy import Column, String, Text, Boolean, Integer, DateTime, Index, func
from app.core.database import Base

class DailyTip(Base):
    __tablename__ = "daily_tips"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tip_text = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("daily_tips_active_idx", "is_active", "sort_order"),
    )
