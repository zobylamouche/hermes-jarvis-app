# Cerveau Jarvis : routage intention.
# Conversation -> LLM direct (OpenRouter, ~2 s). Action/outils -> hermes -z (session agent).
# Fallback hermes si l'appel LLM échoue. Aucune clé n'est jamais loggée.
import os, re, json, shutil, threading, subprocess, urllib.request, urllib.error

ENV_FILE = "/opt/jarvis/.env"
HERMES_DEFAULT = "/usr/local/lib/hermes-agent/.hermes/bin/hermes"
TIMEOUT_BRAIN = int(os.environ.get("JARVIS_TIMEOUT_BRAIN", "240"))
TIMEOUT_FAST = int(os.environ.get("JARVIS_TIMEOUT_FAST", "25"))
FAST_MODEL = os.environ.get("JARVIS_FAST_MODEL", "z-ai/glm-5.3-flash")

def _load_env():
    env = {}
    try:
        for line in open(ENV_FILE):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except OSError:
        pass
    return env

_ENV = _load_env()
HERMES_BIN = _ENV.get("HERMES_BIN") or shutil.which("hermes") or HERMES_DEFAULT
_OPENROUTER_KEY_FILE = os.environ.get("JARVIS_OPENROUTER_KEY_FILE", "/opt/jarvis/.openrouter_key")

STYLE = ("Tu es Jarvis, l'assistant de Greg. Tu réponds en français, style conversationnel type ChatGPT : "
         "naturel, très concis — 2 à 4 phrases courtes, pas de titres, pas de gras, pas de listes, "
         "pas de topo ni de tableaux, sauf si Greg demande explicitement une analyse détaillée. "
         "Si Greg te demande une action concrète (lancer, exécuter, envoyer, créer...), dis simplement "
         "en une phrase que tu ne peux pas l'exécuter dans ce mode et qu'il faut reformuler dans le chat principal.")

# mots qui indiquent une action nécessitant les outils Hermes -> route hermes -z
ACTION_RE = re.compile(
    r"\b(lance[rz]?|relance[rz]?|exécute[rz]?|execute[rz]?|stoppe|arrête|arrete|éteins|eteins|allume|"
    r"envoie|redémarre|redemarre|déploie|deploie|crée|cree|supprime|modifie|place un ordre|"
    r"achète|achete|vends|vendre|clos|clôt|clot|ouvre une position|ordre|trade|position|"
    r"alarme|rappelle[- ]?moi|rappel|cron|telegram|dolibarr|fxrevolution|mt5|home assistant|"
    r"verrouille|télécharge|telecharge|transcri[pt]|one ?drive|email|mail|scan)\b", re.I)

_brain_lock = threading.Lock()   # sérialise hermes -z
_fast_lock = threading.Lock()    # OpenRouter tolère le parallélisme, lock léger pour la propreté

def _hermes(text: str) -> str:
    env = {**os.environ,
           "PATH": "/usr/local/lib/hermes-agent/.hermes/bin:/usr/local/bin:/usr/bin:/bin",
           "HOME": os.path.expanduser("~")}
    with _brain_lock:
        r = subprocess.run([HERMES_BIN, "-z", text], capture_output=True, text=True,
                           timeout=TIMEOUT_BRAIN, env=env)
    return (r.stdout or "").strip()

def _fast_llm(text: str) -> str:
    key = open(_OPENROUTER_KEY_FILE).read().strip()
    body = json.dumps({
        "model": FAST_MODEL, "max_tokens": 300,
        "messages": [{"role": "system", "content": STYLE},
                     {"role": "user", "content": text}],
    }).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with _fast_lock:
        r = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT_FAST).read())
    out = (r.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
    if not out:
        raise ValueError("réponse vide")
    return out

def answer(text: str) -> str:
    """Routage: action -> hermes -z ; conversation -> LLM direct avec fallback hermes."""
    # le routage ignore les préfixes techniques (ex: "[Mini App Jarvis, VOCAL transcrit de Greg]")
    route_text = re.sub(r"^\[[^\]]*\]\s*", "", text.strip())
    if ACTION_RE.search(route_text):
        try:
            return _hermes(text) or "(réponse vide)"
        except subprocess.TimeoutExpired:
            return "⏱️ Trop long pour cette requête. Reformule plus court ?"
        except Exception as e:
            return f"🤖 Erreur interne: {e}"
    try:
        return _fast_llm(text)
    except Exception:
        pass
    try:
        return _hermes(text) or "(réponse vide)"
    except subprocess.TimeoutExpired:
        return "⏱️ Trop long pour cette requête. Reformule plus court ?"
    except Exception as e:
        return f"🤖 Erreur interne: {e}"