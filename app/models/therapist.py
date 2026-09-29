import uuid
from sqlalchemy import Column, String, Integer, Numeric, Boolean, Time, DateTime, ForeignKey, CheckConstraint, UniqueConstraint, func
from sqlalchemy.orm import relationship
from app.core.database import Base

class Therapist(Base):
    __tablename__ = "therapists"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    full_name = Column(String, nullable=False)
    qualification = Column(String, nullable=True)
    years_of_experience = Column(Integer, default=0, nullable=False)
    languages_spoken = Column(String, nullable=True)
    rating = Column(Numeric(3, 2), default=5.0, nullable=False)
    consultation_fee = Column(Numeric(10, 2), default=0.0, nullable=False)
    doctor_code = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, default="approved", nullable=False) # 'approved', 'pending'

    __table_args__ = (
        CheckConstraint("years_of_experience >= 0", name="check_years_exp_non_negative"),
        CheckConstraint("consultation_fee >= 0", name="check_fee_non_negative"),
        CheckConstraint("rating >= 0 AND rating <= 5", name="check_therapist_rating_range"),
        CheckConstraint("status IN ('approved', 'pending')", name="check_therapist_status"),
    )

    availabilities = relationship("Availability", back_populates="therapist", cascade="all, delete-orphan")
    ratings = relationship("Rating", back_populates="therapist", cascade="all, delete-orphan")
    patient_requests = relationship("PatientRequest", back_populates="therapist", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="therapist", cascade="all, delete-orphan")
    patients = relationship("Patient", back_populates="therapist", cascade="all, delete-orphan")


class Availability(Base):
    __tablename__ = "availability"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    doctor_id = Column(String, ForeignKey("therapists.id", ondelete="CASCADE"), nullable=False, index=True)
    day = Column(String, nullable=False)            # e.g., 'Monday', 'Tuesday'
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        CheckConstraint("start_time < end_time", name="check_availability_time_valid"),
        CheckConstraint(
            "day IN ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')",
            name="check_availability_day_valid"
        ),
    )

    therapist = relationship("Therapist", back_populates="availabilities")


class Patient(Base):
    __tablename__ = "patients"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    doctor_id = Column(String, ForeignKey("therapists.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_uid = Column(String, ForeignKey("profiles.patient_uid", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    phone = Column(String, nullable=True)
    parent_email = Column(String, nullable=True)
    accuracy = Column(Numeric(5, 2), default=0.0, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("doctor_id", "patient_uid", name="uq_doctor_patient_link"),
    )

    profile = relationship("Profile", back_populates="patient_relationships")
    therapist = relationship("Therapist", back_populates="patients")


class PatientRequest(Base):
    __tablename__ = "patient_requests"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    doctor_id = Column(String, ForeignKey("therapists.id", ondelete="CASCADE"), nullable=False, index=True)
    patient_uid = Column(String, ForeignKey("profiles.patient_uid", ondelete="CASCADE"), nullable=False, index=True)
    patient_name = Column(String, nullable=False)
    parent_email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    status = Column(String, default="pending", nullable=False) # 'pending', 'accepted', 'rejected'
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'accepted', 'rejected')", name="check_patient_request_status"),
        UniqueConstraint("doctor_id", "patient_uid", "status", name="uq_doctor_patient_request_status"),
    )

    profile = relationship("Profile", back_populates="patient_requests")
    therapist = relationship("Therapist", back_populates="patient_requests")
