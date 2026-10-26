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
import asyncio, logging, urllib.parse
from fastapi import FastAPI, Request, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
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

# ---------- cerveau : routage intention via jarvis_brain (LLM direct ~2 s / hermes pour les actions) ----------
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # /opt/jarvis
import jarvis_brain

def brain(text: str) -> str:
    return jarvis_brain.answer(text)

# ---------- Whisper (chargé au premier vocal, ensuite en RAM) ----------
_whisper_lock = threading.Lock()
_whisper = {}   # nom -> modèle (tiny = rapide, small = qualité de repli)

def _whisper_model(name: str):
    with _whisper_lock:
        if name not in _whisper:
            from faster_whisper import WhisperModel
            _whisper[name] = WhisperModel(name, device="cpu", compute_type="int8")
        return _whisper[name]

def _run_whisper(model, audio_path: str):
    segments, _ = model.transcribe(
        audio_path, language="fr", beam_size=1,
        vad_filter=True,                      # coupe les silences : tue l'hallucination
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,     # pas d'auto-répétition en boucle
        no_speech_threshold=0.6, log_prob_threshold=-1.0,
    )
    parts, probs = [], []
    for s in segments:
        parts.append(s.text.strip())
        if s.avg_logprob is not None:
            probs.append(s.avg_logprob)
    text = " ".join(p for p in parts if p).strip()
    avg = sum(probs) / len(probs) if probs else -10.0
    return text, avg

def _to_wav(src: str) -> str:
    """Normalise n'importe quel format (webm/ogg/mp4) en wav 16k mono.
    Répare aussi les blobs MediaRecorder aux métadonnées tronquées,
    qui font planter le décodage direct (av InvalidDataError)."""
    import subprocess
    dst = src.rsplit(".", 1)[0] + ".wav"
    try:
        r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                            "-i", src, "-ar", "16000", "-ac", "1", dst],
                           capture_output=True, timeout=60)
    except Exception:
        raise RuntimeError("audio illisible")
    if r.returncode != 0 or not os.path.exists(dst):
        err = (r.stderr or b"").decode(errors="replace")[-300:]
        raise RuntimeError("ffmpeg %s: %s" % (r.returncode, err or "sans message"))
    return dst

def transcribe(audio_path: str) -> str:
    """Transcription rapide : tiny partout (CPU du VPS : small = 26 s, inutilisable).
    small ne sert qu'au cas limite où tiny renvoie du vide."""
    t0 = time.time()
    wav = audio_path
    try:
        wav = _to_wav(audio_path)
    except Exception:
        pass                                  # repli : décodage direct par faster-whisper
    try:
        text, _ = _run_whisper(_whisper_model("tiny"), wav)
        if not text:
            text, _ = _run_whisper(_whisper_model("small"), wav)
    finally:
        if wav != audio_path:
            try: os.unlink(wav)
            except OSError: pass
    logging.getLogger("jarvis").info("transcription %.1fs: %s", time.time() - t0, text[:80])
    return text

# ---------- Piper TTS (chargé au premier vocal, ensuite en RAM) ----------
VOICES_DIR = "/opt/jarvis/models/piper"
TTS_MODEL = os.environ.get("JARVIS_TTS_MODEL", os.path.join(VOICES_DIR, "fr_FR-tom-medium.onnx"))
TTS_MAX_CHARS = 500
_voices = {}          # chemin modèle -> PiperVoice chargé (RAM)
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

def available_voices() -> list:
    """Noms de voix Piper disponibles (sans extension), pour la whitelist /api/voices."""
    try:
        return sorted(os.path.splitext(f)[0] for f in os.listdir(VOICES_DIR) if f.endswith(".onnx"))
    except OSError:
        return []

def resolve_voice(name: str) -> str:
    """Nom de voix demandé par le front -> chemin .onnx validé (jamais de chemin arbitraire)."""
    if not name:
        return TTS_MODEL
    v = os.path.basename(name)                      # strip toute arborescence
    if not v.endswith(".onnx"):
        v += ".onnx"
    path = os.path.join(VOICES_DIR, v)
    if not os.path.isfile(path):
        raise HTTPException(400, f"voix inconnue: {v}")
    return path

def synthesize(text: str, model_path: str | None = None) -> bytes:
    """Rend un WAV 16 bits mono, PCM, prêt à jouer dans le navigateur."""
    t = clean_for_tts(text)
    if not t:
        raise HTTPException(400, "rien à dire")
    model_path = model_path or TTS_MODEL
    with _piper_lock:
        voice = _voices.get(model_path)
        if voice is None:
            from piper import PiperVoice
            voice = _voices[model_path] = PiperVoice.load(model_path)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(voice.config.sample_rate)
            for chunk in voice.synthesize(t):
                w.writeframes(chunk.audio_int16_bytes)
        return buf.getvalue()

