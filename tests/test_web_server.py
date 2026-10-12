"""Tests for the web server: port/host selection and hardened request handling."""
from __future__ import annotations

import http.client
import json
import socket

import pytest

from arkad.web.bridge import WebBridge
from arkad.web.server import (
    _local_urls,
    default_web_host,
    resolve_web_port,
    start_web_server,
    stop_web_server,
)


def test_resolve_web_port_skips_busy_port():
    preferred = 28765
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", preferred))
        blocker.listen(1)
        resolved = resolve_web_port("127.0.0.1", preferred, max_tries=5)
    assert resolved == preferred + 1


# ─── Bind host ───────────────────────────────────────────────────────────


def test_default_bind_host_is_loopback(monkeypatch):
    monkeypatch.delenv("ARKAD_WEB_HOST", raising=False)
    assert default_web_host() == "127.0.0.1"
    monkeypatch.setenv("ARKAD_WEB_HOST", "0.0.0.0")
    assert default_web_host() == "0.0.0.0"


def test_start_web_server_defaults_to_loopback_and_advertises_no_lan_url(monkeypatch):
    monkeypatch.delenv("ARKAD_WEB_HOST", raising=False)
    bridge = WebBridge()
    server, urls, _port = start_web_server(bridge=bridge, app=None, port=28971)
    try:
        assert server.server_address[0] == "127.0.0.1"
        # A loopback bind must not print/QR a LAN address — it would be a dead link.
        assert all("127.0.0.1" in u or "localhost" in u for u in urls)
        assert len(urls) <= 2
    finally:
        stop_web_server(server, bridge)


def test_local_urls_skip_lan_addresses_when_bound_to_loopback():
    urls = _local_urls(9000, "tok", "127.0.0.1")
    assert urls == [
        "http://127.0.0.1:9000/?token=tok",
        "http://localhost:9000/?token=tok",
    ]


def test_local_urls_include_the_bind_host_when_it_is_a_lan_address():
    urls = _local_urls(9000, "tok", "192.168.0.5")
    assert urls[0] == "http://127.0.0.1:9000/?token=tok"
    assert "http://192.168.0.5:9000/?token=tok" in urls


# ─── Hardened request handling (live server) ─────────────────────────────


def _request(port, method, path, headers=None, body=None):
    """One raw request — unlike urlopen it does not follow the 302 and lets
    us forge the Host header (a DNS-rebinding browser sends its own name)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        res = conn.getresponse()
        return res.status, dict(res.getheaders()), res.read()
    finally:
        conn.close()


class _Remote:
    """A loopback server plus its bridge, torn down afterwards."""

    def __init__(self, port: int = 28972):
        self.bridge = WebBridge()
        self.server, _urls, self.port = start_web_server(
            bridge=self.bridge, app=None, port=port, host="127.0.0.1"
        )

    def close(self):
        stop_web_server(self.server, self.bridge)


@pytest.fixture
def remote():
    r = _Remote()
    yield r
    r.close()


def test_plain_curl_from_loopback_still_gets_the_token_redirect(remote):
    """No Sec-Fetch / Origin headers: curl or typing the URL by hand."""
    status, headers, _ = _request(remote.port, "GET", "/")
    assert status == 302
    assert headers["Location"] == f"/?token={remote.bridge.token}"


def test_browser_navigation_marked_none_still_gets_the_token(remote):
    status, headers, _ = _request(
        remote.port, "GET", "/", {"Host": f"127.0.0.1:{remote.port}", "Sec-Fetch-Site": "none"}
    )
    assert status == 302
    assert headers["Location"] == f"/?token={remote.bridge.token}"


def test_dns_rebinding_host_never_gets_the_token(remote):
    """A rebinding page follows the 302 same-origin and would read the token
    from the URL — the Host of an attacker-controlled name must see only the
    tokenless shell."""
    status, headers, body = _request(
        remote.port, "GET", "/", {"Host": "rebind.attacker.example:8765"}
    )
    assert status == 200
    assert "Location" not in headers
    assert remote.bridge.token.encode() not in body


def test_cross_site_fetch_never_gets_the_token(remote):
    status, headers, _ = _request(
        remote.port, "GET", "/",
        {"Host": f"127.0.0.1:{remote.port}", "Sec-Fetch-Site": "cross-site"},
    )
    assert status == 200
    assert "Location" not in headers


def test_origin_mismatch_never_gets_the_token(remote):
    status, headers, _ = _request(
        remote.port, "GET", "/",
        {"Host": f"127.0.0.1:{remote.port}", "Origin": "http://evil.example"},
    )
    assert status == 200
    assert "Location" not in headers
    # An Origin matching the Host is a same-origin script — harmless to redirect.
    status, headers, _ = _request(
        remote.port, "GET", "/",
        {"Host": f"127.0.0.1:{remote.port}", "Origin": f"http://127.0.0.1:{remote.port}"},
    )
    assert status == 302
    assert headers["Location"] == f"/?token={remote.bridge.token}"


def test_oversized_json_body_is_refused_with_413(remote):
    body = json.dumps({"text": "x" * (1 << 20)}).encode()  # > 1 MB
    status, _headers, raw = _request(
        remote.port, "POST", "/api/prompt",
        {"Authorization": f"Bearer {remote.bridge.token}",
         "Content-Length": str(len(body))},
        body=body,
    )
    assert status == 413
    assert json.loads(raw)["code"] == "too_large"


def test_invalid_content_length_is_refused_with_400(remote):
    status, _headers, raw = _request(
        remote.port, "POST", "/api/prompt",
        {"Authorization": f"Bearer {remote.bridge.token}", "Content-Length": "banana"},
    )
    assert status == 400
    assert json.loads(raw)["code"] == "bad_length"


def test_responses_carry_nosniff_and_no_referrer(remote):
    status, headers, _ = _request(remote.port, "GET", "/static/js/app.js")
    assert status == 200
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
