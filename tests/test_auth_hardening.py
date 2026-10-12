"""Auth hardening: env timeout parsing (P3) and /responses tool-error retry (P2).

- ``arkad/auth/http_timeout.py``: a non-numeric ``ARKAD_HTTP_*_TIMEOUT`` env var
  used to raise ValueError during client construction; it now falls back to the
  default.
- ``arkad/auth/opencode_client.py`` (responses branch): a tool-related upstream
  error used to retry with ALL tools stripped — including the free tier's
  bash/read identity gate, which guarantees a masked 403 FreeTierError. The
  chat branch already refused to strip when gate tools are present; the
  responses branch now matches.
"""
from __future__ import annotations

import pytest

from arkad.auth.http_timeout import arkad_http_timeout, http_read_timeout_seconds

# ── env timeout parsing ──────────────────────────────────────────────────────


def test_timeout_defaults_when_env_unset(monkeypatch):
    monkeypatch.delenv("ARKAD_HTTP_READ_TIMEOUT", raising=False)
    monkeypatch.delenv("ARKAD_HTTP_CONNECT_TIMEOUT", raising=False)
    assert http_read_timeout_seconds() == 600.0
    assert http_read_timeout_seconds(openrouter=True) == 240.0
    t = arkad_http_timeout()
    assert (t.connect, t.read, t.write, t.pool) == (30.0, 600.0, 30.0, 30.0)


def test_numeric_timeout_env_is_used(monkeypatch):
    monkeypatch.setenv("ARKAD_HTTP_READ_TIMEOUT", " 42 ")
    monkeypatch.setenv("ARKAD_HTTP_CONNECT_TIMEOUT", "5")
    assert http_read_timeout_seconds() == 42.0
    assert http_read_timeout_seconds(openrouter=True) == 42.0
    t = arkad_http_timeout()
    assert (t.connect, t.read) == (5.0, 42.0)


@pytest.mark.parametrize("bad", ["ten", "60s", "1,5", "1..2", "nan seconds"])
def test_non_numeric_read_timeout_falls_back_to_default(monkeypatch, bad):
    monkeypatch.setenv("ARKAD_HTTP_READ_TIMEOUT", bad)
    assert http_read_timeout_seconds() == 600.0
    assert http_read_timeout_seconds(openrouter=True) == 240.0
    # and client construction keeps working
    assert arkad_http_timeout(openrouter=True).read == 240.0


def test_non_numeric_connect_timeout_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("ARKAD_HTTP_CONNECT_TIMEOUT", "soon")
    monkeypatch.delenv("ARKAD_HTTP_READ_TIMEOUT", raising=False)
    t = arkad_http_timeout()
    assert t.connect == 30.0
    assert t.read == 600.0  # read env untouched by the bad connect value


def test_blank_timeout_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("ARKAD_HTTP_READ_TIMEOUT", "   ")
    assert http_read_timeout_seconds() == 600.0


# ── /responses tool-error retry keeps the free-tier gate ─────────────────────

# A model the free-tier gateway serves on /responses (see _zen_wire).
RESPONSES_MODEL = "muse-spark-1.3-contributor-free"
_GATE_TOOLS = ["bash", "read"]


def _responses_client(**kwargs):
    from arkad.auth.opencode_client import OpenCodeClient

    kwargs.setdefault("responses_models", {RESPONSES_MODEL})
    return OpenCodeClient(api_key="x", base_url="http://127.0.0.1:9/v1", **kwargs)


def _tool_names(payload):
    return sorted(t["name"] for t in payload.get("tools") or [])


def _stream_responses(client, monkeypatch, create, tools=None):
    monkeypatch.setattr(client.messages._client.responses, "create", create)
    with client.messages.stream(
        model=RESPONSES_MODEL,
        tools=tools or [],
        messages=[{"role": "user", "content": "hi"}],
    ):
        pass


def test_responses_tool_error_does_not_drop_the_free_tier_gate(monkeypatch):
    """Stripping bash/read on retry only ever produced a masked 403."""
    from arkad.auth.arkad_agent import build_arkad_agent_client

    client = build_arkad_agent_client()
    calls: list[dict] = []

    def create(**kw):
        calls.append(dict(kw))
        raise RuntimeError("400 invalid_request: unknown parameter 'tools'")

    with pytest.raises(RuntimeError):
        _stream_responses(client, monkeypatch, create)

    # No tool-stripping retry: the one request sent still carries the gate.
    assert len(calls) == 1
    assert _tool_names(calls[0]) == _GATE_TOOLS


def test_responses_tool_error_retries_once_without_tools_when_no_gate(monkeypatch):
    client = _responses_client()
    calls: list[dict] = []

    def create(**kw):
        calls.append(dict(kw))
        if len(calls) == 1:
            raise RuntimeError("400 invalid_request: unknown parameter 'tool_choice'")
        raise LookupError("retry reached")

    real_tool = {
        "name": "run_bash",
        "description": "d",
        "input_schema": {"type": "object", "properties": {}},
    }
    with pytest.raises(LookupError, match="retry reached"):
        _stream_responses(client, monkeypatch, create, tools=[real_tool])

    assert len(calls) == 2
    assert _tool_names(calls[0]) == ["run_bash"]
    assert "tools" not in calls[1]


def test_responses_non_tool_error_is_never_retried(monkeypatch):
    from arkad.auth.arkad_agent import build_arkad_agent_client

    client = build_arkad_agent_client()
    calls: list[dict] = []

    def create(**kw):
        calls.append(dict(kw))
        raise RuntimeError("connection reset by peer")

    with pytest.raises(RuntimeError, match="connection reset"):
        _stream_responses(client, monkeypatch, create)

    assert len(calls) == 1
    assert _tool_names(calls[0]) == _GATE_TOOLS  # gate tools injected on send
