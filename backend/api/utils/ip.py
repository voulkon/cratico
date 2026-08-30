"""
Centralized client IP resolution.

This is the single source of truth for extracting the real client IP from
a request. All middleware, views, and utilities should import `get_client_ip`
from here — not from `api.utils.common` or `diavgeia_project.security_tracing`
(those legacy copies are kept only for backward compatibility and delegate
to this module).

Resolution order (most-trusted first):
    1. CF-Connecting-IP   — set by Cloudflare, contains only the real client IP.
                            Unspoofable as long as traffic transits Cloudflare.
    2. True-Client-IP     — set by Cloudflare Enterprise / some other CDNs.
    3. X-Forwarded-For    — leftmost entry is the original client when the
                            chain is trusted (Cloudflare → nginx → Django).
                            We skip private/loopback entries at the head of
                            the chain in case of misconfigured upstream proxies.
    4. X-Real-IP          — set by nginx (`$remote_addr`), which behind
                            Cloudflare is a Cloudflare edge IP. Used only as
                            a last resort.
    5. REMOTE_ADDR        — the direct TCP peer (nginx or Cloudflare).

Why CF-Connecting-IP first:
    Cloudflare strips any client-supplied CF-Connecting-IP header at the edge
    and replaces it with the real client IP. X-Forwarded-For, by contrast,
    is appended to — so a malicious client can prepend fake IPs. Reading
    X-Forwarded-For[0] blindly (as the legacy code did) lets clients pick
    their "IP" for rate-limiting / banning evasion.

When Cloudflare is NOT in front (local dev, direct nginx), CF-Connecting-IP
is absent and we fall through to X-Forwarded-For / REMOTE_ADDR as before.
"""

import ipaddress
from typing import Optional

# IP ranges we treat as "infrastructure" — never the real client.
# Cloudflare edge ranges: https://www.cloudflare.com/ips/
# We don't hardcode the full list (it changes); instead we treat any
# private/loopback/link-local address as non-client, and rely on
# CF-Connecting-IP being present to disambiguate when Cloudflare is in front.
def _is_infrastructure_ip(ip_str: str) -> bool:
    """Return True if the IP is private/loopback/link-local (i.e. a proxy, not a client)."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def get_client_ip(request) -> Optional[str]:
    """
    Extract the real client IP address from a Django request.

    See module docstring for the resolution order and trust model.
    """
    meta = request.META

    # 1. Cloudflare's canonical header (preferred when CF is in front)
    cf_ip = meta.get("HTTP_CF_CONNECTING_IP")
    if cf_ip:
        cf_ip = cf_ip.strip()
        if cf_ip and not _is_infrastructure_ip(cf_ip):
            return cf_ip
        # If CF-Connecting-IP is present but is a private IP, Cloudflare is
        # likely not actually in front (someone spoofed the header on a LAN).
        # Fall through to X-Forwarded-For.

    # 2. True-Client-IP (Cloudflare Enterprise / Akamai)
    true_client_ip = meta.get("HTTP_TRUE_CLIENT_IP")
    if true_client_ip:
        true_client_ip = true_client_ip.strip()
        if true_client_ip and not _is_infrastructure_ip(true_client_ip):
            return true_client_ip

    # 3. X-Forwarded-For — pick the leftmost non-infrastructure IP.
    #    Cloudflare appends the real client IP to the end of any client-supplied
    #    XFF, so the rightmost is trustworthy; but if CF-Connecting-IP is absent
    #    (no Cloudflare), the leftmost is the original client under a trusted
    #    single-proxy chain (nginx). We scan left-to-right and return the first
    #    public IP — this handles both "client → nginx" and rejects spoofed
    #    private IPs prepended by the client.
    xff = meta.get("HTTP_X_FORWARDED_FOR")
    if xff:
        for candidate in (c.strip() for c in xff.split(",")):
            if candidate and not _is_infrastructure_ip(candidate):
                return candidate

    # 4. X-Real-IP (set by nginx to $remote_addr)
    x_real_ip = meta.get("HTTP_X_REAL_IP")
    if x_real_ip:
        x_real_ip = x_real_ip.strip()
        if x_real_ip:
            return x_real_ip

    # 5. Direct peer
    return meta.get("REMOTE_ADDR")
