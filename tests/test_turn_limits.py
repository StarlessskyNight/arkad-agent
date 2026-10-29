"""Runaway protection for the turn loops + legacy cancel-flag hygiene.

Both turn loops (legacy ``arkad.main._send_and_loop`` and the TUI mirror
``ArkadTUI._run_turn``) used to be unbounded ``while True``: a model that kept
emitting ``tool_use`` blocks and never returned ``end_turn`` spun forever —
unbounded token spend, repeated tool side effects, endless DB writes.
``constants.models.MAX_TURN_ITERATIONS`` (env ``ARKAD_MAX_ITERATIONS``, off by
default) optionally caps model→tool iterations per user turn; the loop then
breaks cleanly with a user-facing message. Arkad ships uncapped, like the Jarvis
harness: the repeated-action guard below is what stops a stuck turn.

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


def _tool(input=None, name="read_file"):
    return SimpleNamespace(type="tool_use", name=name, input=input or {}, id="t1")


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
    — the runaway shape. Each call gets distinct arguments so these tests
    exercise the iteration cap and not the repeated-action guard (that shape is
    ``test_repeated_legacy_turn_warns_then_stops``). ``render`` stands in for
    ``render_assistant``; returning True means "tool results exist → keep looping".
    """
    import arkad.main as m

    state = _isolate_state(monkeypatch)
    calls = {"n": 0}
    printed: list[str] = []

    def fake_stream():
        calls["n"] += 1
        out = list(blocks) if blocks is not None else [_tool(input={"n": calls["n"]})]
        return _resp(out, stop_reason=stop_reason)

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
        ("banana", 0),   # unparseable → default (off)
        ("", 0),         # empty → default (off)
        ("0", 0),        # explicit off
        ("-7", 0),       # clamped up to off
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


# ─── repeated-action detection (utils/repeat.py) ─────────────────────────


def _repeat_harness(monkeypatch, inputs):
    """Legacy loop + a model that repeats one tool call. ``render`` mirrors the
    real ``render_assistant``: it appends the tool_result turn the model reads
    next, then returns True."""
    import arkad.main as m
    import arkad.repl.render as render

    state = _isolate_state(monkeypatch)
    calls = {"n": 0}
    printed: list[str] = []
    seq = iter(inputs)

    def fake_stream():
        calls["n"] += 1
        return _resp([_tool(input=next(seq))], stop_reason="tool_use")

    def fake_render(resp):
        state.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]})
        return True

    monkeypatch.setattr(m, "call_claude_stream", fake_stream)
    monkeypatch.setattr(m, "render_assistant", fake_render)
    monkeypatch.setattr(m, "console", _FakeConsole(printed))
    monkeypatch.setattr(render, "MAX_TOOL_OUTPUT", 6000)  # imported eagerly, unused here
    return m, state, calls, printed


def test_streak_counts_only_identical_consecutive_calls():
    from arkad.utils.repeat import RepeatGuard

    g = RepeatGuard(limit=3)
    assert g.check(_resp([_tool(input={"path": "a.py"})])) is None
    assert g.check(_resp([_tool(input={"path": "b.py"})])) is None, "different args reset"
    assert g.check(_resp([_tool(input={"path": "a.py"})])) is None
    assert g.check(_resp([_tool(input={"path": "a.py"})])) is None
    assert g.check(_resp([_tool(input={"path": "a.py"})])) == "warn"
    assert g.check(_resp([_tool(input={"path": "a.py"})])) == "stop"


def test_arg_order_is_not_a_difference():
    from arkad.utils.repeat import RepeatGuard

    g = RepeatGuard(limit=3)
    g.check(_resp([_tool(input={"a": 1, "b": 2})]))
    assert g.streak == 1
    g.check(_resp([_tool(input={"b": 2, "a": 1})]))
    assert g.streak == 2, "same args in a different JSON order are the same call"


def test_a_plain_reply_resets_the_streak():
    from arkad.utils.repeat import RepeatGuard

    g = RepeatGuard(limit=3)
    g.check(_resp([_tool()]))
    g.check(_resp([_tool()]))
    g.check(_resp([_text("done")]))
    assert g.streak == 0
    assert g.check(_resp([_tool()])) is None, "counter starts over after progress"


def test_batch_signature_covers_every_tool_in_the_turn():
    from arkad.utils.repeat import RepeatGuard

    two = [_tool(name="read_file"), _tool(name="search_code")]
    g = RepeatGuard(limit=3)
    for _ in range(2):
        assert g.check(_resp(list(two))) is None
    assert g.check(_resp(list(two))) == "warn"
    g2 = RepeatGuard(limit=3)  # dropping one tool is a different batch → no warning
    for _ in range(2):
        g2.check(_resp(list(two)))
    assert g2.check(_resp([two[0]])) is None


