from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

import ingest
from db import SessionLocal, engine
from models import Base, Forecast

FIXED_RUN_TIMESTAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)

STUB_PAYLOAD = {
    "hourly": {
        "time": [
            "2026-01-01T00:00",
            "2026-01-01T01:00",
            "2026-01-01T02:00",
        ],
        "temperature_2m": [1.0, 2.0, 3.0],
    }
}


def _stub_fetch_forecast(latitude: float, longitude: float) -> dict:
    return STUB_PAYLOAD


def _count_rows_for_fixed_run(session) -> int:
    return session.scalar(
        select(func.count())
        .select_from(Forecast)
        .where(Forecast.ingested_at == FIXED_RUN_TIMESTAMP)
    )


@pytest.fixture(autouse=True)
def _clean_fixed_run_rows():
    Base.metadata.create_all(engine)

    def _delete():
        with SessionLocal() as session:
            session.query(Forecast).filter(
                Forecast.ingested_at == FIXED_RUN_TIMESTAMP
            ).delete()
            session.commit()

    _delete()
    yield
    _delete()


def test_run_ingestion_is_idempotent(monkeypatch):
    monkeypatch.setattr(ingest, "fetch_forecast", _stub_fetch_forecast)

    ingest.run_ingestion(run_timestamp=FIXED_RUN_TIMESTAMP)
    with SessionLocal() as session:
        first_run_count = _count_rows_for_fixed_run(session)

    expected_rows = len(ingest.CITY_COORDINATES) * len(STUB_PAYLOAD["hourly"]["time"])
    assert first_run_count == expected_rows

    ingest.run_ingestion(run_timestamp=FIXED_RUN_TIMESTAMP)
    with SessionLocal() as session:
        second_run_count = _count_rows_for_fixed_run(session)

    assert second_run_count == first_run_count
