import logging
from datetime import datetime, timezone

import requests
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from config import CITY_COORDINATES
from db import SessionLocal, engine
from models import Base, Forecast

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_forecast(latitude: float, longitude: float) -> dict:
    response = requests.get(
        OPEN_METEO_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m",
            "forecast_days": 7,
            "timezone": "UTC",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _parse_rows(city: str, payload: dict, run_timestamp: datetime) -> list[dict]:
    hourly = payload["hourly"]
    times = hourly["time"]
    temperatures = hourly["temperature_2m"]

    if len(times) != len(temperatures):
        raise ValueError(
            f"hourly.time and hourly.temperature_2m length mismatch: "
            f"{len(times)} vs {len(temperatures)}"
        )

    return [
        {
            "city": city,
            "target_time": datetime.fromisoformat(t).replace(tzinfo=timezone.utc),
            "ingested_at": run_timestamp,
            "temperature_c": temperature_c,
        }
        for t, temperature_c in zip(times, temperatures)
    ]


def run_ingestion(run_timestamp: datetime | None = None) -> None:
    if run_timestamp is None:
        run_timestamp = datetime.now(timezone.utc)

    Base.metadata.create_all(engine)

    for city, (latitude, longitude) in CITY_COORDINATES.items():
        try:
            payload = fetch_forecast(latitude, longitude)
            rows = _parse_rows(city, payload, run_timestamp)
        except (requests.RequestException, KeyError, ValueError) as exc:
            logger.error("%s: fetch/parse failed: %s", city, exc)
            continue

        try:
            with SessionLocal() as session:
                stmt = pg_insert(Forecast).values(rows)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["city", "target_time", "ingested_at"]
                )
                result = session.execute(stmt)
                session.commit()
                logger.info("%s: inserted %d rows", city, result.rowcount)
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error("%s: DB write failed: %s", city, exc)
            continue


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_ingestion()
