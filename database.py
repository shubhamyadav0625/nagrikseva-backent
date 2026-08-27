"""
Database layer for the NagrikSeva backend.

Stores complaints in a real PostgreSQL database (not per-browser
localStorage) so that citizens and officers see the SAME shared data,
and nothing is lost when the server restarts.

Set the DATABASE_URL environment variable (Render gives you this
automatically when you create a PostgreSQL database — see setup notes).
"""

import datetime
import os

from sqlalchemy import Column, DateTime, JSON, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Render (and some other hosts) give URLs starting with "postgres://", but
# SQLAlchemy 2.x requires "postgresql://" — normalize it here.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True) if DATABASE_URL else None
SessionLocal = (
    sessionmaker(autocommit=False, autoflush=False, bind=engine) if engine else None
)
Base = declarative_base()


class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(String, primary_key=True)  # e.g. "GRV-482910"
    description = Column(Text, nullable=False)
    location = Column(String, nullable=True)
    department = Column(String, nullable=True)
    category = Column(String, nullable=True)
    recommended_action = Column(String, nullable=True)
    portal = Column(String, nullable=True)
    statutory_days = Column(String, nullable=True)
    priority = Column(String, nullable=True)
    status = Column(String, default="Submitted")
    fields = Column(JSON, nullable=True)  # full extracted fields, as JSON
    officer_notes = Column(Text, nullable=True)
    citizen_name = Column(String, nullable=True)
    submitted_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )


def init_db():
    """Creates the complaints table if it doesn't exist yet. Safe to call
    every startup — does nothing if the table is already there."""
    if engine:
        Base.metadata.create_all(bind=engine)


def get_session():
    if not SessionLocal:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it in Render's Environment Variables."
        )
    return SessionLocal()


def serialize(row: Complaint) -> dict:
    return {
        "id": row.id,
        "description": row.description,
        "location": row.location,
        "department": row.department,
        "category": row.category,
        "recommendedAction": row.recommended_action,
        "portal": row.portal,
        "statutoryDays": row.statutory_days,
        "priority": row.priority,
        "status": row.status,
        "fields": row.fields,
        "officerNotes": row.officer_notes,
        "citizenName": row.citizen_name,
        "submittedAt": row.submitted_at.isoformat() if row.submitted_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }
