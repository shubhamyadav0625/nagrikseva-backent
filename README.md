# NagrikSeva Backend — Final Fixed Version

This folder is the backend that should be deployed to the Render service.

## Files
- `main.py` — FastAPI API, authentication, pipeline, complaints
- `database.py` — PostgreSQL on Render / SQLite fallback locally
- `groq_client.py` — server-side Groq integration
- `decision_table.py` — deterministic rule engine
- `requirements.txt` — Python dependencies
- `.env.example` — required environment variables
- `render.yaml` — Render deployment configuration

## Render settings
If this repository contains these files in its root, use:

**Build command**
```text
pip install -r requirements.txt
```

**Start command**
```text
python -m uvicorn main:app --host 0.0.0.0 --port $PORT
```

**Root directory:** leave blank.

Set these Environment Variables in Render:
- `GROQ_API_KEY`
- `NAGRIKSEVA_AUTH_SECRET`
- `DATABASE_URL`
- optionally `CORS_ORIGINS` (for the prototype, `*` works)

After deployment, verify:
- `/`
- `/api/health`
- `/docs`

The health response includes `version: 1.0.0-fixed`, which makes it easy to confirm Render is actually serving this revision.

## Local run
```bash
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

When `DATABASE_URL` is not set, the backend automatically creates `nagrikseva_local.db` for local testing.
