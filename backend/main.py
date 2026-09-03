from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

import crud
import schemas
from config import CITY_COORDINATES
from db import engine, get_db
from models import Base

CITIES = list(CITY_COORDINATES)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def validate_city(city: str) -> str:
    if city not in CITY_COORDINATES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown city '{city}'. Valid cities: {CITIES}",
        )
    return city


@app.get("/cities", response_model=schemas.CitiesResponse)
def list_cities():
    return {"cities": CITIES}


@app.get("/forecasts/{city}/latest", response_model=list[schemas.ForecastEntry])
def latest_forecast(
    city: str = Depends(validate_city),
    db: Session = Depends(get_db),
):
    return crud.get_latest_forecast(db, city)


@app.get("/forecasts/{city}/history", response_model=list[schemas.HistoryEntry])
def forecast_history(
    target_time: datetime,
    city: str = Depends(validate_city),
    db: Session = Depends(get_db),
):
    return crud.get_forecast_history(db, city, target_time)
