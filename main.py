"""
NagrikSeva Enterprise — backend API.

Step 3:
- Citizen registration
- Citizen login using email + password
- Signed authentication token
- /api/me endpoint

Existing AI pipeline and complaint APIs are preserved.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from decision_table import find_missing_fields, recommend_action, generate_explanation
from groq_client import extract_fields, GroqError
from database import User, Complaint, get_session, init_db, serialize


load_dotenv()

app = FastAPI(title="NagrikSeva Enterprise API")


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# DATABASE STARTUP
# ---------------------------------------------------------------------------

@app.on_event("startup")
def on_startup():
    try:
        init_db()
    except Exception as e:
        print(f"[startup] Database init skipped/failed: {e}")


# ---------------------------------------------------------------------------
# HEALTH
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# AUTHENTICATION
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    mobile: str = Field(min_length=10, max_length=15)
    email: str = Field(min_length=5, max_length=150)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=150)
    password: str = Field(min_length=1, max_length=128)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_mobile(mobile: str) -> str:
    return re.sub(r"\s+", "", mobile.strip())


def is_valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 password hash."""
    iterations = 310_000
    salt = secrets.token_bytes(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )

    return f"pbkdf2_sha256${iterations}${salt.hex()}${password_hash.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against the stored PBKDF2 hash."""
    try:
        algorithm, iterations_text, salt_hex, hash_hex = stored_hash.split("$")

        if algorithm != "pbkdf2_sha256":
            return False

        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)

        actual_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )

        return hmac.compare_digest(actual_hash, expected_hash)

    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Signed authentication token
#
# Set NAGRIKSEVA_AUTH_SECRET in Render/local .env for a stable production
# secret. A temporary development secret is generated if it is missing.
# ---------------------------------------------------------------------------

AUTH_SECRET = os.environ.get("NAGRIKSEVA_AUTH_SECRET")

if not AUTH_SECRET:
    AUTH_SECRET = secrets.token_urlsafe(32)
    print(
        "[auth] WARNING: NAGRIKSEVA_AUTH_SECRET is not set. "
        "A temporary development secret is being used."
    )


def create_auth_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "exp": int(time.time()) + (7 * 24 * 60 * 60),
    }

    payload_bytes = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    payload_b64 = base64.urlsafe_b64encode(
        payload_bytes
    ).decode("utf-8").rstrip("=")

    signature = hmac.new(
        AUTH_SECRET.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    signature_b64 = base64.urlsafe_b64encode(
        signature
    ).decode("utf-8").rstrip("=")

    return f"{payload_b64}.{signature_b64}"


def get_current_user_id(authorization: str | None) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
        )

    token = authorization[7:].strip()

    try:
        payload_b64, signature_b64 = token.split(".", 1)

        expected_signature = hmac.new(
            AUTH_SECRET.encode("utf-8"),
            payload_b64.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        supplied_signature = base64.urlsafe_b64decode(
            signature_b64 + "=" * (-len(signature_b64) % 4)
        )

        if not hmac.compare_digest(
            expected_signature,
            supplied_signature,
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired session.",
            )

        payload = json.loads(
            base64.urlsafe_b64decode(
                payload_b64 + "=" * (-len(payload_b64) % 4)
            ).decode("utf-8")
        )

        if int(payload["exp"]) < int(time.time()):
            raise HTTPException(
                status_code=401,
                detail="Session expired. Please log in again.",
            )

        return int(payload["user_id"])

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session.",
        )


@app.post("/api/auth/register")
def register_user(req: RegisterRequest):
    name = req.name.strip()
    mobile = normalize_mobile(req.mobile)
    email = normalize_email(req.email)

    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")

    if not is_valid_email(email):
        raise HTTPException(
            status_code=400,
            detail="Please enter a valid email address.",
        )

    mobile_for_check = mobile

    if mobile_for_check.startswith("+91"):
        mobile_for_check = mobile_for_check[3:]
    elif mobile_for_check.startswith("91") and len(mobile_for_check) == 12:
        mobile_for_check = mobile_for_check[2:]

    if not re.fullmatch(r"[6-9]\d{9}", mobile_for_check):
        raise HTTPException(
            status_code=400,
            detail="Please enter a valid 10-digit mobile number.",
        )

    if req.password != req.confirm_password:
        raise HTTPException(
            status_code=400,
            detail="Password and confirm password do not match.",
        )

    db = get_session()

    try:
        existing_email = (
            db.query(User)
            .filter(User.email == email)
            .first()
        )

        if existing_email:
            raise HTTPException(
                status_code=409,
                detail="An account with this email already exists.",
            )

        user = User(
            name=name,
            mobile=mobile_for_check,
            email=email,
            password_hash=hash_password(req.password),
            city=req.city.strip() if req.city else None,
            state=req.state.strip() if req.state else None,
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        return {
            "success": True,
            "message": "Registration successful. You can now log in.",
            "user": {
                "id": user.id,
                "name": user.name,
                "mobile": user.mobile,
                "email": user.email,
                "city": user.city,
                "state": user.state,
            },
        }

    finally:
        db.close()


@app.post("/api/auth/login")
def login_user(req: LoginRequest):
    email = normalize_email(req.email)

    db = get_session()

    try:
        user = (
            db.query(User)
            .filter(User.email == email)
            .first()
        )

        # Same response for unknown email and wrong password.
        if not user or not verify_password(req.password, user.password_hash):
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password.",
            )

        token = create_auth_token(user.id)

        return {
            "success": True,
            "message": "Login successful.",
            "token": token,
            "user": {
                "id": user.id,
                "name": user.name,
                "mobile": user.mobile,
                "email": user.email,
                "city": user.city,
                "state": user.state,
            },
        }

    finally:
        db.close()


