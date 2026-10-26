#!/usr/bin/env python3
"""Jarvis Mini App — serveur FastAPI.

Interface HUD Iron Man dans Telegram (Mini App), voix locale via Whisper.
Endpoints :
  GET  /            -> index.html (HUD)
  POST /api/chat    -> {text}          -> cerveau hermes -z
  POST /api/voice   -> multipart audio -> Whisper (fr) -> cerveau
Auth : validation Telegram initData (HMAC-SHA256, cf. docs Mini Apps).
"""
import os, hmac, hashlib, json, time, subprocess, threading, queue, tempfile
import urllib.parse
from fastapi import FastAPI, Request, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
ENV_FILE = os.environ.get("JARVIS_ENV", "/opt/jarvis/.env")
PORT = int(os.environ.get("JARVIS_APP_PORT", "8010"))
HERMES_BIN = "/usr/local/lib/hermes-agent/.hermes/bin/hermes"
TIMEOUT_BRAIN = 240

def load_env():
    env = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

ENV = load_env()
BOT_TOKEN = ENV.get("TELEGRAM_BOT_TOKEN", "")
if not BOT_TOKEN:
    raise SystemExit("TELEGRAM_BOT_TOKEN manquant — Jarvis App refuse de démarrer")

app = FastAPI(title="Jarvis Mini App", docs_url=None, redoc_url=None)

# ---------- validation Telegram initData ----------
def validate_init_data(init_data: str) -> dict:
    """Vérifie la signature HMAC du initData Telegram Mini App. Lève 401 sinon."""
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, strict_parsing=False))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            raise ValueError("hash absent")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, received_hash):
            raise ValueError("signature invalide")
        # anti-replay : initData de moins de 24 h
        auth_date = int(parsed.get("auth_date", "0"))
        if time.time() - auth_date > 86400:
            raise ValueError("initData expiré")
        user = json.loads(parsed.get("user", "{}"))
        return user
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(401, f"Auth Telegram refusée: {e}")

# ---------- cerveau (queue sérialisée) ----------
def brain(text: str) -> str:
    try:
        r = subprocess.run([HERMES_BIN, "-z", text], capture_output=True, text=True,
                           timeout=TIMEOUT_BRAIN,
                           env={**os.environ,
                                "PATH": "/usr/local/lib/hermes-agent/.hermes/bin:/usr/local/bin:/usr/bin:/bin",
                                "HOME": os.path.expanduser("~")})
        out = (r.stdout or "").strip()
        return out or "(réponse vide)"
    except subprocess.TimeoutExpired:
        return "⏱️ Trop long pour cette requête. Reformule plus court ?"
    except Exception as e:
        return f"🤖 Erreur interne: {e}"

# ---------- Whisper (chargé au premier vocal, ensuite en RAM) ----------
_whisper = None
_whisper_lock = threading.Lock()

def transcribe(audio_path: str) -> str:
    global _whisper
    with _whisper_lock:
        if _whisper is None:
            from faster_whisper import WhisperModel
            _whisper = WhisperModel("small", device="cpu", compute_type="int8")
        segments, _ = _whisper.transcribe(audio_path, language="fr", beam_size=5)
        return " ".join(s.text.strip() for s in segments).strip()

# ---------- routes ----------
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))

@app.post("/api/chat")
async def api_chat(request: Request):
    user = validate_init_data(request.headers.get("X-Init-Data", ""))
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "texte vide")
    reply = brain(f"[Mini App Jarvis, message de {user.get('first_name','Greg')}] {text}")
    return JSONResponse({"reply": reply})

@app.post("/api/voice")
async def api_voice(request: Request, file: UploadFile, note: str = Form("")):
    user = validate_init_data(request.headers.get("X-Init-Data", ""))
    suffix = os.path.splitext(file.filename or "v.webm")[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir="/tmp") as tmp:
        tmp.write(await file.read())
        audio_path = tmp.name
    try:
        text = transcribe(audio_path)
        if not text:
            raise HTTPException(400, "vocal vide ou inaudible")
        prompt = f"[Mini App Jarvis, VOCAL transcrit de {user.get('first_name','Greg')}] {text}"
        if note:
            prompt += f" — note jointe: {note}"
        reply = brain(prompt)
        return JSONResponse({"transcription": text, "reply": reply})
    finally:
        os.unlink(audio_path)

@app.get("/health")
def health():
    return {"status": "ok", "app": "jarvis-mini-app"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")