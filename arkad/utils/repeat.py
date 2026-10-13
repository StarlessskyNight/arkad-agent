"""Repeated-action detection for the model→tool turn loops.

The runaway guard (``constants.models.MAX_TURN_ITERATIONS``) is a hard ceiling:
it stops a turn that has already spent the whole budget. This module catches the
common shape much earlier — a model re-issuing the *same* tool call with the
*same* arguments turn after turn (a file it can't find, a command that keeps
failing, a search that returns nothing new).

Policy: warn once at ``REPEAT_CALL_LIMIT``, then stop if it happens again. A
single nudge keeps legitimate repeat loops alive ("run the tests until green"
repeats ``run_bash("pytest")``), while a second identical call proves the model
did not take the hint and is just spinning.

One guard instance per user turn — the streak resets every turn.
"""
from __future__ import annotations

import json
from typing import Any

from ..constants.models import REPEAT_CALL_LIMIT

WARN = "warn"
STOP = "stop"


def _canon(value: Any) -> str:
    """Stable string for a tool input, so arg order / spacing never differ."""
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(value)


def signature(resp) -> tuple[str, list[str]] | None:
    """``(batch signature, tool names)`` for *resp*, or None if it calls no tools."""
    calls: list[tuple[str, str]] = []
    for b in getattr(resp, "content", None) or []:
        if getattr(b, "type", None) == "tool_use":
            calls.append((getattr(b, "name", "") or "", _canon(getattr(b, "input", None))))
    if not calls:
        return None
    return "␟".join(f"{n}:{a}" for n, a in sorted(calls)), [n for n, _ in calls]


class RepeatGuard:
    """Count consecutive iterations that re-issue an identical tool-call batch."""

    def __init__(self, limit: int = REPEAT_CALL_LIMIT):
        self.limit = limit
        self.streak = 0
        self.tools: list[str] = []
        self._sig: str | None = None
        self._warned = False

    def check(self, resp) -> str | None:
        """``WARN``, ``STOP``, or None for this iteration's response."""
        sig = signature(resp)
        if sig is None:
            # A plain reply resets the streak — the model moved on.
            self._sig, self.streak, self.tools = None, 0, []
            self._warned = False
            return None
        if sig[0] == self._sig:
            self.streak += 1
        else:
            self._sig, self.streak, self.tools = sig[0], 1, sig[1]
        if self.streak == self.limit and not self._warned:
            self._warned = True
            return WARN
        if self.streak > self.limit:
            return STOP
        return None

    def warn_text(self) -> str:
        return (
            f"repeated action: identical tool call {'/'.join(self.tools) or 'tools'} "
            f"{self.streak} times in a row with the same arguments and no new result. "
            "Do not call it again unchanged — try different arguments or a different "
            "tool, or answer the user now with what you have."
        )

    def stop_text(self) -> str:
        return (
            f"repeated-action guard: stopped after {self.streak} identical "
            f"{'/'.join(self.tools) or 'tool'} calls with no new result. "
            "(set ARKAD_REPEAT_CALL_LIMIT to raise)"
        )


def inject_note(text: str) -> bool:
    """Append a plain-text nudge to the tool-result turn *render_assistant* just wrote.

    Both API paths accept a text block beside ``tool_result`` blocks in a user
    turn (Anthropic natively; ``auth.opencode_client`` splits it into a
    following user message), so this is safe on both.
    """
    from .. import state

    msgs = state.messages
    if not msgs:
        return False
    last = msgs[-1]
    if not isinstance(last, dict) or last.get("role") != "user":
        return False
    content = last.get("content")
    if not isinstance(content, list):
        return False
    content.append({"type": "text", "text": text})
    return True