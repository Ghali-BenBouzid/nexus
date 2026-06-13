from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def client_ip(request: Request) -> str:
    """The real client IP to rate-limit on. In production the request always
    arrives through the Cloudflare + Railway proxies, which set X-Forwarded-For;
    its left-most entry is the original client. request.client.host would be the
    proxy, so keying on it would lump every visitor into one bucket. Locally there
    is no proxy, so fall back to the socket address."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


# In-memory storage is fine for a single warm instance; horizontal scaling would
# need a shared backend (e.g. Redis), which is out of scope for the demo.
limiter = Limiter(key_func=client_ip)
