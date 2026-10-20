"""Deployment helpers for stable browser assets and trusted proxy addresses."""

import shutil
import time
from pathlib import Path

# Official https://www.cloudflare.com/ips-v4 and /ips-v6, verified 2026-10-20.
# Trust only Cloudflare peers; direct clients cannot spoof CF-Connecting-IP.
CLOUDFLARE_NETWORKS = (
    '173.245.48.0/20', '103.21.244.0/22', '103.22.200.0/22', '103.31.4.0/22',
    '141.101.64.0/18', '108.162.192.0/18', '190.93.240.0/20', '188.114.96.0/20',
    '197.234.240.0/22', '198.41.128.0/17', '162.158.0.0/15', '104.16.0.0/13',
    '104.24.0.0/14', '172.64.0.0/13', '131.0.72.0/22',
    '2400:cb00::/32', '2606:4700::/32', '2803:f800::/32', '2405:b500::/32',
    '2405:8100::/32', '2a06:98c0::/29', '2c0f:f248::/32',
)


def trusted_proxy_config():
    return '\n'.join(
        [f'    set_real_ip_from {network};' for network in CLOUDFLARE_NETWORKS]
        + ['    real_ip_header CF-Connecting-IP;']
    )


def retain_assets(previous, current, now=None):
    """Keep hashed assets for open tabs for 30 days, without replacing new files."""
    cutoff = (time.time() if now is None else now) - 30 * 86400
    source = Path(previous) / 'public' / 'assets'
    destination = Path(current) / 'public' / 'assets'
    for asset in source.rglob('*'):
        if asset.is_symlink() or not asset.is_file() or asset.stat().st_mtime < cutoff:
            continue
        target = destination / asset.relative_to(source)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset, target)
