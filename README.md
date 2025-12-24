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

Le template du service est dans [systemd/etst.service](systemd/etst.service).

Exemple d’installation dans `/opt/etst-bot`:

```bash
sudo mkdir -p /opt/etst-bot
sudo rsync -a --delete ./ /opt/etst-bot/
cd /opt/etst-bot

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Crée /opt/etst-bot/.env (copie depuis .env.example puis mets DISCORD_TOKEN)
sudo cp .env.example .env
sudo nano .env

sudo cp systemd/etst.service /etc/systemd/system/etst.service
sudo systemctl daemon-reload
sudo systemctl enable --now etst

sudo systemctl status etst
journalctl -u etst -f
```

## Commandes

- `!hello`
- `!users`
- `!damn`
- `!DJ`
- `!Nicoow`, `!Lucas`, `!Grimdal`, `!Kenderium`
- `!stats minecraft` (status serveur + joueurs en ligne)
- `!stats smite2 <pseudo>` (à brancher)
- `!stats rocketleague <pseudo>` (à brancher)
