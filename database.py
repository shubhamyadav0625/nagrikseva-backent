"""Database layer for NagrikSeva.

Render uses PostgreSQL through DATABASE_URL. For local development, if
DATABASE_URL is not set, a small SQLite database is used automatically.
"""

import datetime
import os

from dotenv import load_dotenv
from sqlalchemy import Column, DateTime, JSON, String, Text, Integer, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Local fallback makes the backend runnable in VS Code without PostgreSQL.
# Render should always have DATABASE_URL set, so it will use PostgreSQL there.
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./nagrikseva_local.db"

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    mobile = Column(String(20), nullable=False)
    email = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(300), nullable=False)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(String, primary_key=True)
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
    submitted_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_session():
    return SessionLocal()


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
        "submittedAt": row.submitted_at.isoformat() if row.submitted_at else None,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }
