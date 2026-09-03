from sqlalchemy import Column, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Forecast(Base):
    __tablename__ = "forecasts"

    id = Column(Integer, primary_key=True)
    city = Column(String, nullable=False)
    target_time = Column(DateTime(timezone=True), nullable=False)
    ingested_at = Column(DateTime(timezone=True), nullable=False)
    temperature_c = Column(Numeric, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "city", "target_time", "ingested_at",
            name="uq_forecasts_city_target_time_ingested_at",
        ),
    )
