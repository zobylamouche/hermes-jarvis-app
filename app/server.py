#!/usr/bin/env python3
"""Jarvis Mini App — serveur FastAPI.

Interface HUD Iron Man dans Telegram (Mini App), voix locale via Whisper.
Endpoints :
  GET  /            -> index.html (HUD)
  POST /api/chat    -> {text}          -> cerveau hermes -z
  POST /api/voice   -> multipart audio -> Whisper (fr) -> cerveau
Auth : validation Telegram initData (HMAC-SHA256, cf. docs Mini Apps).
"""
import os, hmac, hashlib, json, time, subprocess, threading, queue, tempfile, io, re, wave
import urllib.parse
from fastapi import FastAPI, Request, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
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

# tokens additionnels : la Mini App peut aussi être ouverte depuis le bot principal
# (clavier du canal Home) — chaque ouverture est signée avec le token du bot émetteur.
EXTRA_BOT_TOKENS = [t.strip() for t in ENV.get("JARVIS_EXTRA_BOT_TOKENS", "").split(",") if t.strip()]
ALL_BOT_TOKENS = [BOT_TOKEN] + EXTRA_BOT_TOKENS

app = FastAPI(title="Jarvis Mini App", docs_url=None, redoc_url=None)

# ---------- validation Telegram initData ----------
def validate_init_data(init_data: str) -> dict:
    """Vérifie la signature HMAC du initData Telegram Mini App. Lève 401 sinon.
    Accepte la signature de tout bot autorisé (Jarvis + bots supplémentaires)."""
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, strict_parsing=False))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            raise ValueError("hash absent")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        for token in ALL_BOT_TOKENS:
            secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
            computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
            if hmac.compare_digest(computed, received_hash):
                break
        else:
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
        segments, _ = _whisper.transcribe(
            audio_path, language="fr", beam_size=1,
            vad_filter=True,                      # coupe les silences : tue l'hallucination
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,     # pas d'auto-répétition en boucle
            no_speech_threshold=0.6, log_prob_threshold=-1.0,
        )
        return " ".join(s.text.strip() for s in segments).strip()

# ---------- Piper TTS (chargé au premier vocal, ensuite en RAM) ----------
TTS_MODEL = os.environ.get("JARVIS_TTS_MODEL", "/opt/jarvis/models/piper/fr_FR-tom-medium.onnx")
TTS_MAX_CHARS = 500
_piper = None
_piper_lock = threading.Lock()

_EMOJI_RE = re.compile(r"[\U00010000-\U0010FFFF\u2600-\u27BF\uFE0F\u200D\u2190-\u21FF]")

def clean_for_tts(text: str) -> str:
    t = re.sub(r"```.*?```", " (bloc de code, je te l'envoie en texte) ", text, flags=re.S)
    t = re.sub(r"https?://\S+", " lien ", t)
    t = re.sub(r"[*_`#>|~\[\]]", " ", t)
    t = _EMOJI_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > TTS_MAX_CHARS:
        cut = t[:TTS_MAX_CHARS]
        for sep in ".!?\n":
            idx = cut.rfind(sep)
            if idx > TTS_MAX_CHARS // 2:
                cut = cut[:idx + 1]
                break
        t = cut.strip()
    return t

def synthesize(text: str) -> bytes:
    """Rend un WAV 16 bits mono, PCM, prêt à jouer dans le navigateur."""
    global _piper
    t = clean_for_tts(text)
    if not t:
        raise HTTPException(400, "rien à dire")
    with _piper_lock:
        if _piper is None:
            from piper import PiperVoice
            _piper = PiperVoice.load(TTS_MODEL)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(_piper.config.sample_rate)
            for chunk in _piper.synthesize(t):
                w.writeframes(chunk.audio_int16_bytes)
        return buf.getvalue()

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

@app.post("/api/tts")
async def api_tts(request: Request):
    """Texte -> audio WAV (voix Jarvis). Auth initData obligatoire."""
    validate_init_data(request.headers.get("X-Init-Data", ""))
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "texte vide")
    audio = synthesize(text)          # laisse remonter les HTTPException
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})

@app.get("/health")
def health():
    return {"status": "ok", "app": "jarvis-mini-app"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")