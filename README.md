# Jarvis Bot 🤖

Ton assistant Hermes dans Telegram, comme une app : **DM permanent, boutons, vocaux, notifications** — mais légitime, local-first, sans abonnement. Le bot est une fenêtre vers **le cerveau Hermes de ta machine** (mêmes outils, même mémoire).

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
4. `systemctl enable --now jarvis-bot`
5. Envoie `/start` à ton bot → le menu apparaît

## Ce que le bot fait (Phase 1)

- 🏠 **Maison** — état des capteurs (via Home Assistant du serveur)
- 📊 **Trading** — résumé des comptes FxRevolution / Alpaca paper (si présent)
- 📄 **Briefing** — le dernier rapport de cron Hermes
- 💬 **Texte libre** — traité par le cerveau complet (`hermes -z`) : tout ce que ton Hermes sait faire

### À venir
- **Phase 2 — voix** : vocaux entrants → Whisper (STT), réponses → Kokoro (TTS), 100 % local
- **Phase 3** : Mini App Telegram (dashboard PWA), mémoire Obsidian, boutons riches

## Architecture

```
Telegram (ton bot) ← long polling ← bot.py (systemd jarvis-bot)
                                  ├─ boutons   → prompts bornés (économie de tokens)
                                  └─ texte libre → hermes -z (cerveau complet)
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
bot.py          le bot (polling, boutons, cerveau)
install.sh      installation + unité systemd (auto-détecte le chemin hermes)
uninstall.sh    désinstallation (garde token/logs ; --purge pour tout effacer)
.env            configuration (JAMAIS commité)
data/           logs (jamais commité)
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