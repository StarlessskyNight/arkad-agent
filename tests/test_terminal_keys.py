"""Shift+Enter → newline, for terminals that send it as ESC+CR (VS Code/Cursor)."""
import asyncio

import pytest

from arkad.tui.terminal_keys import install


def _keys(raw: str) -> list[str]:
    from textual._xterm_parser import XTermParser

    install()
    parser = XTermParser()
    events = list(parser.feed(raw)) + list(parser.feed(""))
    return [e.key for e in events if hasattr(e, "key")]


def test_esc_cr_parses_as_alt_enter_without_breaking_other_keys():
    assert _keys("a\x1b\rb") == ["a", "alt+enter", "b"]
    assert _keys("\x1b\n") == ["alt+enter"]
    assert _keys("\r") == ["enter"]
    assert _keys("\x1b") == ["escape"]
    assert _keys("\x1b[13;2u") == ["shift+enter"]  # kitty protocol terminals
    assert _keys("\x1bx") == ["alt+x"]


@pytest.fixture()
def hermetic_app(monkeypatch):
    monkeypatch.setenv("ARKAD_SKIP_UPDATE", "1")
    import arkad.mcp.registry as mcp_registry
    import arkad.storage.sessions as sessions
    import arkad.storage.settings as settings
    import arkad.tui.prompt_history as prompt_history
    import arkad.updater as updater
    from arkad import state

    monkeypatch.setattr(updater, "maybe_update_and_reexec", lambda: None)
    monkeypatch.setattr(mcp_registry, "auto_connect_servers", lambda console_print=None, **kw: None,
                        raising=False)
    monkeypatch.setattr(sessions, "db_init", lambda: None)
    monkeypatch.setattr(sessions, "db_create_session", lambda model: None)
    monkeypatch.setattr(settings.Settings, "save", lambda self: None)
    monkeypatch.setattr(prompt_history.PromptHistory, "_save", lambda self: None)
    monkeypatch.setattr(state, "save_trace_config", lambda: None)
    from arkad.tui.app import ArkadTUI

    monkeypatch.setattr(ArkadTUI, "_warm_model_catalogs_background", lambda self: None)
    monkeypatch.setattr(ArkadTUI, "_run_turn", lambda self, *a, **k: None)  # no model call
    return ArkadTUI


def test_cursor_shift_enter_inserts_a_newline_instead_of_submitting(hermetic_app):
    """The bytes Cursor sends for Shift+Enter (ESC CR) end up as a line break."""
    from arkad.tui.transcript import UserBlock

    async def run() -> None:
        app = hermetic_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.2)
            await pilot.press(*_keys("line one\x1b\rline two"))
            await pilot.pause(0.1)
            prompt = app.query_one("#prompt")
            assert prompt.text == "line one\nline two"
            assert not list(app.query(UserBlock))  # nothing was sent

            await pilot.press(*_keys("\r"))  # plain Enter still submits
            await pilot.pause(0.2)
            assert [b.text for b in app.query(UserBlock)] == ["line one\nline two"]

    asyncio.run(run())
