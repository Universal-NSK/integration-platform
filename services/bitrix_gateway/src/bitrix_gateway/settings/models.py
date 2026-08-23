from pydantic import BaseModel, Field


class LimitSettings(BaseModel):
    min_interval: float = Field(..., gt=0)

    class Config:
        extra = "forbid"


class GatewaySettings(BaseModel):
    limits: LimitSettings

    class Config:
        extra = "forbid"
