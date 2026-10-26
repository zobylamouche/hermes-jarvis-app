#!/usr/bin/env python3
"""Jarvis Bot — bot Telegram personnel branché sur le cerveau Hermes.

Portable : toute la config passe par .env (token, chats autorisés, chemin hermes).
Voir README.md — installation sur n'importe quelle instance Hermes via install.sh.
"""
import os, json, time, subprocess, threading, queue, sys, logging, shutil
import urllib.request, urllib.error

BASE = "https://api.telegram.org/bot{}/{}"
HERE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.environ.get("JARVIS_ENV", os.path.join(HERE, ".env"))
STATE_DIR = os.environ.get("JARVIS_STATE", os.path.join(HERE, "data"))
TIMEOUT_BRAIN = int(os.environ.get("JARVIS_TIMEOUT_BRAIN", "240"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(f"{STATE_DIR}/jarvis_bot.log"),
                              logging.StreamHandler()])
log = logging.getLogger("jarvis")

os.makedirs(STATE_DIR, exist_ok=True)

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
TOKEN = ENV.get("TELEGRAM_BOT_TOKEN", "")
if not TOKEN:
    log.error("TELEGRAM_BOT_TOKEN manquant dans %s — arrêt", ENV_FILE)
    sys.exit(1)

# whitelist : un ou plusieurs chat ids, séparés par des virgules
ALLOWED = {c.strip() for c in ENV.get("ALLOWED_CHAT_IDS", "7981177449").split(",") if c.strip()}
# binaire hermes : HERMES_BIN dans .env, sinon détection, sinon chemin d'install par défaut
HERMES_BIN = ENV.get("HERMES_BIN") or shutil.which("hermes") \
             or "/usr/local/lib/hermes-agent/.hermes/bin/hermes"
HERMES_BIN = os.path.expanduser(HERMES_BIN)
log.info("cerebra binaire: %s | chats autorisés: %s", HERMES_BIN, sorted(ALLOWED))

def tg(method, payload=None, timeout=35):
    req = urllib.request.Request(
        BASE.format(TOKEN, method),
        data=json.dumps(payload).encode() if payload else None,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def reply(chat_id, text, keyboard=None, parse="Markdown"):
    payload = {"chat_id": chat_id, "text": text[:4000]}
    if parse: payload["parse_mode"] = parse
    if keyboard: payload["reply_markup"] = {"inline_keyboard": keyboard}
    try:
        return tg("sendMessage", payload)
    except Exception as e:
        log.error("sendMessage erreur: %s", e)

# ---------- cerveau (sérialisé : un appel hermes à la fois) ----------
brain_queue = queue.Queue()

def brain_worker():
    while True:
        chat_id, text = brain_queue.get()
        try:
            log.info("cerebra <- %s", text[:120])
            r = subprocess.run([HERMES_BIN, "-z", text],
                               capture_output=True, text=True, timeout=TIMEOUT_BRAIN,
                               env={**os.environ, "PATH": "/usr/local/lib/hermes-agent/.hermes/bin:/usr/local/bin:/usr/bin:/bin",
                                    "HOME": os.path.expanduser("~")})
            out = (r.stdout or "").strip()
            if not out:
                out = "(réponse vide — regarde les logs si ça persiste)"
            reply(chat_id, out)
        except subprocess.TimeoutExpired:
            reply(chat_id, "⏱️ Trop long pour cette requête (240 s). Reformule plus court ?")
        except Exception as e:
            log.error("cerebra erreur: %s", e)
            reply(chat_id, f"🤖 Erreur interne: {e}")
        finally:
            brain_queue.task_done()

threading.Thread(target=brain_worker, daemon=True).start()

# ---------- clavier Mini App ----------
APP_URL = ENV.get("JARVIS_APP_URL", "https://jarvis.spectrodom.xyz")

def reply_kb():
    """Clavier persistant : lance la Mini App Jarvis (HUD plein écran)."""
    return {"keyboard": [[{"text": "🤖 OUVRIR JARVIS", "web_app": {"url": APP_URL}}]],
            "resize_keyboard": True, "is_persistent": True}

WELCOME = (
    "🤖 *Jarvis en ligne*\n"
    "À ton service. Écris-moi librement — je traite avec les mêmes outils "
    "que sur le chat principal.\n"
    "Ou ouvre l'app ci-dessous : HUD, voix inclus."
)

def allowed(chat_id):
    return chat_id in ALLOWED

def handle_message(m):
    chat_id = str(m["message"]["chat"]["id"])
    if not allowed(chat_id):
        log.warning("chat refusé: %s", chat_id); return
    if "text" in m["message"] and m["message"]["text"].startswith("/start"):
        payload = {"chat_id": chat_id, "text": WELCOME, "reply_markup": reply_kb()}
        tg("sendMessage", payload)
        return
    if "text" in m["message"]:
        brain_queue.put((chat_id, m["message"]["text"]))
    elif "voice" in m["message"] or "audio" in m["message"]:
        reply(chat_id, "🎙️ Vocal reçu — ouvre l'app Jarvis (bouton ci-dessous) pour parler en direct, la voix arrive ici bientôt.")
    else:
        reply(chat_id, "🤖 Je traite texte et vocaux pour l'instant.")

def handle_callback(c):
    # plus de menu boutons : on répond juste pour faire disparaître le spinner
    tg("answerCallbackQuery", {"callback_query_id": c["id"]})

def main():
    log.info("Jarvis Bot démarré (polling)")
    offset = 0
    # purge les updates en attente pour repartir propre
    u = tg("getUpdates", {"offset": -1})
    if u.get("result"): offset = u["result"][-1]["update_id"] + 1
    while True:
        try:
            u = tg("getUpdates", {"offset": offset, "timeout": 30}, timeout=40)
            for up in u.get("result", []):
                offset = up["update_id"] + 1
                if "message" in up: handle_message(up)
                elif "callback_query" in up: handle_callback(up["callback_query"])
        except urllib.error.HTTPError as e:
            log.error("HTTP %s: %s", e.code, e.read()[:200])
            time.sleep(5)
        except Exception as e:
            log.error("polling erreur: %s", e)
            time.sleep(5)

if __name__ == "__main__":
    main()