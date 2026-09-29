from pydantic import BaseModel

class DailyTipResponse(BaseModel):
    id: str
    tip_text: str
    sort_order: int

    model_config = {"from_attributes": True}
