#!/usr/bin/env bash
set -euo pipefail

# Update ETST Discord bot systemd service.
#
# What it does:
# - Installs/updates Python deps in the local venv (.venv)
# - Reloads systemd units
# - Restarts the service
# - Shows status
# - Shows logs (last lines by default; follow with --follow)
#
# Usage examples:
#   ./scripts/update_systemd.sh
#   ./scripts/update_systemd.sh --follow
#   ./scripts/update_systemd.sh --service etstBotDiscord --dir /home/jeux/BotDiscord/BotETST

SERVICE_NAME="etstBotDiscord"
APP_DIR="/home/jeux/BotDiscord/BotETST"
FOLLOW_LOGS=0

while [[ $# -gt 0 ]]; do
	case "$1" in
		--service)
			SERVICE_NAME="${2:-}"
			shift 2
			;;
		--dir)
			APP_DIR="${2:-}"
			shift 2
			;;
		--follow)
			FOLLOW_LOGS=1
			shift
			;;
		-h|--help)
			echo "Usage: $0 [--service NAME] [--dir PATH] [--follow]"
			exit 0
			;;
		*)
			echo "Unknown argument: $1" >&2
			exit 2
			;;
	esac
done

if [[ -z "$SERVICE_NAME" ]]; then
	echo "--service requires a non-empty value" >&2
	exit 2
fi

if [[ ! -d "$APP_DIR" ]]; then
	echo "App directory not found: $APP_DIR" >&2
	exit 2
fi

cd "$APP_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
	echo "Missing venv at $APP_DIR/.venv" >&2
	echo "Create it first: python3 -m venv .venv" >&2
	exit 2
fi

echo "[1/5] Installing dependencies..."
.venv/bin/python -m pip install -r requirements.txt

echo "[2/5] Reloading systemd units..."
sudo systemctl daemon-reload

echo "[3/5] Restarting service: $SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "[4/5] Service status: $SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager

echo "[5/5] Logs: $SERVICE_NAME"
if [[ "$FOLLOW_LOGS" -eq 1 ]]; then
	sudo journalctl -u "$SERVICE_NAME" -f
else
	sudo journalctl -u "$SERVICE_NAME" -n 80 --no-pager
	echo "Tip: add --follow to tail logs (journalctl -f)."
fi
