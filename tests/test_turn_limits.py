"""Runaway protection for the turn loops + legacy cancel-flag hygiene.

Both turn loops (legacy ``arkad.main._send_and_loop`` and the TUI mirror
``ArkadTUI._run_turn``) used to be unbounded ``while True``: a model that kept
emitting ``tool_use`` blocks and never returned ``end_turn`` spun forever —
unbounded token spend, repeated tool side effects, endless DB writes.
``constants.models.MAX_TURN_ITERATIONS`` (env ``ARKAD_MAX_ITERATIONS``) caps
model→tool iterations per user turn; the loop then breaks cleanly with a
user-facing message.

Also pins the legacy loop clearing ``state.cancel_requested`` at turn start
(only the TUI used to do that) and its cancel checkpoints around the
assistant-append, so a leftover cancel can't abort every later turn.

Fixtures/patterns reused from ``tests/test_empty_response.py`` (fake
``call_claude_stream`` + ``_FakeConsole``) and ``tests/test_turn_cancel.py``
(hermetic TUI app).
"""
from __future__ import annotations

import importlib
import os
import time
from types import SimpleNamespace

import pytest

from arkad.constants import models as M


# ─── response / console fakes (same shapes as test_empty_response.py) ────


def _resp(blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def _text(s):
    return SimpleNamespace(type="text", text=s)


def _tool():
    return SimpleNamespace(type="tool_use", name="read_file", input={}, id="t1")


class _FakeStatus:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConsole:
    def __init__(self, sink):
        self.sink = sink

    def status(self, *a, **k):
        return _FakeStatus()

    def print(self, msg="", *a, **k):
        self.sink.append(str(msg))


def _isolate_state(monkeypatch):
    from arkad import state

    monkeypatch.setattr(state, "messages", [])
    monkeypatch.setattr(state, "current_session_id", None)
    monkeypatch.setattr(state, "web_tool_used_this_turn", False)
    state.cancel_requested.clear()
    return state


@pytest.fixture(autouse=True)
def _restore_turn_cap():
    """Env-reload tests rewrite ``MAX_TURN_ITERATIONS`` — put it back."""
    yield
    os.environ.pop("ARKAD_MAX_ITERATIONS", None)
    importlib.reload(M)


def _legacy_harness(monkeypatch, *, stop_reason="tool_use", blocks=None, render=None):
    """Fake model + console for ``arkad.main._send_and_loop``.

    Default: the model *always* asks for another tool call (never ``end_turn``)
    — the runaway shape. ``render`` stands in for ``render_assistant``;
    returning True means "tool results exist → keep looping".
    """
    import arkad.main as m

    state = _isolate_state(monkeypatch)
    calls = {"n": 0}
    printed: list[str] = []

    def fake_stream():
        calls["n"] += 1
        return _resp(list(blocks if blocks is not None else [_tool()]),
                     stop_reason=stop_reason)

    monkeypatch.setattr(m, "call_claude_stream", fake_stream)
    monkeypatch.setattr(m, "render_assistant", render or (lambda resp: True))
    monkeypatch.setattr(m, "console", _FakeConsole(printed))
    return m, state, calls, printed


# ─── (a) runaway turn stops at the cap ───────────────────────────────────


def test_runaway_legacy_turn_stops_at_the_cap(monkeypatch):
    m, state, calls, printed = _legacy_harness(monkeypatch)
    monkeypatch.setattr(M, "MAX_TURN_ITERATIONS", 3)

    m._send_and_loop("keep going")  # would previously spin forever

    assert calls["n"] == 3, "exactly MAX_TURN_ITERATIONS model calls, then stop"
    assert any("runaway guard" in p for p in printed), printed
    assert any("model iterations" in p for p in printed), printed
    # Consistent state: every reply that ran was appended and the turn ended
    # via the normal path (no KeyboardInterrupt → no "interrupted").
    assistants = [msg for msg in state.messages if msg["role"] == "assistant"]
    assert len(assistants) == 3
    assert not any("interrupted" in p for p in printed), printed
    assert not state.cancel_requested.is_set()


def test_a_normal_short_turn_is_untouched_by_the_cap(monkeypatch):
    m, _state, calls, printed = _legacy_harness(
        monkeypatch, stop_reason="end_turn", blocks=[_text("hi")]
    )
    monkeypatch.setattr(M, "MAX_TURN_ITERATIONS", 3)

    m._send_and_loop("hello")

    assert calls["n"] == 1
    assert not any("runaway guard" in p for p in printed), printed


# ─── (b) the cap resets between turns ────────────────────────────────────


def test_cap_resets_between_turns(monkeypatch):
    m, _state, calls, printed = _legacy_harness(monkeypatch)
    monkeypatch.setattr(M, "MAX_TURN_ITERATIONS", 2)

    m._send_and_loop("first")
    assert calls["n"] == 2
    m._send_and_loop("second")
    assert calls["n"] == 4, "the cap is per user turn — the second turn gets its own budget"
    assert sum("runaway guard" in p for p in printed) == 2


# ─── (c) env override + invalid values ───────────────────────────────────


def test_env_cap_override_is_used_by_the_loop(monkeypatch):
    monkeypatch.setenv("ARKAD_MAX_ITERATIONS", "4")
    importlib.reload(M)
    assert M.MAX_TURN_ITERATIONS == 4

    m, _state, calls, printed = _legacy_harness(monkeypatch)
    m._send_and_loop("keep going")
    assert calls["n"] == 4
    assert any("runaway guard" in p for p in printed), printed


@pytest.mark.parametrize(
    "value,expected",
    [
        ("banana", 50),   # unparseable → default
        ("", 50),         # empty → default
        ("0", 1),         # clamped up (cap must allow at least one call)
        ("-7", 1),        # clamped up
        ("999999", 500),  # clamped down
    ],
)
def test_bad_env_cap_falls_back_safely(monkeypatch, value, expected):
    monkeypatch.setenv("ARKAD_MAX_ITERATIONS", value)
    importlib.reload(M)
    assert M.MAX_TURN_ITERATIONS == expected


# ─── (d) cancel hygiene in the legacy loop ───────────────────────────────


def test_cancel_flag_cleared_at_start_of_legacy_turn(monkeypatch):
    """A cancel left over from an earlier turn must not abort this one."""
    m, state, calls, printed = _legacy_harness(
        monkeypatch, stop_reason="end_turn", blocks=[_text("hi")]
    )
    state.cancel_requested.set()  # e.g. an earlier interrupted turn

    seen: dict = {}

    def fake_stream():
        calls["n"] += 1
        seen["flag"] = state.cancel_requested.is_set()
        return _resp([_text("hi")], stop_reason="end_turn")

    monkeypatch.setattr(m, "call_claude_stream", fake_stream)

    m._send_and_loop("hello")

    assert seen["flag"] is False, "the turn must start with a clean cancel flag"
    assert calls["n"] == 1  # without the fix this loop aborts before any call
    assert not any("interrupted" in p for p in printed), printed
    assert any(msg["role"] == "assistant" for msg in state.messages)
    assert not state.cancel_requested.is_set()


def test_cancel_arriving_mid_turn_drops_the_pending_reply(monkeypatch):
    """Cancel between the stream and the append → reply never lands (TUI parity)."""
    m, state, calls, printed = _legacy_harness(monkeypatch)

    def fake_stream():
        calls["n"] += 1
        state.cancel_requested.set()  # cancelled while the reply was finishing
        return _resp([_text("partial")], stop_reason="end_turn")

    monkeypatch.setattr(m, "call_claude_stream", fake_stream)

    m._send_and_loop("hello")

    assert calls["n"] == 1
    assert not any(msg["role"] == "assistant" for msg in state.messages)
    assert any("interrupted" in p for p in printed), printed


# ─── TUI: same cap, clean turn end ───────────────────────────────────────


@pytest.fixture()
def hermetic_app(monkeypatch):
    """ArkadTUI with persistence/updater/MCP stubbed out (as in test_turn_cancel)."""
    monkeypatch.setenv("ARKAD_SKIP_UPDATE", "1")

    import arkad.mcp.registry as mcp_registry
    import arkad.storage.sessions as sessions
    import arkad.storage.settings as settings
    import arkad.tui.prompt_history as prompt_history
    import arkad.updater as updater

    monkeypatch.setattr(updater, "maybe_update_and_reexec", lambda: None)
    monkeypatch.setattr(mcp_registry, "auto_connect_servers", lambda console_print=None, **kw: None,
                        raising=False)
    monkeypatch.setattr(sessions, "db_init", lambda: None)
    monkeypatch.setattr(sessions, "db_create_session", lambda model: None)
    monkeypatch.setattr(sessions, "db_append_message", lambda *a, **k: None)
    monkeypatch.setattr(sessions, "db_set_title_if_empty", lambda *a, **k: None)
    monkeypatch.setattr(settings.Settings, "save", lambda self: None)
    monkeypatch.setattr(prompt_history.PromptHistory, "_save", lambda self: None)

    from arkad.tui.app import ArkadTUI

    monkeypatch.setattr(ArkadTUI, "_warm_model_catalogs_background", lambda self: None)
    return ArkadTUI


def test_tui_loop_enforces_the_cap_and_ends_the_turn_cleanly(hermetic_app, monkeypatch):
    import asyncio

    import arkad.repl.render as render
    import arkad.repl.stream as stream
    from arkad import state

    from arkad import loop as L

    L.end_loop()  # a /loop left running elsewhere would re-arm _loop_after_turn
    monkeypatch.setattr(M, "MAX_TURN_ITERATIONS", 3)
    calls = {"n": 0}

    def fake_stream():
        calls["n"] += 1
        return _resp([_tool()], stop_reason="tool_use")  # never end_turn

    monkeypatch.setattr(stream, "call_claude_stream", fake_stream)
    monkeypatch.setattr(render, "render_assistant", lambda resp: True)
    monkeypatch.setattr(state, "client", object())
    monkeypatch.setattr(state, "messages", [])
    monkeypatch.setattr(state, "current_session_id", None)
    state.cancel_requested.clear()
    state.prompt_queue.clear()

    ArkadTUI = hermetic_app

    async def run():
        app = ArkadTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            app._begin_turn("keep going")
            end = time.monotonic() + 5.0
            while app._busy and time.monotonic() < end:
                await pilot.pause(0.05)
            assert not app._busy, "the cap must end the turn via _turn_done (no dangling busy)"
            await pilot.pause(0.2)
            text = app.query_one("#transcript").plain_text()
            assert "runaway guard" in text, text
            assert calls["n"] == 3, f"exactly the cap, got {calls['n']}"
            # Ended as a normal turn: not cancelled, flag cleared, replies kept.
            assert not app._turn_cancelled
            assert not state.cancel_requested.is_set()
            assistants = [msg for msg in state.messages if msg["role"] == "assistant"]
            assert len(assistants) == 3

    asyncio.run(run())
