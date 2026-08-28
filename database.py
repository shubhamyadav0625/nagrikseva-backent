"""
Database layer for the NagrikSeva backend.

Stores users and complaints in PostgreSQL so that citizens and officers
share the same data.
"""

import datetime
import os

from sqlalchemy import Column, DateTime, JSON, String, Text, Integer, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Render may provide postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True) if DATABASE_URL else None

SessionLocal = (
    sessionmaker(autocommit=False, autoflush=False, bind=engine)
    if engine
    else None
)

Base = declarative_base()


# ============================================================
# USER
# ============================================================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    mobile = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ============================================================
# COMPLAINT
# ============================================================

class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(String, primary_key=True)

    # Links a complaint to the citizen who submitted it.
    # Nullable for now so existing complaints are not broken.
    user_id = Column(Integer, nullable=True, index=True)

    description = Column(Text, nullable=False)
    location = Column(String, nullable=True)
    department = Column(String, nullable=True)
    category = Column(String, nullable=True)
    recommended_action = Column(String, nullable=True)
    portal = Column(String, nullable=True)
    statutory_days = Column(String, nullable=True)
    priority = Column(String, nullable=True)
    status = Column(String, default="Submitted")
    fields = Column(JSON, nullable=True)
    officer_notes = Column(Text, nullable=True)
    citizen_name = Column(String, nullable=True)

    submitted_at = Column(
        DateTime,
        default=datetime.datetime.utcnow
    )

    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow
    )


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db():
    """Creates missing tables safely at startup."""
    if engine:
        Base.metadata.create_all(bind=engine)


# ============================================================
# DATABASE SESSION
# ============================================================

def get_session():
    if not SessionLocal:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it in Render's Environment Variables."
        )

    return SessionLocal()


# ============================================================
# COMPLAINT SERIALIZER
# ============================================================

def serialize(row: Complaint) -> dict:
    return {
        "id": row.id,
        "userId": row.user_id,
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
        "submittedAt": (
            row.submitted_at.isoformat()
            if row.submitted_at
            else None
        ),
        "updatedAt": (
            row.updated_at.isoformat()
            if row.updated_at
            else None
        ),
    }

