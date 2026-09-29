from datetime import date, time, datetime, timedelta
from pydantic import BaseModel, Field, field_validator, model_validator

class CreateAppointmentRequest(BaseModel):
    doctor_id: str = Field(..., min_length=1)
    appointment_date: date
    start_time: time
    end_time: time

    @field_validator("doctor_id")
    @classmethod
    def clean_doctor_id(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("doctor_id cannot be empty")
        return cleaned

    @field_validator("appointment_date")
    @classmethod
    def validate_date_not_in_past(cls, v: date) -> date:
        if v < date.today():
            raise ValueError("appointment_date cannot be in the past")
        return v

    @model_validator(mode="after")
    def validate_times_and_duration(self):
        if self.start_time >= self.end_time:
            raise ValueError("end_time must be strictly after start_time")

        # Convert to datetime for duration check
        dummy_date = date(2000, 1, 1)
        dt_start = datetime.combine(dummy_date, self.start_time)
        dt_end = datetime.combine(dummy_date, self.end_time)
        duration = dt_end - dt_start

        if duration != timedelta(minutes=30):
            raise ValueError(f"Appointment duration must be exactly 30 minutes (got {duration.total_seconds() / 60:.0f} minutes)")

        return self

class SlotInfo(BaseModel):
    time: str
    start_time: str
    end_time: str
    is_available: bool
    status: str

class AvailableSlotsResponse(BaseModel):
    date: date
    slots: list[str]
    all_slots: list[SlotInfo] = []

class AppointmentResponse(BaseModel):
    id: str
    doctor_id: str
    patient_uid: str
    patient_name: str
    appointment_date: date
    start_time: time
    end_time: time
    status: str
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v):
        return str(v)

    model_config = {"from_attributes": True}

class UpdateAppointmentStatusRequest(BaseModel):
    status: str = Field(..., description="confirmed, cancelled, completed, pending")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        s = v.strip().lower()
        if s not in {"confirmed", "cancelled", "completed", "pending"}:
            raise ValueError("status must be confirmed, cancelled, completed, or pending")
        return s
