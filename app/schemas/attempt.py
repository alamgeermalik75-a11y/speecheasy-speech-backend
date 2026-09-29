from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

class CreateAttemptRequest(BaseModel):
    item_id: str = Field(..., min_length=1, max_length=100)
    alphabet_name: str = Field(..., min_length=1, max_length=100)
    level_key: str = Field(..., pattern=r"^(words|sentences|fillBlanks|poems|story)$")
    score: int = Field(..., ge=0, le=100)
    client_timestamp: Optional[datetime] = None

    @field_validator("item_id", "alphabet_name")
    @classmethod
    def sanitize_strings(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty")
        return cleaned

class AttemptResponse(BaseModel):
    id: str
    patient_uid: str
    item_id: str
    alphabet_name: str
    level_key: str
    score: int
    attempted_at: Optional[datetime] = None

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v):
        return str(v)

    model_config = {"from_attributes": True}

class AttemptResultResponse(BaseModel):
    attempt: AttemptResponse
    milestone_notification: Optional[str] = None
    sound_mastered: bool = False
    next_sound: Optional[str] = None
    focus_progress: float = 0.0
