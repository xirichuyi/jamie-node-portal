#!/bin/bash
# Usage: bash prepare_small_node.sh PUBLIC_IP MANAGEMENT_PORT MASTER_IP
# Dedicated nft table: leaves existing rules and applications untouched.
set -euo pipefail
umask 077
ip="$1"
port="$2"
master_ip="$3"
test "$(id -u)" = 0
test ! -e /usr/local/x-ui
test ! -e /etc/x-ui/x-ui.db
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
install -d -m 700 /root/codex-backups/jamie-node-20260921
nft list ruleset > /root/codex-backups/jamie-node-20260921/firewall-before.nft
python3 - "$port" "$master_ip" <<'PY'
from pathlib import Path
import sys
import ipaddress
port=int(sys.argv[1])
assert 1024 <= port <= 65535
master_ip=str(ipaddress.IPv4Address(sys.argv[2]))
assert ipaddress.ip_address(master_ip).is_global
Path('/etc/jamie-node-management.nft').write_text('''table inet jamie_node_management {
 chain input {
  type filter hook input priority -10; policy accept;
  iifname "lo" tcp dport PORT accept
  ip saddr MASTER tcp dport PORT accept
  tcp dport PORT drop
 }
}
'''.replace('PORT',str(port)).replace('MASTER', master_ip))
Path('/etc/systemd/system/jamie-node-firewall.service').write_text('''[Unit]
Description=Restrict Jamie node management to master
Before=x-ui.service
After=network-pre.target
[Service]
Type=oneshot
ExecStart=/usr/sbin/nft -f /etc/jamie-node-management.nft
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
''')
drop=Path('/etc/systemd/system/x-ui.service.d')
drop.mkdir(exist_ok=True)
(drop/'resources.conf').write_text('''[Unit]
Requires=jamie-node-firewall.service
After=jamie-node-firewall.service
[Service]
MemoryHigh=240M
MemoryMax=320M
CPUQuota=50%
TasksMax=128
''')
PY
systemctl daemon-reload
systemctl enable --now jamie-node-firewall.service
curl --fail --silent --show-error --location --max-time 60 \
 https://raw.githubusercontent.com/MHSanaei/3x-ui/v3.8.0/install.sh \
 -o /root/codex-backups/jamie-node-20260921/install.sh
export XUI_NONINTERACTIVE=1 XUI_PANEL_PORT="$port" XUI_SSL_MODE=none
export XUI_DB_TYPE=sqlite XUI_ENABLE_FAIL2BAN=false XUI_SERVER_IP="$ip"
if ! bash /root/codex-backups/jamie-node-20260921/install.sh v3.8.0 \
 > /root/codex-backups/jamie-node-20260921/install.log 2>&1; then
 echo 'Installation failed; private log retained on node.'
 exit 1
fi
install -d -m 700 /etc/x-ui/tls
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
 -keyout /etc/x-ui/tls/node.key -out /etc/x-ui/tls/node.crt -days 3650 \
 -subj "/CN=$ip" -addext "subjectAltName=IP:$ip,IP:127.0.0.1" \
 > /root/codex-backups/jamie-node-20260921/cert.log 2>&1
/usr/local/x-ui/x-ui cert -webCert /etc/x-ui/tls/node.crt -webCertKey /etc/x-ui/tls/node.key > /dev/null
systemctl daemon-reload
systemctl restart x-ui
systemctl is-active x-ui
