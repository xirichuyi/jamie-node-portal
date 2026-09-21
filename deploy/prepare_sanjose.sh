#!/bin/bash
# New node only. Does not enable a proxy inbound or modify existing applications.
set -euo pipefail
echo 'Retired one-time installer. Use deploy/node_manager.py add --prepare.'
exit 1
umask 077
test "$(id -u)" = 0
test ! -e /usr/local/x-ui
test ! -e /etc/x-ui/x-ui.db
install -d -m 700 /root/codex-backups/sanjose-node-20260921
ufw status > /root/codex-backups/sanjose-node-20260921/ufw-before.txt
# Management API is reachable only by the existing master; no public admin UI.
ufw allow from 138.2.82.194 to any port 48177 proto tcp
curl --fail --silent --show-error --location --max-time 60 \
  https://raw.githubusercontent.com/MHSanaei/3x-ui/v3.8.0/install.sh \
  -o /root/codex-backups/sanjose-node-20260921/install.sh
export XUI_NONINTERACTIVE=1 XUI_PANEL_PORT=48177 XUI_SSL_MODE=none
export XUI_DB_TYPE=sqlite XUI_ENABLE_FAIL2BAN=false XUI_SERVER_IP=192.9.148.252
if ! bash /root/codex-backups/sanjose-node-20260921/install.sh v3.8.0 \
  > /root/codex-backups/sanjose-node-20260921/install.log 2>&1; then
  echo 'Installation failed; private log retained on node.'
  exit 1
fi
install -d -m 700 /etc/x-ui/tls
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
  -keyout /etc/x-ui/tls/node.key -out /etc/x-ui/tls/node.crt -days 3650 \
  -subj '/CN=192.9.148.252' -addext 'subjectAltName=IP:192.9.148.252,IP:127.0.0.1' \
  > /root/codex-backups/sanjose-node-20260921/cert.log 2>&1
/usr/local/x-ui/x-ui cert -webCert /etc/x-ui/tls/node.crt \
  -webCertKey /etc/x-ui/tls/node.key > /dev/null
systemctl restart x-ui
systemctl is-active --quiet x-ui
echo 'San Jose panel installed with TLS and source-restricted management; no proxy inbound enabled.'
