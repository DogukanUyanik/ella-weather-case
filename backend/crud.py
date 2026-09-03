from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import Forecast


def get_latest_forecast(db: Session, city: str) -> list[Forecast]:
    latest_ingested_at = db.scalar(
        select(func.max(Forecast.ingested_at)).where(Forecast.city == city)
    )
    if latest_ingested_at is None:
        return []

    return db.scalars(
        select(Forecast)
        .where(Forecast.city == city, Forecast.ingested_at == latest_ingested_at)
        .order_by(Forecast.target_time)
    ).all()


def get_forecast_history(
    db: Session, city: str, target_time: datetime
) -> list[Forecast]:
    return db.scalars(
        select(Forecast)
        .where(Forecast.city == city, Forecast.target_time == target_time)
        .order_by(Forecast.ingested_at)
    ).all()
