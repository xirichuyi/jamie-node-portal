#!/bin/bash
# New Alpine nodes only. Install bash before invoking this script.
set -euo pipefail
umask 077
ip="$1"
port="$2"
master_ip="$3"
test "$(id -u)" = 0
test ! -e /usr/local/x-ui
test ! -e /etc/x-ui/x-ui.db
apk add --no-cache curl python3 nftables openssl
install -d -m 700 /root/codex-backups/jamie-alpine
python3 - "$port" "$master_ip" <<'PY'
import ipaddress
import sys
from pathlib import Path
port = int(sys.argv[1])
assert 1024 <= port <= 65535
master = ipaddress.IPv4Address(sys.argv[2])
assert master.is_global
Path('/etc/jamie-node-management.nft').write_text(f'''table inet jamie_node_management {{
 chain input {{
  type filter hook input priority -10; policy accept;
  iifname "lo" tcp dport {port} accept
  ip saddr {master} tcp dport {port} accept
  tcp dport {port} drop
 }}
}}
''')
PY
cat > /etc/init.d/jamie-node-firewall <<'EOF'
#!/sbin/openrc-run
depend() { before x-ui; need net; }
start() {
 nft list table inet jamie_node_management >/dev/null 2>&1 || nft -f /etc/jamie-node-management.nft
}
EOF
chmod 755 /etc/init.d/jamie-node-firewall
rc-update add jamie-node-firewall default
rc-service jamie-node-firewall start
mkdir -p /etc/conf.d
cat > /etc/conf.d/x-ui <<'EOF'
export GOMEMLIMIT=24MiB
export GOGC=50
export GOMAXPROCS=1
rc_need="jamie-node-firewall"
EOF
curl -fsSL --max-time 60 https://raw.githubusercontent.com/MHSanaei/3x-ui/v3.8.0/install.sh \
 -o /root/codex-backups/jamie-alpine/install.sh
export GOMEMLIMIT=24MiB GOGC=50 GOMAXPROCS=1
export XUI_NONINTERACTIVE=1 XUI_PANEL_PORT="$port" XUI_SSL_MODE=none
export XUI_DB_TYPE=sqlite XUI_ENABLE_FAIL2BAN=false XUI_SERVER_IP="$ip"
bash /root/codex-backups/jamie-alpine/install.sh v3.8.0 \
 > /root/codex-backups/jamie-alpine/install.log 2>&1
install -d -m 700 /etc/x-ui/tls
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
 -keyout /etc/x-ui/tls/node.key -out /etc/x-ui/tls/node.crt -days 3650 \
 -subj "/CN=$ip" -addext "subjectAltName=IP:$ip,IP:127.0.0.1" \
 > /root/codex-backups/jamie-alpine/cert.log 2>&1
/usr/local/x-ui/x-ui cert -webCert /etc/x-ui/tls/node.crt -webCertKey /etc/x-ui/tls/node.key >/dev/null
rc-service x-ui restart
rc-service x-ui status
