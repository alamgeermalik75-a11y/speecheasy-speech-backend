from sqlalchemy import Column, String, Integer, Numeric, DateTime, ForeignKey, CheckConstraint, func
from sqlalchemy.orm import relationship
from app.core.database import Base

class Profile(Base):
    __tablename__ = "profiles"

    patient_uid = Column(String, primary_key=True, index=True)
    parent_name = Column(String, nullable=True)
    child_name = Column(String, nullable=True)
    age = Column(Integer, nullable=True)
    phone = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Cascade relationships on delete with eager selectin loading for async
    focus_sound = relationship("FocusSound", back_populates="profile", uselist=False, lazy="selectin", cascade="all, delete-orphan")
    attempts = relationship("Attempt", back_populates="profile", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="profile", cascade="all, delete-orphan")
    ratings = relationship("Rating", back_populates="profile", cascade="all, delete-orphan")
    patient_relationships = relationship("Patient", back_populates="profile", cascade="all, delete-orphan")
    patient_requests = relationship("PatientRequest", back_populates="profile", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="profile", cascade="all, delete-orphan")

    # --- Flat conveniences for the Flutter ProfileResponse contract ---
    # The Flutter app expects sound / alphabet_name / focus progress directly
    # on the profile payload; they are derived from focus_sound (single source
    # of truth in the database, no duplicated columns).
    @property
    def sound(self):
        return self.focus_sound.sound if self.focus_sound else None

    @property
    def alphabet_name(self):
        return self.focus_sound.alphabet_name if self.focus_sound else None

    @property
    def focus_progress(self):
        return float(self.focus_sound.progress) if self.focus_sound and self.focus_sound.progress is not None else 0.0


class FocusSound(Base):
    __tablename__ = "focus_sound"

    patient_uid = Column(String, ForeignKey("profiles.patient_uid", ondelete="CASCADE"), primary_key=True)
    sound = Column(String, nullable=True)
    alphabet_name = Column(String, nullable=True)
    progress = Column(Numeric, nullable=False, default=0.0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 1", name="check_focus_progress_bounds"),
    )

    profile = relationship("Profile", back_populates="focus_sound", lazy="selectin")
