import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, CheckConstraint, Index, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.core.database import Base

class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_uid = Column(String, ForeignKey("profiles.patient_uid", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(String, nullable=False)
    alphabet_name = Column(String, nullable=False)
    level_key = Column(String, nullable=False)
    score = Column(Integer, nullable=False)
    attempted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="check_attempt_score_range"),
        CheckConstraint(
            "level_key IN ('words', 'sentences', 'fillBlanks', 'poems', 'story')",
            name="check_attempt_level_key"
        ),
        UniqueConstraint("patient_uid", "item_id", "alphabet_name", "level_key", name="uq_attempts_patient_item"),
        Index("idx_attempts_patient_alphabet", "patient_uid", "alphabet_name"),
        Index("idx_attempts_patient_timestamp", "patient_uid", "attempted_at"),
    )

    profile = relationship("Profile", back_populates="attempts")

    @property
    def is_passed(self) -> bool:
        return self.score >= 70


class ProgressEvent(Base):
    __tablename__ = "progress_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_uid = Column(String, ForeignKey("profiles.patient_uid", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(String, nullable=False)
    alphabet_name = Column(String, nullable=False)
    level_key = Column(String, nullable=False)
    previous_score = Column(Integer, nullable=False)
    new_score = Column(Integer, nullable=False)
    progress_earned = Column(Integer, nullable=False)
    earned_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_progress_events_patient_earned_at", "patient_uid", "earned_at"),
    )
