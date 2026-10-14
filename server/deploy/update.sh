#!/usr/bin/env bash
# Deploy or update from the owner's computer. Idempotent.
#   bash server/deploy/update.sh            (reads VPS_* and PUBLIC_DOMAIN from .env)
# First run: also runs install.sh on the VPS.
set -euo pipefail
cd "$(dirname "$0")/../.."

[ -f .env ] || { echo ".env missing"; exit 1; }
set -a; . ./.env; set +a
: "${VPS_HOST:?}" "${VPS_USER:?}" "${PUBLIC_DOMAIN:?}"
KEY="${VPS_SSH_KEY/#\~/$HOME}"
SSH="ssh -i $KEY -o BatchMode=yes $VPS_USER@$VPS_HOST"
APP_DIR=/opt/projectbilal

echo "== sync code"
$SSH "mkdir -p $APP_DIR"
rsync -az --delete -e "ssh -i $KEY" \
  --exclude .env --exclude data/ --exclude .venv/ --exclude .git/ --exclude '__pycache__' \
  --exclude 'knowledge/raw/' --exclude 'knowledge/blocklist.txt' \
  ./ "$VPS_USER@$VPS_HOST:$APP_DIR/"

echo "== .env"
scp -q -i "$KEY" .env "$VPS_USER@$VPS_HOST:$APP_DIR/.env"
$SSH "chmod 600 $APP_DIR/.env"

if ! $SSH "test -f /etc/systemd/system/projectbilal.service"; then
  echo "== first install"
  $SSH "bash $APP_DIR/server/deploy/install.sh $PUBLIC_DOMAIN ${PORT:-8000}"
fi

echo "== dependencies and restart"
$SSH "cd $APP_DIR && (test -d .venv || python3 -m venv .venv) && .venv/bin/pip install -q -r server/requirements.txt \
  && chown -R projectbilal:projectbilal $APP_DIR && chown projectbilal:projectbilal $APP_DIR/.env \
  && sed -i 's#^DATA_DIR=.*#DATA_DIR=/var/lib/projectbilal#' $APP_DIR/.env \
  && systemctl restart projectbilal && sleep 2 && systemctl --no-pager status projectbilal | head -3"

echo "== health"
sleep 1
curl -fsS "https://$PUBLIC_DOMAIN/health" || { echo "health check failed; see: $SSH journalctl -u projectbilal -n 50"; exit 1; }
echo
