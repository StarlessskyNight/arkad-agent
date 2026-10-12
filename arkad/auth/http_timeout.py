"""Shared HTTP timeout settings for provider SDK clients."""
from __future__ import annotations

import os

import httpx


def _env_seconds(name: str, default: float) -> float:
    """Parse a timeout env var; blank or non-numeric values fall back.

    A malformed value (e.g. ``ARKAD_HTTP_READ_TIMEOUT=ten``) must never crash
    client construction — a bad timeout is a tuning mistake, not a reason to
    refuse to boot.
    """
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def http_read_timeout_seconds(*, openrouter: bool = False) -> float:
    """Seconds to wait between bytes on a streaming HTTP response."""
    return _env_seconds("ARKAD_HTTP_READ_TIMEOUT", 240.0 if openrouter else 600.0)


def arkad_http_timeout(*, openrouter: bool = False) -> httpx.Timeout:
    """Limits how long we wait between bytes on streaming responses."""
    read = http_read_timeout_seconds(openrouter=openrouter)
    c = _env_seconds("ARKAD_HTTP_CONNECT_TIMEOUT", 30.0)
    return httpx.Timeout(connect=c, read=read, write=c, pool=c)
