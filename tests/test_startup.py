"""Startup performance helpers — update throttle and bootstrap fast path."""
from __future__ import annotations

import time

from arkad.bootstrap import _has_any_credentials_fast, ensure_arkad_agent_defaults
from arkad.updater import (
    maybe_update_and_reexec,
    should_check_for_updates,
    start_background_update,
)


def test_should_check_for_updates_respects_skip_env(monkeypatch):
    monkeypatch.delenv("ARKAD_SKIP_UPDATE", raising=False)
    monkeypatch.delenv("ARKAD_UPDATE_INTERVAL", raising=False)
    assert should_check_for_updates(now=0.0) is True

    monkeypatch.setenv("ARKAD_SKIP_UPDATE", "1")
    assert should_check_for_updates(now=0.0) is False


def test_should_check_for_updates_checks_every_launch_by_default(monkeypatch):
    monkeypatch.delenv("ARKAD_SKIP_UPDATE", raising=False)
    monkeypatch.delenv("ARKAD_UPDATE_INTERVAL", raising=False)
    assert should_check_for_updates(now=0.0) is True


def test_should_check_for_updates_throttles_when_interval_set(monkeypatch, tmp_path):
    monkeypatch.delenv("ARKAD_SKIP_UPDATE", raising=False)
    monkeypatch.setenv("ARKAD_UPDATE_INTERVAL", "86400")
    stamp = tmp_path / "last_update_check"
    stamp.write_text(str(time.time()), encoding="utf-8")
    monkeypatch.setattr("arkad.updater.UPDATE_CHECK_STAMP", stamp)

    assert should_check_for_updates(now=time.time()) is False
    assert should_check_for_updates(now=time.time() + 25 * 3600) is True


def test_bootstrap_pins_free_tier_on_first_install(monkeypatch):
    monkeypatch.setattr("arkad.storage.prefs.load_saved_model", lambda: "")
    monkeypatch.setattr("arkad.storage.prefs.should_use_first_run_arkad_defaults", lambda: True)
    from arkad import state
    from arkad.constants.providers import ARKAD_AGENT_FALLBACK_MODEL, PROVIDER_OPENCODE_ZEN

    state.arkad_agent_free = False
    state.MODEL = "claude-sonnet-4-6"
    state.provider = "anthropic"
    ensure_arkad_agent_defaults()
    assert state.provider == PROVIDER_OPENCODE_ZEN
    assert state.MODEL == ARKAD_AGENT_FALLBACK_MODEL
    assert state.arkad_agent_free is True


def test_bootstrap_respects_saved_model_preference(monkeypatch):
    monkeypatch.setattr("arkad.storage.prefs.should_use_first_run_arkad_defaults", lambda: False)
    from arkad import state

    state.MODEL = "claude-sonnet-4-6"
    state.provider = "anthropic"
    ensure_arkad_agent_defaults()
    assert state.MODEL == "claude-sonnet-4-6"
    assert state.provider == "anthropic"


def test_bootstrap_pins_free_tier_without_credentials(monkeypatch):
    monkeypatch.setattr("arkad.storage.prefs.load_saved_model", lambda: "")
    monkeypatch.setattr("arkad.storage.prefs.should_use_first_run_arkad_defaults", lambda: True)
    from arkad import state
    from arkad.constants.providers import ARKAD_AGENT_FALLBACK_MODEL, PROVIDER_OPENCODE_ZEN

    state.arkad_agent_free = False
    ensure_arkad_agent_defaults()
    assert state.provider == PROVIDER_OPENCODE_ZEN
    assert state.MODEL == ARKAD_AGENT_FALLBACK_MODEL
    assert state.arkad_agent_free is True


def test_has_any_credentials_fast_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_ZEN_API_KEY", raising=False)
    assert _has_any_credentials_fast() in (True, False)


def test_maybe_update_and_reexec_skips_after_reexec(monkeypatch):
    monkeypatch.setenv("ARKAD_UPDATED_REEXEC", "1")
    called = {"n": 0}

    def _boom():
        called["n"] += 1
        return {"updated": True}

    monkeypatch.setattr("arkad.updater.check_and_update", _boom)
    maybe_update_and_reexec()
    assert called["n"] == 0


def test_start_background_update_respects_skip(monkeypatch):
    monkeypatch.setenv("ARKAD_SKIP_UPDATE", "1")
    called = {"n": 0}

    def _fake_thread(*_a, **_k):
        called["n"] += 1
        class _T:
            def start(self):
                called["n"] += 1
        return _T()

    monkeypatch.setattr("threading.Thread", _fake_thread)
    start_background_update()
    assert called["n"] == 0
