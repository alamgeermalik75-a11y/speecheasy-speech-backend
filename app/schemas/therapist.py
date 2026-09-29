import re
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator

class TherapistResponse(BaseModel):
    id: str
    full_name: str
    name: Optional[str] = None
    qualification: Optional[str] = None
    specialty: Optional[str] = None
    years_of_experience: int = 0
    languages_spoken: Optional[str] = None
    rating: float = 5.0
    consultation_fee: float = 0.0
    doctor_code: str
    status: str = "approved"

    @model_validator(mode="after")
    def populate_aliases(self):
        if not self.name:
            self.name = self.full_name
        if not self.specialty and self.qualification:
            self.specialty = self.qualification
        return self

    model_config = {"from_attributes": True}

class DoctorCodeQuery(BaseModel):
    code: str = Field(..., min_length=4, max_length=20)

    @field_validator("code")
    @classmethod
    def clean_code(cls, v: str) -> str:
        code = v.strip().upper()
        if not re.match(r"^[A-Z0-9\-]+$", code):
            raise ValueError("Doctor code must be alphanumeric with hyphens")
        return code

class PatientRequestCreate(BaseModel):
    doctor_id: str = Field(..., min_length=1)

    @field_validator("doctor_id")
    @classmethod
    def clean_doctor_id(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("doctor_id cannot be empty")
        return cleaned

class PatientRequestResponse(BaseModel):
    id: str
    doctor_id: str
    patient_uid: str
    patient_name: str
    parent_email: Optional[str] = None
    phone: Optional[str] = None
    age: Optional[int] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}

class MyDoctorStatusResponse(BaseModel):
    status: str  # 'approved', 'pending', or 'none'
    doctor: Optional[TherapistResponse] = None
    request: Optional[PatientRequestResponse] = None
