"""
GitHub host resolution.

OctoFinance talks to two flavours of GitHub Enterprise Cloud, which expose the
same REST API on different hosts:

  * github.com                — API at https://api.github.com
  * <subdomain>.ghe.com       — GHE.com with data residency,
                                API at https://api.<subdomain>.ghe.com

A host is stored in its normalized form (``github.com`` or ``<sub>.ghe.com``);
the API and web base URLs are derived from it. GitHub Enterprise Server
(self-hosted, ``/api/v3``) is out of scope.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

DEFAULT_HOST = "github.com"

_GHE_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.ghe\.com$")
_ENTERPRISE_PATH_RE = re.compile(r"^/enterprises/([^/?#]+)")


def normalize_host(value: str | None) -> str:
    """Normalize user input to ``github.com`` or ``<subdomain>.ghe.com``.

    Accepts a bare host, an API host or any URL on the host, e.g.
    ``ACME.ghe.com``, ``api.acme.ghe.com`` or
    ``https://acme.ghe.com/enterprises/acme``. Empty input means github.com.
    Raises ValueError for anything else.
    """
    raw = (value or "").strip().lower()
    if not raw:
        return DEFAULT_HOST
    if "://" not in raw:
        raw = "https://" + raw
    host = (urlparse(raw).hostname or "").rstrip(".")
    if host.startswith("api."):
        host = host[len("api."):]
    if host in ("github.com", "www.github.com"):
        return DEFAULT_HOST
    if _GHE_HOST_RE.match(host):
        return host
    raise ValueError(
        f"Unsupported GitHub host '{value}'. Use github.com or <subdomain>.ghe.com "
        "(GitHub Enterprise Cloud with data residency)."
    )


def is_ghe_host(host: str | None) -> bool:
    return (host or DEFAULT_HOST) != DEFAULT_HOST


def api_base_url(host: str | None) -> str:
    host = host or DEFAULT_HOST
    return "https://api.github.com" if host == DEFAULT_HOST else f"https://api.{host}"


def web_base_url(host: str | None) -> str:
    return f"https://{host or DEFAULT_HOST}"


def host_from_api_base(base_url: str) -> str:
    """Inverse of :func:`api_base_url`; unknown bases fall back to github.com."""
    try:
        return normalize_host(base_url)
    except ValueError:
        return DEFAULT_HOST


def parse_enterprise_url(value: str) -> tuple[str, str] | None:
    """Split an enterprise URL into ``(host, slug)``.

    ``https://acme.ghe.com/enterprises/acme`` -> ``("acme.ghe.com", "acme")``.
    Returns None when ``value`` is a plain slug rather than a URL.
    """
    raw = (value or "").strip()
    if "/enterprises/" not in raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    match = _ENTERPRISE_PATH_RE.match(parsed.path)
    if not match:
        return None
    return normalize_host(parsed.hostname or ""), match.group(1)
