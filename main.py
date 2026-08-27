"""
NagrikSeva Enterprise — backend API.

Run locally with:
    uvicorn main:app --reload --port 8000

Endpoints:
    POST /api/pipeline          { "complaint_text": "..." }  -> full recommendation
    GET  /api/health             -> {"status": "ok"}

    POST   /api/complaints       -> create/save a complaint (shared DB, not localStorage)
    GET    /api/complaints       -> list all complaints (for officer dashboard)
    GET    /api/complaints/{id}  -> fetch one complaint (for citizen tracking)
    PATCH  /api/complaints/{id}  -> officer updates status / notes
"""

import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from decision_table import find_missing_fields, recommend_action, generate_explanation
from groq_client import extract_fields, GroqError
from database import Complaint, get_session, init_db, serialize

load_dotenv()  # reads GROQ_API_KEY (and DATABASE_URL) from .env

app = FastAPI(title="NagrikSeva Enterprise API")

# Allow the frontend (served from a different origin, e.g. file:// or
# localhost:5500 / a Vercel/Netlify URL) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your real frontend URL before going live
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    # Creates the complaints table if it doesn't exist yet. Safe no-op if
    # DATABASE_URL isn't set — /api/complaints routes will just fail with a
    # clear error instead of crashing the whole app.
    try:
        init_db()
    except Exception as e:
        print(f"[startup] Database init skipped/failed: {e}")


class ComplaintRequest(BaseModel):
    complaint_text: str


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/pipeline")
def run_pipeline(req: ComplaintRequest):
    complaint_text = req.complaint_text.strip()
    if not complaint_text:
        raise HTTPException(status_code=400, detail="complaint_text is empty.")
    if len(complaint_text) > 1200:
        raise HTTPException(status_code=400, detail="complaint_text is too long (max 1200 characters).")

    # Stage 1: extract structured fields via Groq (the ONLY API call).
    try:
        fields = extract_fields(complaint_text)
    except GroqError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse extraction result: {e}")

    # Stage 2: check completeness.
    missing = find_missing_fields(fields)
    if missing:
        return {"status": "incomplete", "fields": fields, "missing_fields": missing}

    # Stage 3: match rule.
    rec = recommend_action(fields)
    if rec["status"] == "no_rule_matched":
        return {"status": "no_rule_matched", "fields": fields, "note": rec["note"]}

    # Stage 4: explanation (local, no API call).
    explanation = generate_explanation(rec)

    return {
        "status": "recommended",
        "fields": fields,
        "recommendation": rec,
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# Complaints database — shared storage so citizens and officers see the same
# data (this replaces the old per-browser localStorage complaint history).
# ---------------------------------------------------------------------------

class ComplaintCreate(BaseModel):
    id: str
    description: str
    location: Optional[str] = None
    department: Optional[str] = None
    category: Optional[str] = None
    recommended_action: Optional[str] = None
    portal: Optional[str] = None
    statutory_days: Optional[str] = None
    priority: Optional[str] = None
    status: str = "Submitted"
    fields: Optional[dict] = None
    citizen_name: Optional[str] = None


class ComplaintUpdate(BaseModel):
    status: Optional[str] = None
    officer_notes: Optional[str] = None


@app.post("/api/complaints")
def create_complaint(c: ComplaintCreate):
    db = get_session()
    try:
        existing = db.query(Complaint).filter(Complaint.id == c.id).first()
        if existing:
            raise HTTPException(status_code=409, detail="A complaint with this ID already exists.")
        row = Complaint(**c.dict())
        db.add(row)
        db.commit()
        db.refresh(row)
        return serialize(row)
    finally:
        db.close()


@app.get("/api/complaints")
def list_complaints():
    db = get_session()
    try:
        rows = db.query(Complaint).order_by(Complaint.submitted_at.desc()).all()
        return [serialize(r) for r in rows]
    finally:
        db.close()


@app.get("/api/complaints/{complaint_id}")
def get_complaint(complaint_id: str):
    db = get_session()
    try:
        row = db.query(Complaint).filter(Complaint.id == complaint_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Complaint not found.")
        return serialize(row)
    finally:
        db.close()


@app.patch("/api/complaints/{complaint_id}")
def update_complaint(complaint_id: str, u: ComplaintUpdate):
    db = get_session()
    try:
        row = db.query(Complaint).filter(Complaint.id == complaint_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Complaint not found.")
        if u.status is not None:
            row.status = u.status
        if u.officer_notes is not None:
            row.officer_notes = u.officer_notes
        db.commit()
        db.refresh(row)
        return serialize(row)
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
