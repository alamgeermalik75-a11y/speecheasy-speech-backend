from typing import Optional
from pydantic import BaseModel, Field, field_validator

class SubmitRatingRequest(BaseModel):
    doctor_id: str = Field(..., min_length=1)
    rating: int = Field(..., ge=1, le=5)

    @field_validator("doctor_id")
    @classmethod
    def sanitize_doctor_id(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("doctor_id cannot be empty")
        return cleaned

class MyRatingResponse(BaseModel):
    doctor_id: str
    rating: Optional[int] = None

class RatingResponse(BaseModel):
    id: int
    doctor_id: str
    patient_uid: str
    rating: int

    model_config = {"from_attributes": True}
