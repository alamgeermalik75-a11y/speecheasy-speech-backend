from typing import Optional
from datetime import datetime
from pydantic import BaseModel, field_validator, model_validator

class NotificationResponse(BaseModel):
    id: str
    patient_uid: str
    icon: str = "🔔"
    message: str
    title: Optional[str] = None
    body: Optional[str] = None
    read: Optional[bool] = None
    is_read: bool = False
    created_at: datetime

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v):
        return str(v)

    @model_validator(mode="after")
    def populate_compat_fields(self):
        if not self.title:
            self.title = self.message
        if not self.body:
            self.body = self.message
        if self.read is None:
            self.read = self.is_read
        return self

    model_config = {"from_attributes": True}

class UnreadCountResponse(BaseModel):
    count: int

class ActionCountResponse(BaseModel):
    success: bool = True
    count: int
