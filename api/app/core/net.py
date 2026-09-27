"""Client address resolution behind the reverse proxy."""
import ipaddress

from starlette.requests import Request


def client_ip(request: Request, trusted_proxies: list[str]) -> str:
    """The real client IP.

    X-Forwarded-For is only believed when the direct peer is a trusted proxy;
    otherwise any client could claim any address (and dodge rate limits).
    Walks the header right to left and returns the first untrusted hop.
    """
    peer = request.client.host if request.client else "unknown"
    if peer not in trusted_proxies:
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    for hop in reversed(hops):
        if hop not in trusted_proxies and _is_ip(hop):
            return hop
    return peer


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False
