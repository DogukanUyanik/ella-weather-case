from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CitiesResponse(BaseModel):
    cities: list[str]


class ForecastEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_time: datetime
    temperature_c: float


class HistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ingested_at: datetime
    temperature_c: float
