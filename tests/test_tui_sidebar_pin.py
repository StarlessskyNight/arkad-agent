"""The sidebar can be *pinned* — its visibility survives a restart.

``ui.sidebar`` is tri-state: ``None`` = auto by terminal width (the historic
behaviour, hidden below 150 columns), ``True``/``False`` = pinned regardless
of width. ``⌃B`` and ``/sidebar`` toggle and persist the pin.

Headless Pilot tests (``asyncio.run``, no pytest-asyncio); startup side
effects are stubbed like the other TUI tests.
"""
import asyncio
import json

import pytest

_MIN_WIDTH = 150  # mirrors _SIDEBAR_MIN_WIDTH in arkad.tui.app
NARROW, WIDE = 100, _MIN_WIDTH + 30  # below / above the auto-hide threshold


@pytest.fixture()
def hermetic_app(monkeypatch, tmp_path):
    monkeypatch.setenv("ARKAD_SKIP_UPDATE", "1")

    import arkad.updater as updater
    import arkad.mcp.registry as mcp_registry
    import arkad.storage.sessions as sessions
    import arkad.storage.settings as settings
    import arkad.tui.prompt_history as prompt_history
    from arkad import state

    monkeypatch.setattr(updater, "maybe_update_and_reexec", lambda: None)
    monkeypatch.setattr(mcp_registry, "auto_connect_servers", lambda console_print=None, **kw: None,
                        raising=False)
    monkeypatch.setattr(sessions, "db_init", lambda: None)
    monkeypatch.setattr(sessions, "db_create_session", lambda model: None)
    monkeypatch.setattr(prompt_history.PromptHistory, "_save", lambda self: None)
    monkeypatch.setattr(state, "save_trace_config", lambda: None)

    # Point Settings at a scratch file so a pin never touches the real config.
    scratch = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "SETTINGS_FILE", scratch)
    monkeypatch.setattr(settings, "get_settings", lambda: settings.Settings(scratch))

    from arkad.tui.app import ArkadTUI

    monkeypatch.setattr(ArkadTUI, "_warm_model_catalogs_background", lambda self: None)
    monkeypatch.setattr(ArkadTUI, "_load_sticky_pref", lambda self: None)
    return ArkadTUI


def _pin(value):
    """Write ui.sidebar to the scratch settings and return the file path."""
    from arkad.storage.settings import SETTINGS_FILE

    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    import json

    SETTINGS_FILE.write_text(json.dumps({"ui": {"sidebar": value}}))
    return SETTINGS_FILE


def _is_hidden(app) -> bool:
    return app.query_one("#sidebar").has_class("hidden")


def test_auto_still_follows_the_width(hermetic_app):
    async def run() -> None:
        _pin(None)
        for width, want_hidden in ((NARROW, True), (WIDE, False)):
            async with hermetic_app().run_test(size=(width, 30)) as pilot:
                await pilot.pause(0.2)
                assert _is_hidden(pilot.app) is want_hidden, f"width={width}"

    asyncio.run(run())


def test_pinned_open_wins_over_a_narrow_terminal(hermetic_app):
    """The bug this fixes: a narrow terminal used to hide a pinned sidebar."""
    async def run() -> None:
        _pin(True)
        async with hermetic_app().run_test(size=(NARROW, 30)) as pilot:
            await pilot.pause(0.2)
            assert not _is_hidden(pilot.app)

    asyncio.run(run())


def test_pinned_closed_wins_over_a_wide_terminal(hermetic_app):
    async def run() -> None:
        _pin(False)
        async with hermetic_app().run_test(size=(WIDE, 30)) as pilot:
            await pilot.pause(0.2)
            assert _is_hidden(pilot.app)

    asyncio.run(run())


def test_toggle_persists_across_a_restart(hermetic_app):
    async def run() -> None:
        # Wide + auto → visible; ⌃B pins it shut and writes that through.
        _pin(None)
        async with hermetic_app().run_test(size=(WIDE, 30)) as pilot:
            await pilot.pause(0.2)
            app = pilot.app
            assert not _is_hidden(app)
            await pilot.press("ctrl+b")
            await pilot.pause(0.2)
            assert app._sidebar_pref is False  # pinned, not auto
            assert _is_hidden(app)

        # The scratch file now holds the pin; a fresh app must honour it.
        from arkad.storage.settings import SETTINGS_FILE

        assert json.loads(SETTINGS_FILE.read_text())["ui"]["sidebar"] is False
        async with hermetic_app().run_test(size=(WIDE, 30)) as pilot:
            await pilot.pause(0.2)
            assert _is_hidden(pilot.app)

    asyncio.run(run())


def test_sidebar_setting_is_tri_state():
    from arkad.storage.settings import DEFAULTS, _coerce

    assert DEFAULTS["ui"]["sidebar"] is None  # None = auto by width
    for raw, want in ((True, True), (False, False), (None, None),
                      ("true", True), ("yes", True), ("open", True),
                      ("false", False), ("off", False), ("closed", False),
                      ("auto", None), ("default", None), ("null", None), ("", None)):
        assert _coerce("ui.sidebar", raw) is want, raw
    for bad in ("maybe", 1, 0, 2):
        with pytest.raises(ValueError):
            _coerce("ui.sidebar", bad)


def test_settings_modal_lists_the_pin():
    """The pin must be reachable from /settings, not a hidden knob."""
    from arkad.tui.settings_modal import _DESCRIPTIONS

    assert "ui.sidebar" in _DESCRIPTIONS
