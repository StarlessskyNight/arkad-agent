"""Tests for context-budget trimming and context-overflow recovery.

Covers:
  - trim_messages pack budget (newest KEEP_PACKS + MAX_PACK_CHARS cap)
  - force_trim_messages (aggressive recovery path used by stream.py)
  - _call_claude_stream recovering from a provider "prompt is too long"
    rejection: trim + heal + retry once, then a clear error.
"""
from types import SimpleNamespace

import pytest

import arkad.repl.stream as stream
from anthropic import APIStatusError
from arkad.console import ArkadAPIError
from arkad.repl import trim as trim_mod
from arkad.repl.trim import (
    CHAR_BUDGET,
    KEEP_PACKS,
    KEEP_TURNS,
    MAX_PACK_CHARS,
    TRIM_STATS,
    force_trim_messages,
    trim_messages,
)


# ── helpers ────────────────────────────────────────────────────────────────

def _status_error(message: str, status: int):
    response = SimpleNamespace(
        status_code=status, request=SimpleNamespace(), headers={}
    )
    return APIStatusError(message, response=response, body={})


def _turn(i: int, pack_size: int = 0, plain_size: int = 0) -> dict:
    """One user turn: text plus optional tool_result blocks (as in real
    Anthropic history — tool results live inside the user message)."""
    content = [{"type": "text", "text": f"question {i}"}]
    if pack_size:
        content.append({
            "type": "tool_result",
            "tool_use_id": f"tool-{i}",
            "content": "=== Connected Context Pack ===\n" + "x" * pack_size,
        })
    if plain_size:
        content.append({
            "type": "tool_result",
            "tool_use_id": f"plain-{i}",
            "content": "y" * plain_size,
        })
    return {"role": "user", "content": content}


def _pairing_intact(messages) -> bool:
    """Every tool_result keeps its tool_use_id (stubbing must not break pairs)."""
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                if not block.get("tool_use_id"):
                    return False
    return True


def _packs(messages):
    return [
        b for m in messages for b in (m.get("content") or [])
        if isinstance(b, dict) and b.get("type") == "tool_result"
        and str(b.get("content", "")).startswith("=== Connected Context Pack ===")
    ]


# ── pack budget ────────────────────────────────────────────────────────────

class TestPackBudget:
    def test_no_trim_under_budget(self):
        msgs = [_turn(i, pack_size=100) for i in range(12)]
        out = trim_messages(msgs)
        assert out is msgs  # untouched
        assert TRIM_STATS["trimmed"] is False

    def test_newest_packs_kept_older_stubbed(self):
        # 30 turns × 30K-char packs → far over CHAR_BUDGET. The last KEEP_TURNS
        # turns stay verbatim; the pack budget (150K) is entirely consumed by
        # the newest packs, so every older pack is stubbed.
        size = 30_000
        msgs = [_turn(i, pack_size=size) for i in range(30)]
        out = trim_messages(msgs)
        assert _pairing_intact(out)
        kept = _packs(out)
        assert len(kept) == KEEP_TURNS
        assert {b["tool_use_id"] for b in kept} == {
            f"tool-{i}" for i in range(30 - KEEP_TURNS, 30)
        }
        assert TRIM_STATS["packs_kept"] == KEEP_TURNS
        assert TRIM_STATS["packs_stubbed"] == 30 - KEEP_TURNS
        assert TRIM_STATS["trimmed"] is True

    def test_budget_allows_extra_packs(self):
        # 10K packs: the budget rescues some older packs beyond KEEP_PACKS.
        # (The 2 exempt packs also count against MAX_PACK_CHARS — conservative.)
        size = 10_000
        msgs = [_turn(i, pack_size=size) for i in range(30)]
        out = trim_messages(msgs)
        kept = _packs(out)
        keep_ids = trim_mod._pack_keep_ids(msgs)
        expected = KEEP_TURNS + max(0, len(keep_ids) - KEEP_TURNS)
        assert len(kept) == expected > KEEP_TURNS
        total_kept = sum(len(b["content"]) for b in kept)
        assert total_kept <= KEEP_TURNS * size + KEEP_PACKS * size + MAX_PACK_CHARS
        assert _pairing_intact(out)

    def test_plain_results_stubbed_regardless(self):
        msgs = [_turn(i, plain_size=30_000) for i in range(30)]
        out = trim_messages(msgs)
        stubs = [
            b for m in out for b in (m.get("content") or [])
            if isinstance(b, dict) and b.get("type") == "tool_result"
            and b.get("content") == "[output trimmed to save context]"
        ]
        # older plain results are stubbed; recent window ones stay
        assert 0 < len(stubs) < 30
        assert _pairing_intact(out)


# ── force_trim_messages ────────────────────────────────────────────────────