# ---------- routes ----------
@app.on_event("startup")
def warmup_models():
    """Précharge Whisper et Piper en arrière-plan : le 1er vocal ne paie plus le chargement (~7 s)."""
    def _warm():
        try:
            # les 2 voix fr disponibles : le 1er changement de voix ne paie pas le chargement
            for v in set(available_voices()) or {os.path.basename(TTS_MODEL)}:
                wav = synthesize("Systèmes en ligne.", resolve_voice(v))
                with open("/opt/jarvis/models/warmup.wav", "wb") as f:
                    f.write(wav)
            transcribe("/opt/jarvis/models/warmup.wav")
        except Exception as e:
            logging.getLogger("jarvis").warning("warmup incomplet: %s", e)
    threading.Thread(target=_warm, daemon=True).start()

@app.api_route("/", methods=["GET", "HEAD"])
def index():
    return FileResponse(os.path.join(STATIC, "index.html"),
                        headers={"Cache-Control": "no-store, must-revalidate"})

@app.post("/api/chat")
async def api_chat(request: Request):
    user = validate_init_data(request.headers.get("X-Init-Data", ""))
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "texte vide")
    reply = await run_in_threadpool(brain, f"[Mini App Jarvis, message de {user.get('first_name','Greg')}] {text}")
    return JSONResponse({"reply": reply})

@app.post("/api/stt")
async def api_stt(request: Request, file: UploadFile):
    """Transcription seule (rapide) — le front affiche le texte tout de suite,
    puis envoie la transcription à /api/chat. Sépare STT et cerveau."""
    validate_init_data(request.headers.get("X-Init-Data", ""))
    suffix = os.path.splitext(file.filename or "v.webm")[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir="/tmp") as tmp:
        blob = await file.read()
        if len(blob) < 2048:
            raise HTTPException(400, "vocal trop court")
        tmp.write(blob)
        audio_path = tmp.name
    try:
        text = await run_in_threadpool(transcribe, audio_path)
    except HTTPException:
        raise
    except Exception as exc:
        try:   # capture du blob illisible pour diagnostic
            os.makedirs("/opt/jarvis/bad_audio", exist_ok=True)
            with open("/opt/jarvis/bad_audio/%d.webm" % int(time.time()), "wb") as f:
                f.write(blob)
        except OSError:
            pass
        logging.getLogger("jarvis").warning("audio illisible (%s octets): %s", len(blob), str(exc)[:200])
        raise HTTPException(400, "vocal illisible")
    finally:
        os.unlink(audio_path)
    if not text:
        raise HTTPException(400, "vocal vide ou inaudible")
    return JSONResponse({"transcription": text})

@app.post("/api/voice")
async def api_voice(request: Request, file: UploadFile, note: str = Form("")):
    user = validate_init_data(request.headers.get("X-Init-Data", ""))
    suffix = os.path.splitext(file.filename or "v.webm")[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir="/tmp") as tmp:
        blob = await file.read()
        if len(blob) < 2048:
            raise HTTPException(400, "vocal trop court")
        tmp.write(blob)
        audio_path = tmp.name
    try:
        try:
            text = await run_in_threadpool(transcribe, audio_path)  # noqa: garde /api/voice (1 appel cerveau)
        except Exception:
            logging.getLogger("jarvis").warning("audio illisible (%s octets)", len(blob))
            raise HTTPException(400, "vocal illisible")
        if not text:
            raise HTTPException(400, "vocal vide ou inaudible")
        prompt = f"[Mini App Jarvis, VOCAL transcrit de {user.get('first_name','Greg')}] {text}"
        if note:
            prompt += f" — note jointe: {note}"
        reply = await run_in_threadpool(brain, prompt)
        return JSONResponse({"transcription": text, "reply": reply})
    finally:
        os.unlink(audio_path)

@app.post("/api/tts")
async def api_tts(request: Request):
    """Texte -> audio WAV (voix Jarvis). Auth initData obligatoire. voice = nom Piper optionnel."""
    validate_init_data(request.headers.get("X-Init-Data", ""))
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "texte vide")
    audio = await run_in_threadpool(synthesize, text, resolve_voice(body.get("voice") or ""))
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})

@app.get("/api/voices")
async def api_voices(request: Request):
    """Liste des voix Piper disponibles (auth initData obligatoire)."""
    validate_init_data(request.headers.get("X-Init-Data", ""))
    return JSONResponse({"voices": available_voices()})

@app.get("/health")
def health():
    return {"status": "ok", "app": "jarvis-mini-app"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")