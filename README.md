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
- `!ppc @membre` (Pierre-Papier-Ciseaux 1 manche; vous devez être dans le même vocal; le perdant est déconnecté du vocal)
- `!DJ`
- `!Nicoow`, `!Lucas`, `!Grimdal`, `!Kenderium`
- `!stats minecraft` (status serveur + joueurs en ligne)
- `!stats ark` (joueurs en ligne sur le serveur ARK ETST1)
- `!stats satisfactory` (joueurs en ligne sur un serveur Satisfactory)
- `!id` (enregistrer/afficher tes IDs Steam/Epic)
- `!stats smite1 [pseudo]` (si pseudo absent, utilise l’ID Steam enregistré via `!id`)
- `!stats smite2 [pseudo]` (si pseudo absent, utilise l’ID Steam enregistré via `!id`)
- `!stats rocketleague [pseudo]` (si pseudo absent, utilise l’ID Epic enregistré via `!id`)
- `!stats lethalcompany` (joueurs en ligne globaux via Steam)
- `!stats coc #TAG` (infos joueur Clash of Clans via API Supercell)
- `!stats cocclan #TAG` (infos clan Clash of Clans via API Supercell)
- `!stats brawl #TAG` (infos joueur Brawl Stars via API Supercell)
- `!stats cr #TAG` (infos joueur Clash Royale via API officielle / proxy RoyaleAPI)

### Notes permissions (vocal)

- Pour `!ppc`, le bot doit avoir la permission **Move Members** afin de pouvoir déconnecter le perdant du salon vocal.
- Les 2 joueurs doivent être dans **le même salon vocal**.

## Variables d’environnement

- `DISCORD_TOKEN` (obligatoire)
- `MINECRAFT_SERVER` (ex: `play.example.com:25565`)
- `ARK_ETST1_SERVER` (port query Steam/A2S, ex: `play.example.com:27015`)
- `SATISFACTORY_SERVER` (port query/A2S, ex: `play.example.com:8888`)

### Tracker Network (TRN) — stats profils

Le bot peut interroger l’API publique TRN (tracker.gg) pour récupérer des stats profils.

- `TRN_API_KEY` (optionnel) — utilisé si tu branches Smite via TRN.
- `TRN_SMITE1_PLATFORM` (optionnel, défaut: `steam`) — ex: `!stats smite1 steam:MonPseudo`
- `TRN_SMITE2_PLATFORM` (optionnel, défaut: `steam`) — ex: `!stats smite2 steam:MonPseudo`

### Rocket League (RapidAPI)

Rocket League n’est pas forcément disponible via TRN selon ton plan/titres. Le bot peut utiliser une API Rocket League via RapidAPI.

- `RAPIDAPI_KEY` (obligatoire)
- `RL_RAPIDAPI_HOST` (obligatoire) — le host RapidAPI (ex: `xxxx.p.rapidapi.com`)
- `RL_RAPIDAPI_URL_TEMPLATE` (obligatoire) — URL complète ou path (commençant par `/`).
	- Peut être une URL complète **ou** juste un path (commençant par `/`).
	- Exemples (à adapter à l’API RapidAPI que tu as choisie):
		- `/ranks/{identifier}`
	- Pour `rocket-league1`, le paramètre `{identifier}` est l’**Epic Games account id** ou le **display name**.
- `RL_PLATFORM` (optionnel) — conservé pour compatibilité de commande, mais `rocket-league1` ignore la plateforme.

### Supercell (Clash of Clans / Brawl Stars)

Les APIs officielles Supercell nécessitent:
- un token API
- et une IP **whitelistée** sur le portail développeur (sinon 401/403).

- `COC_API_TOKEN` (optionnel) — permet `!stats coc #TAG`
- `BRAWLSTARS_API_TOKEN` (optionnel) — permet `!stats brawl #TAG`

Option "backup" si ton IP change: proxies RoyaleAPI (https://docs.royaleapi.com/proxy.html)
- `COC_API_BASE_URL` (défaut: `https://api.clashofclans.com/v1`)
- `COC_PROXY_BASE_URL` (défaut: `https://cocproxy.royaleapi.dev/v1`)
- `BRAWLSTARS_API_BASE_URL` (défaut: `https://api.brawlstars.com/v1`)
- `BRAWLSTARS_PROXY_BASE_URL` (défaut: `https://bsproxy.royaleapi.dev/v1`)

### Clash Royale

- `CLASHROYALE_API_TOKEN` (optionnel) — permet `!stats cr #TAG`
- `CLASHROYALE_API_BASE_URL` (défaut: `https://api.clashroyale.com/v1`)
- `CLASHROYALE_PROXY_BASE_URL` (défaut: `https://proxy.royaleapi.dev/v1`)
