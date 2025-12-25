# BotETST
Bot discord for the Eternal Storm discord server

## Prérequis

- Python 3.10+ (recommandé: 3.11/3.12)
- Un bot Discord créé sur https://discord.com/developers/applications
- Activer **MESSAGE CONTENT INTENT** dans le portail développeur (sinon les commandes préfixées `!` ne marcheront pas)

## Installation (dev / PC)

1. Crée un fichier `.env` à la racine (tu peux partir de `.env.example`).
2. Installe les dépendances:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\pip install -r requirements.txt
```

3. Lance le bot:

```bash
.venv\Scripts\python -m src.main
```

## Déploiement Linux avec systemd

Le template du service est dans [systemd/etstBotDiscord.service](systemd/etstBotDiscord.service).

Exemple d’installation dans `/home/jeux/BotDiscord/BotETST` (adapte les chemins/utilisateur si besoin):

```bash
sudo mkdir -p /home/jeux/BotDiscord/BotETST
sudo rsync -a --delete ./ /home/jeux/BotDiscord/BotETST/
cd /home/jeux/BotDiscord/BotETST

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Crée /home/jeux/BotDiscord/BotETST/.env (copie depuis .env.example puis mets DISCORD_TOKEN)
cp .env.example .env
nano .env

sudo cp systemd/etstBotDiscord.service /etc/systemd/system/etstBotDiscord.service
sudo systemctl daemon-reload
sudo systemctl enable --now etstBotDiscord

sudo systemctl status etstBotDiscord
journalctl -u etstBotDiscord -f
```

## Commandes

- `!hello`
- `!users`
- `!damn`
- `!DJ`
- `!Nicoow`, `!Lucas`, `!Grimdal`, `!Kenderium`
- `!stats minecraft` (status serveur + joueurs en ligne)
- `!stats ark` (joueurs en ligne sur le serveur ARK ETST1)
- `!stats smite2 <pseudo>` (à brancher)
- `!stats rocketleague <pseudo>` (à brancher)

## Variables d’environnement

- `DISCORD_TOKEN` (obligatoire)
- `MINECRAFT_SERVER` (ex: `play.example.com:25565`)
- `ARK_ETST1_SERVER` (port query Steam/A2S, ex: `etst.duckdns.org:27015`)

### Tracker Network (TRN) — stats profils

Le bot peut interroger l’API publique TRN (tracker.gg) pour récupérer des stats profils.

- `TRN_API_KEY` (obligatoire pour `!stats smite1|smite2|rocketleague`)
- `TRN_RL_PLATFORM` (optionnel, défaut: `steam`) — tu peux aussi faire `!stats rocketleague steam:MonPseudo`
- `TRN_SMITE1_PLATFORM` (optionnel, défaut: `steam`) — ex: `!stats smite1 steam:MonPseudo`
- `TRN_SMITE2_PLATFORM` (optionnel, défaut: `steam`) — ex: `!stats smite2 steam:MonPseudo`
