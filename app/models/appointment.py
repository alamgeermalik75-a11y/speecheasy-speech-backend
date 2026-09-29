import uuid
from sqlalchemy import Column, String, Date, Time, DateTime, ForeignKey, CheckConstraint, Index, func, text
from sqlalchemy.orm import relationship
from app.core.database import Base

class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    doctor_id = Column(String, ForeignKey("therapists.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_uid = Column(String, ForeignKey("profiles.patient_uid", ondelete="CASCADE"), nullable=False, index=True)
    patient_name = Column(String, nullable=False)
    appointment_date = Column(Date, nullable=False, index=True)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    status = Column(String, default="pending", nullable=False) # 'pending', 'confirmed', 'booked', 'cancelled', 'completed'
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("start_time < end_time", name="check_appointment_time_valid"),
        CheckConstraint("status IN ('pending', 'confirmed', 'booked', 'cancelled', 'completed')", name="check_appointment_status_valid"),
        Index(
            "uq_active_therapist_booking",
            "doctor_id", "appointment_date", "start_time",
            unique=True,
            postgresql_where=text("status NOT IN ('cancelled', 'rejected', 'expired')")
        ),
        Index("idx_active_doctor_appointments", "doctor_id", "appointment_date", "start_time"),
    )

    profile = relationship("Profile", back_populates="appointments")
    therapist = relationship("Therapist", back_populates="appointments")
