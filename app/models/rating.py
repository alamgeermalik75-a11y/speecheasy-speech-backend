from sqlalchemy import Column, Integer, BigInteger, String, DateTime, ForeignKey, CheckConstraint, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.core.database import Base

class Rating(Base):
    __tablename__ = "ratings"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    doctor_id = Column(String, ForeignKey("therapists.id", ondelete="CASCADE"), nullable=False)
    patient_uid = Column(String, ForeignKey("profiles.patient_uid", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="check_rating_range"),
        UniqueConstraint("doctor_id", "patient_uid", name="uq_doctor_patient_rating"),
    )

    profile = relationship("Profile", back_populates="ratings")
    therapist = relationship("Therapist", back_populates="ratings")