@app.get("/api/me")
def get_me(authorization: str | None = Header(default=None)):
    user_id = get_current_user_id(authorization)

    db = get_session()

    try:
        user = (
            db.query(User)
            .filter(User.id == user_id)
            .first()
        )

        if not user:
            raise HTTPException(
                status_code=401,
                detail="User account no longer exists.",
            )

        return {
            "id": user.id,
            "name": user.name,
            "mobile": user.mobile,
            "email": user.email,
            "city": user.city,
            "state": user.state,
            "createdAt": (
                user.created_at.isoformat()
                if user.created_at
                else None
            ),
        }

    finally:
        db.close()


# ---------------------------------------------------------------------------
# AI PIPELINE
# ---------------------------------------------------------------------------

class ComplaintRequest(BaseModel):
    complaint_text: str


@app.post("/api/pipeline")
def run_pipeline(req: ComplaintRequest):
    complaint_text = req.complaint_text.strip()

    if not complaint_text:
        raise HTTPException(
            status_code=400,
            detail="complaint_text is empty.",
        )

    if len(complaint_text) > 1200:
        raise HTTPException(
            status_code=400,
            detail="complaint_text is too long (max 1200 characters).",
        )

    try:
        fields = extract_fields(complaint_text)
    except GroqError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse extraction result: {e}",
        )

    missing = find_missing_fields(fields)

    if missing:
        return {
            "status": "incomplete",
            "fields": fields,
            "missing_fields": missing,
        }

    rec = recommend_action(fields)

    if rec["status"] == "no_rule_matched":
        return {
            "status": "no_rule_matched",
            "fields": fields,
            "note": rec["note"],
        }

    explanation = generate_explanation(rec)

    return {
        "status": "recommended",
        "fields": fields,
        "recommendation": rec,
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# COMPLAINTS DATABASE
# ---------------------------------------------------------------------------

class ComplaintCreate(BaseModel):
    id: str
    description: str
    location: str | None = None
    department: str | None = None
    category: str | None = None
    recommended_action: str | None = None
    portal: str | None = None
    statutory_days: str | None = None
    priority: str | None = None
    status: str = "Submitted"
    fields: dict | None = None
    citizen_name: str | None = None


class ComplaintUpdate(BaseModel):
    status: str | None = None
    officer_notes: str | None = None


@app.post("/api/complaints")
def create_complaint(c: ComplaintCreate):
    db = get_session()

    try:
        existing = (
            db.query(Complaint)
            .filter(Complaint.id == c.id)
            .first()
        )

        if existing:
            raise HTTPException(
                status_code=409,
                detail="A complaint with this ID already exists.",
            )

        row = Complaint(**c.model_dump())
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
        rows = (
            db.query(Complaint)
            .order_by(Complaint.submitted_at.desc())
            .all()
        )

        return [serialize(r) for r in rows]

    finally:
        db.close()


@app.get("/api/complaints/{complaint_id}")
def get_complaint(complaint_id: str):
    db = get_session()

    try:
        row = (
            db.query(Complaint)
            .filter(Complaint.id == complaint_id)
            .first()
        )

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Complaint not found.",
            )

        return serialize(row)

    finally:
        db.close()


@app.patch("/api/complaints/{complaint_id}")
def update_complaint(
    complaint_id: str,
    u: ComplaintUpdate,
):
    db = get_session()

    try:
        row = (
            db.query(Complaint)
            .filter(Complaint.id == complaint_id)
            .first()
        )

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Complaint not found.",
            )

        if u.status is not None:
            row.status = u.status

        if u.officer_notes is not None:
            row.officer_notes = u.officer_notes

        db.commit()
        db.refresh(row)

        return serialize(row)

    finally:
        db.close()


# ---------------------------------------------------------------------------
# LOCAL RUN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=True,
    )
