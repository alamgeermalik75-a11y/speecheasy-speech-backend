import re
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator


class FocusSoundResponse(BaseModel):
    sound: Optional[str] = None
    alphabet_name: Optional[str] = None
    progress: float = Field(0.0, ge=0.0, le=1.0)
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ProfileCreateOrUpdate(BaseModel):
    parent_name: str = Field(..., min_length=2, max_length=100)
    child_name: str = Field(..., min_length=2, max_length=100)
    age: Optional[int] = Field(None, ge=1, le=100, description="Child's age in years")
    phone: str = Field(..., min_length=7, max_length=20, pattern=r"^\+?[0-9\s\-]{7,20}$", description="Parent's contact phone number")
    sound: Optional[str] = Field(None, max_length=10)
    alphabet_name: Optional[str] = Field(None, max_length=50)

    @field_validator("parent_name", "child_name")
    @classmethod
    def sanitize_names(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 2:
            raise ValueError("Name must be at least 2 non-whitespace characters")
        return cleaned

    @field_validator("age", mode="before")
    @classmethod
    def parse_age(cls, v):
        if v is None or v == "":
            return None
        try:
            val = int(v)
            return val
        except (ValueError, TypeError):
            raise ValueError("Age must be a valid integer")

    @field_validator("phone", mode="before")
    @classmethod
    def sanitize_phone(cls, v) -> str:
        if v is None:
            raise ValueError("Phone number is compulsory and cannot be empty.")
        cleaned = str(v).strip()
        if not cleaned:
            raise ValueError("Phone number is compulsory and cannot be blank.")
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not re.match(r"^\+?[0-9\s\-]{7,20}$", cleaned):
            raise ValueError("Invalid phone number format. Must contain 7 to 20 digits, optionally starting with '+'.")
        return cleaned

    @field_validator("sound", "alphabet_name")
    @classmethod
    def sanitize_sound(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip()
        return cleaned if cleaned else None

    @model_validator(mode="after")
    def validate_sound_pair(self):
        if (self.sound and not self.alphabet_name) or (self.alphabet_name and not self.sound):
            raise ValueError("Both 'sound' and 'alphabet_name' must be provided together.")
        return self


class ProfileResponse(BaseModel):
    patient_uid: str
    parent_name: Optional[str] = None
    child_name: Optional[str] = None
    age: Optional[int] = None
    phone: Optional[str] = None
    # Flat focus-sound fields expected by the Flutter app (derived from
    # focus_sound; also exposed nested under focus_sound for compatibility).
    sound: Optional[str] = None
    alphabet_name: Optional[str] = None
    focus_progress: float = 0.0
    focus_sound: Optional[FocusSoundResponse] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