def test_repeated_legacy_turn_warns_then_stops(monkeypatch):
    same = {"path": "nope.py"}
    m, state, calls, printed = _repeat_harness(monkeypatch, [dict(same)] * 10)
    monkeypatch.setattr(M, "MAX_TURN_ITERATIONS", 50)

    m._send_and_loop("keep calling the same thing")

    # limit 3 → warn on #3, stop on #4 — nowhere near the optional cap.
    assert calls["n"] == 4, calls["n"]
    assert any("repeated action" in p for p in printed), printed
    assert any("repeated-action guard" in p for p in printed), printed
    assert not any("runaway guard" in p for p in printed), printed
    # The nudge reached the model as part of the turn it reads next.
    notes = [
        b["text"]
        for msg in state.messages
        if isinstance(msg.get("content"), list)
        for b in msg["content"]
        if isinstance(b, dict) and b.get("type") == "text"
    ]
    assert any("repeated action" in t for t in notes), notes


def test_model_that_changes_its_mind_keeps_going(monkeypatch):
    """Many *different* calls in a row is ordinary work, not a loop — and with no
    cap set (the default) the turn runs as long as it is making progress."""
    import arkad.main as m

    state = _isolate_state(monkeypatch)
    calls = {"n": 0}
    printed: list[str] = []

    def fake_stream():
        calls["n"] += 1
        if calls["n"] > 60:
            return _resp([_text("done")], stop_reason="end_turn")
        return _resp([_tool(input={"path": f"f{calls['n']}.py"})], stop_reason="tool_use")

    def fake_render(resp):
        has_tool = any(getattr(b, "type", "") == "tool_use" for b in resp.content)
        if has_tool:
            state.messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]})
        return has_tool

    monkeypatch.setattr(m, "call_claude_stream", fake_stream)
    monkeypatch.setattr(m, "render_assistant", fake_render)
    monkeypatch.setattr(m, "console", _FakeConsole(printed))
    assert M.MAX_TURN_ITERATIONS == 0, "the runaway cap ships off"

    m._send_and_loop("read a lot of files")

    assert calls["n"] == 61, "no cap: the turn keeps going well past 50 model calls"
    assert not any("repeated" in p for p in printed), printed
    assert not any("runaway guard" in p for p in printed), printed


def test_an_opt_in_cap_still_stops_the_runaway_loop(monkeypatch):
    """Setting ARKAD_MAX_ITERATIONS still works for anyone who wants a ceiling."""
    paths = [{"path": f"f{i}.py"} for i in range(60)]
    m, _state, calls, printed = _repeat_harness(monkeypatch, paths)
    monkeypatch.setattr(M, "MAX_TURN_ITERATIONS", 8)

    m._send_and_loop("read a lot of files")

    assert calls["n"] == 8
    assert any("runaway guard" in p for p in printed), printed


def test_repeat_streak_resets_between_turns(monkeypatch):
    m, _state, calls, printed = _repeat_harness(monkeypatch, [{}] * 10)

    m._send_and_loop("first")
    assert calls["n"] == 4
    calls["n"] = 0
    m._send_and_loop("second")
    assert calls["n"] == 4, "the streak — like the cap — is per user turn"


def test_tui_loop_stops_on_a_repeated_tool_call(hermetic_app, monkeypatch):
    """TUI parity: same warn-then-stop shape as the legacy loop."""
    import asyncio

    import arkad.repl.render as render
    import arkad.repl.stream as stream
    from arkad import state

    from arkad import loop as L

    L.end_loop()
    monkeypatch.setattr(M, "MAX_TURN_ITERATIONS", 50)
    calls = {"n": 0}

    def fake_stream():
        calls["n"] += 1
        return _resp([_tool(input={"path": "nope.py"})], stop_reason="tool_use")

    def fake_render(resp):
        state.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "not found"}]})
        return True

    monkeypatch.setattr(stream, "call_claude_stream", fake_stream)
    monkeypatch.setattr(render, "render_assistant", fake_render)
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
            app._begin_turn("keep calling the same thing")
            end = time.monotonic() + 5.0
            while app._busy and time.monotonic() < end:
                await pilot.pause(0.05)
            assert not app._busy, "must end the turn via _turn_done (no dangling busy)"
            await pilot.pause(0.2)
            text = app.query_one("#transcript").plain_text()
            assert "repeated action" in text, text
            assert "repeated-action guard" in text, text
            assert "runaway guard" not in text, text
            assert calls["n"] == 4, f"warn on #3, stop on #4 — got {calls['n']}"
            assert not app._turn_cancelled

    asyncio.run(run())
