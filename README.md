# Jarvis Bot 🤖

Ton assistant Hermes dans Telegram, comme une app : **DM permanent, conversation libre, Mini App HUD, vocaux** — mais légitime, local-first, sans abonnement. Le bot est une fenêtre vers **le cerveau Hermes de ta machine** (mêmes outils, même mémoire).

Fonctionne sur **n'importe quelle instance Hermes** (VPS, machine locale, serveur domestique).

## Installation en 3 minutes

```bash
git clone git@github.com:zobylamouche/hermes-jarvis-app.git
cd hermes-jarvis-app
sudo ./install.sh            # installe dans /opt/jarvis + service systemd
```

Puis :
1. Crée ton bot : Telegram → **@BotFather** → `/newbot` (nom libre, username doit finir par `bot`)
2. Copie le token dans `/opt/jarvis/.env` → `TELEGRAM_BOT_TOKEN=123456:ABC…` (chmod 600 déjà appliqué)
3. Dans `.env`, mets ton chat id dans `ALLOWED_CHAT_IDS` (par défaut : celui du canal Home d'un Hermes existant ; pour un nouveau compte, écris d'abord un message à ton bot puis récupère l'id via l'update API)
4. `systemctl enable --now jarvis-bot jarvis-app`
5. **Mini App** : sous-domaine → `A jarvis.votredomaine.tld VOTRE_IP` + site nginx (proxy → 127.0.0.1:8010) + `certbot --nginx` ; mets `JARVIS_APP_URL=https://jarvis.votredomaine.tld` dans `.env`
6. Envoie `/start` à ton bot → conversation libre + bouton permanent **🤖 OUVRIR JARVIS**

## Déployer sur une autre instance Hermes — sans prise de tête

```bash
git clone git@github.com:zobylamouche/hermes-jarvis-app.git
cd hermes-jarvis-app && sudo ./install.sh
```

C'est tout. `install.sh` apporte **tout le nécessaire** : code + Mini App, cerveau (`jarvis_brain.py`),
les 2 voix Piper (`models/piper/`, incluses au repo), la **mémoire de Jarvis**
(`data/jarvis_memoire.md`), le venv avec `requirements.txt` et les 2 services systemd
(chemin hermes auto-détecté). Idempotent : réinstaller n'écrase jamais `.env`, la mémoire
existante, ni les données.

Reste 3 choses, forcément locales à la machine cible :
1. le **token du bot** (par @BotFather, ou réutilise le même bot — le token s'envoie par EMAIL, pas en chat)
2. ton **chat id** dans `ALLOWED_CHAT_IDS`
3. le **sous-domaine Mini App** (DNS + nginx + certbot) si tu veux le HUD vocal

## La Mini App (HUD façon Iron Man)

Le bouton **🤖 OUVRIR JARVIS** lance la Mini App Telegram en plein écran :

- Interface HUD : arc réacteur animé, style Stark Industries, en français
- **Micro (maintenir pour parler)** → Whisper local *tiny* (français) → cerveau → réponse parlée (Piper, voix réglable 🎚)
- Texte libre aussi
- Auth Telegram native : la signature `initData` (HMAC) est vérifiée à chaque appel — personne d'autre ne peut utiliser l'API
- 100 % local : STT Whisper sur ta machine, pas de service cloud tiers

## Ce que le bot fait

- 💬 **Conversation libre** — traité par le cerveau complet (`hermes -z`) : tout ce que ton Hermes sait faire
- 🤖 **Mini App HUD** — s'ouvre en plein écran via le bouton permanent (voix incluse)
- Pas de menus, pas de boutons à décision prédéfinie : Jarvis, c'est Jarvis

### À venir
- Streaming STT partiel + réponse LLM en stream si la latence vocale redevient gênante

## Architecture

```
Telegram (ton bot) ← long polling ← bot.py (systemd jarvis-bot)
                                  ├─ texte libre → hermes -z (cerveau complet)
                                  └─ /start → clavier permanent "OUVRIR JARVIS" → Mini App HUD
```

- **Long polling** : pas de webhook, pas de TLS à gérer, pas de port à ouvrir
- **Queue sérialisée** : un appel cerveau à la fois (les appels `hermes -z` coûtent des tokens)
- **Whitelist** : seuls les chat ids listés dans `.env` sont servis

## Sécurité — règles non négociables

- Le token ne vit **QUE** dans `/opt/jarvis/.env` (chmod 600). Jamais dans un chat, jamais dans un repo (`.env` est git-ignoré).
- Envoi du token **par email**, pas en clair dans Telegram.
- Tout autre chat qui écrit au bot est refusé et loggé.

## Structure

```
bot.py          le bot (polling, cerveau)
jarvis_brain.py cerveau partagé (conversation LLM direct / action hermes, mémoire persistante)
app/            la Mini App (FastAPI + HUD, Piper TTS, Whisper STT)
models/piper/   les 2 voix fr (incluses au repo)
data/jarvis_memoire.md   la mémoire de Jarvis (commitée — édite-la pour lui apprendre)
requirements.txt         dépendances python
install.sh      installation + unités systemd (auto-détecte le chemin hermes)
uninstall.sh    désinstallation (garde token/logs ; --purge pour tout effacer)
.env            configuration (JAMAIS commité)
data/           logs et historiques (jamais commités, sauf la mémoire)
```

## Dépannage

```bash
systemctl status jarvis-bot                     # état
tail -f /opt/jarvis/data/jarvis_bot.log         # logs live
```

| Symptôme | Cause probable |
|---|---|
| Arrêt immédiat, log « TELEGRAM_BOT_TOKEN manquant » | Token pas rempli dans `.env` |
| HTTP 401 dans les logs | Token invalide — refaire /newbot ou vérifier la copie |
| Réponse vide | Voir les logs : souvent timeout cerveau ou provider down |
| Le bot ne répond pas après un restart | Normal 1 s : polling offset récupéré au prochain cycle |

## Licence

MIT — utilise-le, adapte-le. Les prompts des boutons parlent de domotique/trading : personnalise-les pour ta maison.