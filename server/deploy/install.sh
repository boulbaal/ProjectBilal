#!/usr/bin/env bash
# First-time install on a fresh Ubuntu 22.04/24.04 VPS. Run as root ON THE VPS:
#   bash install.sh <PUBLIC_DOMAIN> <PORT>
# It installs only what is listed here. It removes nothing. It touches no other service.
set -euo pipefail

DOMAIN="${1:?usage: install.sh <public_domain> [port]}"
PORT="${2:-8000}"
APP_DIR=/opt/projectbilal
DATA_DIR=/var/lib/projectbilal
SVC_USER=projectbilal

echo "== packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip rsync ufw curl debian-keyring debian-archive-keyring apt-transport-https gnupg

if ! command -v caddy >/dev/null; then
  echo "== caddy (official repo)"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
  apt-get install -y -q caddy
fi

echo "== user and directories"
id -u $SVC_USER >/dev/null 2>&1 || useradd --system --home $DATA_DIR --shell /usr/sbin/nologin $SVC_USER
mkdir -p $APP_DIR $DATA_DIR/backup
chown -R $SVC_USER:$SVC_USER $DATA_DIR

echo "== application (expects the repository already rsynced to $APP_DIR by update.sh, or run update.sh after this)"
if [ -f $APP_DIR/server/requirements.txt ]; then
  python3 -m venv $APP_DIR/.venv
  $APP_DIR/.venv/bin/pip install -q --upgrade pip
  $APP_DIR/.venv/bin/pip install -q -r $APP_DIR/server/requirements.txt
  chown -R $SVC_USER:$SVC_USER $APP_DIR
fi

echo "== systemd unit"
sed "s#__PORT__#$PORT#g" "$APP_DIR/server/deploy/projectbilal.service" > /etc/systemd/system/projectbilal.service
systemctl daemon-reload
systemctl enable projectbilal

echo "== caddy"
if grep -q "$DOMAIN" /etc/caddy/Caddyfile 2>/dev/null; then
  echo "Caddyfile already has $DOMAIN, leaving it"
else
  if [ -s /etc/caddy/Caddyfile ] && ! grep -q "^:80" /etc/caddy/Caddyfile; then
    echo "WARNING: /etc/caddy/Caddyfile already has content for another site. Appending a block."
    cat "$APP_DIR/server/deploy/Caddyfile" | sed "s#__DOMAIN__#$DOMAIN#g; s#__PORT__#$PORT#g" >> /etc/caddy/Caddyfile
  else
    sed "s#__DOMAIN__#$DOMAIN#g; s#__PORT__#$PORT#g" "$APP_DIR/server/deploy/Caddyfile" > /etc/caddy/Caddyfile
  fi
fi
systemctl enable caddy
systemctl restart caddy

echo "== firewall (22, 80, 443 only)"
ufw allow 22/tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

echo "== daily database backup"
cat > /etc/cron.daily/projectbilal-backup <<'EOF'
#!/bin/sh
d=/var/lib/projectbilal
[ -f $d/projectbilal.db ] || exit 0
cp $d/projectbilal.db $d/backup/$(date +%F).db
find $d/backup -name '*.db' -mtime +14 -delete
EOF
chmod +x /etc/cron.daily/projectbilal-backup

echo "== start"
if [ -f $APP_DIR/.env ]; then
  systemctl restart projectbilal
  sleep 2
  systemctl --no-pager status projectbilal | head -5
else
  echo "No $APP_DIR/.env yet. Copy it (scp), chmod 600, chown $SVC_USER, then: systemctl restart projectbilal"
fi
echo "Done. Check: curl -s https://$DOMAIN/health"
