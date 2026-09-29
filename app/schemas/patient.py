import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, EmailStr, field_validator
from app.schemas.therapist import TherapistResponse


class PatientCreate(BaseModel):
    doctor_id: str = Field(..., min_length=1, description="Registered speech therapist ID")
    name: str = Field(..., min_length=2, max_length=100, description="Child's full name")
    age: int = Field(..., ge=1, le=100, description="Child's age in years")
    phone: str = Field(..., min_length=7, max_length=20, description="Parent's contact phone number")
    parent_email: EmailStr = Field(..., description="Parent's email address")
    accuracy: Optional[float] = Field(default=0.0, ge=0.0, le=100.0, description="Speech practice accuracy percentage (optional)")

    @field_validator("doctor_id", "name", "phone")
    @classmethod
    def sanitize_strings(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace only")
        return cleaned

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"\s+", " ", v.strip())
        if not re.match(r"^\+?[0-9\s\-]{7,20}$", cleaned):
            raise ValueError("Invalid phone number format")
        return cleaned


class PatientUpdate(BaseModel):
    doctor_id: str = Field(..., min_length=1, description="Registered speech therapist ID")
    name: str = Field(..., min_length=2, max_length=100, description="Child's full name")
    age: int = Field(..., ge=1, le=100, description="Child's age in years")
    phone: str = Field(..., min_length=7, max_length=20, description="Parent's contact phone number")
    parent_email: EmailStr = Field(..., description="Parent's email address")
    accuracy: Optional[float] = Field(default=0.0, ge=0.0, le=100.0, description="Current speech accuracy percentage (optional)")

    @field_validator("doctor_id", "name", "phone")
    @classmethod
    def sanitize_strings(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace only")
        return cleaned

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"\s+", " ", v.strip())
        if not re.match(r"^\+?[0-9\s\-]{7,20}$", cleaned):
            raise ValueError("Invalid phone number format")
        return cleaned


class PatientResponse(BaseModel):
    id: str
    doctor_id: str
    patient_uid: str
    name: str
    age: int
    phone: str
    parent_email: str
    accuracy: float = 0.0
    practice_code: Optional[str] = None
    doctor: Optional[TherapistResponse] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v):
        return str(v)

    model_config = {"from_attributes": True}
