"""
Calls Groq (OpenAI-compatible chat completions API) to extract structured
fields from a citizen's free-text complaint. Groq's free tier has much more
generous per-minute limits than Gemini's, which is why we switched to it.

Same retry / exponential-backoff / backup-model logic as before — just
targeting Groq's endpoint and message format instead of Gemini's.
"""

import json
import os
import re
import time

import httpx

from decision_table import CATEGORIES

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

MODEL_NAME = "openai/gpt-oss-120b"
BACKUP_MODELS = ["openai/gpt-oss-20b", "qwen/qwen3.6-27b"]
ALL_MODELS = [MODEL_NAME] + BACKUP_MODELS
MAX_ATTEMPTS_PER_MODEL = 4

EXTRACTION_SYSTEM_PROMPT = f"""You extract structured facts from a citizen's civic complaint.
The complaint may be in English, Hindi, or Marathi (or mixed, including Hinglish
transliterated in Roman script). Understand it in its original language, but
output field VALUES in English (except free-text notes).

Return ONLY a JSON object, no preamble, no markdown fences. Use this exact schema:

{{
  "category": one of {json.dumps(CATEGORIES)} or null if unclear,
  "location": string or null,
  "duration_or_since_when": string or null,
  "prior_complaint_filed": true | false | null,
  "days_since_complaint": integer or null,
  "response_received": true | false | null,
  "response_satisfactory": true | false | null,
  "wants_information_only": true | false,
  "what_information_or_record": string or null,
  "prior_rti_filed": true | false | null,
  "days_since_rti": integer or null,
  "rti_response_received": true | false | null,
  "raw_summary": "one-sentence neutral restatement of the issue, in English"
}}

Rules:
- Use null for anything not stated or not clearly inferable. Do NOT guess.
- "wants_information_only" is true ONLY if the person is asking for records, reasons,
  or an explanation of a decision/policy -- not merely reporting a broken/unresolved service.
- Do not invent numbers. If duration is vague ("a while"), leave days_since_complaint null
  and keep the vague phrase in duration_or_since_when.

CRITICAL — detecting "prior_complaint_filed" correctly (this is the field most
often mis-read, be careful):
- Set it to true whenever the person describes having ALREADY submitted, lodged,
  registered, or reported a complaint/grievance about this specific issue before —
  in ANY phrasing or language. Past-tense verbs about filing/registering/complaining
  are the signal, e.g.: "maine ... shikayat darj ki thi", "maine complaint kiya tha",
  "maine already complain kiya", "I already filed a complaint", "I reported this
  X days ago", "maine complaint diya hua hai", "मी तक्रार केली होती" (Marathi).
- Set it to false ONLY if the person is describing the problem for the FIRST time
  and has not mentioned filing anything about it before.
- A sentence describing when/how long ago they filed (e.g. "25 din pehle ... shikayat
  darj ki thi") means prior_complaint_filed = true AND days_since_complaint = that
  number — these two fields go together; don't set one without the other when both
  are present in the text.
- "abhi tak koi jawab nahi aaya" / "no response yet" / "still no reply" means
  response_received = false, and confirms a complaint WAS already filed.

Worked example (do not include this in your output, it's just for your reference):
Input: "Maine 25 din pehle sadak ke gaddhe ki shikayat darj ki thi, abhi tak koi
jawab nahi aaya."
Correct extraction includes: category="road_pothole", prior_complaint_filed=true,
days_since_complaint=25, response_received=false, wants_information_only=false."""


class GroqError(Exception):
    pass


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```json", "", text)
    text = re.sub(r"^```", "", text)
    text = re.sub(r"```$", "", text)
    return text.strip()


def _call_groq_once(client: httpx.Client, api_key: str, model_name: str, system_instruction: str, user_text: str):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": user_text})

    body = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.2,
    }
    # Ask for strict JSON when we're doing extraction (system prompt present).
    if system_instruction:
        body["response_format"] = {"type": "json_object"}

    return client.post(GROQ_URL, headers=headers, json=body, timeout=30)


def call_groq(system_instruction: str, user_text: str) -> str:
    """
    Calls Groq with retries/backoff/backup-models. Raises GroqError with a
    clear, user-facing message on failure.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise GroqError("Server is missing GROQ_API_KEY — check the .env file.")

    last_err = None

    with httpx.Client() as client:
        for model_idx, model_name in enumerate(ALL_MODELS):
            for attempt in range(1, MAX_ATTEMPTS_PER_MODEL + 1):
                try:
                    res = _call_groq_once(client, api_key, model_name, system_instruction, user_text)
                except httpx.RequestError:
                    last_err = GroqError("Network error reaching Groq — check the server's internet connection.")
                    break

                if res.status_code == 429:
                    retry_after = res.headers.get("retry-after")
                    wait_sec = int(float(retry_after)) if retry_after else min(2 * (2 ** (attempt - 1)), 30)
                    try:
                        msg = res.json().get("error", {}).get("message", res.text[:300])
                    except Exception:
                        msg = res.text[:300]
                    time.sleep(wait_sec)
                    last_err = GroqError(f"Rate limited (HTTP 429) on {model_name}: {msg}")
                    continue

                if res.status_code in (500, 502, 503, 504):
                    wait_sec = min(2 * (2 ** (attempt - 1)), 30)
                    time.sleep(wait_sec)
                    last_err = GroqError(f"Model busy (HTTP {res.status_code}) on {model_name}")
                    continue

                if res.status_code != 200:
                    raise GroqError(f"Groq API error {res.status_code}: {res.text[:300]}")

                data = res.json()
                choices = data.get("choices", [])
                text = choices[0]["message"]["content"] if choices else ""
                if not text:
                    raise GroqError("Empty response from Groq.")
                return text

            if model_idx < len(ALL_MODELS) - 1:
                time.sleep(0.6)

    raise last_err or GroqError("All models are busy right now. Wait a minute and try again.")


def extract_fields(complaint_text: str) -> dict:
    raw = call_groq(EXTRACTION_SYSTEM_PROMPT, complaint_text)
    return json.loads(_strip_fences(raw))