class TestForceTrim:
    def test_stubs_everything_outside_keep_window(self):
        msgs = [_turn(i, pack_size=5000, plain_size=5000)
                for i in range(KEEP_TURNS + 6)]
        out = force_trim_messages(msgs)
        assert out is msgs  # in place
        user_msgs = [m for m in msgs if m.get("role") == "user"]
        assert len(user_msgs) == KEEP_TURNS + 6  # user text never dropped
        stubbed = sum(
            1 for m in msgs for b in (m.get("content") or [])
            if isinstance(b, dict) and b.get("type") == "tool_result"
            and str(b.get("content", "")).startswith("[")
        )
        assert stubbed == 12  # 6 old turns × (1 pack + 1 plain)
        assert _pairing_intact(msgs)

    def test_recent_window_untouched(self):
        msgs = [_turn(i, pack_size=5000) for i in range(KEEP_TURNS + 2)]
        force_trim_messages(msgs)
        recent = [
            b for m in msgs[-KEEP_TURNS:] for b in (m.get("content") or [])
            if isinstance(b, dict) and b.get("type") == "tool_result"
        ]
        assert len(recent) == KEEP_TURNS
        assert all(str(b["content"]).startswith("=== Connected Context Pack ===")
                   for b in recent)


# ── overflow recovery in call_claude_stream ────────────────────────────────

def _final():
    return SimpleNamespace(
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        content=[SimpleNamespace(type="text", text="hi")],
        stop_reason="end_turn",
    )


class _Ctx:
    def __init__(self, behavior):
        self._behavior = behavior

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self._behavior()

    def close(self):
        pass


class _Messages:
    def __init__(self, script):
        self.script = script
        self.calls = 0

    def stream(self, **kwargs):
        behavior = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return _Ctx(behavior)


@pytest.fixture
def arkad(monkeypatch):
    from arkad import state

    monkeypatch.setattr(stream, "build_system", lambda: "sys")
    monkeypatch.setattr(stream, "select_tools", lambda msgs: [])
    monkeypatch.setattr(stream, "trim_messages", lambda msgs: msgs)
    monkeypatch.setattr(stream, "_heal_message_history", lambda: None)
    monkeypatch.setattr(stream, "report_turn_phase", lambda *a, **k: None)
    monkeypatch.setattr(stream, "_report_http_timeout", lambda: None)
    monkeypatch.setattr(stream.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        stream, "console", SimpleNamespace(print=lambda m="", *a, **k: None)
    )

    monkeypatch.setattr(state, "messages", [{"role": "user", "content": "hi"}])
    monkeypatch.setattr(state, "stream_reply_live", False)
    monkeypatch.setattr(state, "show_internal", False)
    monkeypatch.setattr(state, "think_mode", False)
    monkeypatch.setattr(state, "provider", "anthropic")
    monkeypatch.setattr(state, "MODEL", "test-model")
    state.cancel_requested.clear()
    stream._got_first_delta = False

    def install(script):
        client = SimpleNamespace(messages=_Messages(script))
        monkeypatch.setattr(state, "client", client)
        return client

    return SimpleNamespace(install=install, state=state)


def _context_overflow():
    raise _status_error("prompt is too long: 250000 tokens > 200000 maximum", 400)


class TestOverflowRecovery:
    def test_trims_and_retries_once(self, arkad, monkeypatch):
        trimmed = []
        real_trim = stream.force_trim_messages

        def spy():
            trimmed.append(True)
            real_trim()

        monkeypatch.setattr(stream, "force_trim_messages", spy)

        client = arkad.install([_context_overflow, lambda: _final()])
        final = stream.call_claude_stream()
        assert final.usage.input_tokens == 10
        assert client.messages.calls == 2  # overflow + one retry
        assert trimmed == [True]

    def test_second_overflow_raises_actionable_error(self, arkad):
        client = arkad.install([_context_overflow])  # always overflows
        with pytest.raises(ArkadAPIError) as exc:
            stream.call_claude_stream()
        assert "context window exceeded" in str(exc.value)
        assert client.messages.calls == 2  # exactly one recovery attempt

    def test_unrelated_400_does_not_trigger_recovery(self, arkad, monkeypatch):
        trimmed = []
        monkeypatch.setattr(
            stream, "force_trim_messages", lambda: trimmed.append(True)
        )

        def bad_request():
            raise _status_error("model 'test-model' not found", 400)

        client = arkad.install([bad_request])
        with pytest.raises(Exception):  # raw SDK error: unhandled 400s re-raise (pre-existing)
            stream.call_claude_stream()
        assert client.messages.calls == 1  # no trim, no retry
        assert trimmed == []

    def test_detection_helper(self):
        assert stream._is_context_length_error(
            _status_error("Error code: 400 - prompt is too long", 400)
        )
        assert stream._is_context_length_error(
            _status_error("413 context_length_exceeded", 413)
        )
        assert not stream._is_context_length_error(
            _status_error("400 model not found", 400)
        )
        assert not stream._is_context_length_error(
            _status_error("401 invalid api key", 401)
        )
