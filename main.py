"""
NagrikSeva Enterprise — backend API.

Run locally with:
    uvicorn main:app --reload --port 8000

Endpoints:
    POST /api/pipeline   { "complaint_text": "..." }  -> full recommendation
    GET  /api/health      -> {"status": "ok"}
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from decision_table import find_missing_fields, recommend_action, generate_explanation
from groq_client import extract_fields, GroqError

load_dotenv()  # reads GROQ_API_KEY from .env

app = FastAPI(title="NagrikSeva Enterprise API")

# Allow the frontend (served from a different origin, e.g. file:// or
# localhost:5500 / a Vercel/Netlify URL) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your real frontend URL before going live
    allow_methods=["*"],
    allow_headers=["*"],
)


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
