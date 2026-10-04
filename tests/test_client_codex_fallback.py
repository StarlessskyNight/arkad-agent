"""Startup auth resolution when Codex OAuth is missing."""
from unittest.mock import MagicMock, patch

from arkad.auth.client import _resolve_provider, make_client
from arkad.constants.providers import PROVIDER_ANTHROPIC, PROVIDER_OPENAI_CODEX


def test_resolve_provider_ignores_stale_codex_pin(tmp_path, monkeypatch):
    provider_file = tmp_path / "provider"
    provider_file.write_text(PROVIDER_OPENAI_CODEX)
    monkeypatch.setattr("arkad.constants.paths.PROVIDER_FILE", provider_file)
    monkeypatch.setattr("arkad.auth.client.load_codex_oauth_tokens", lambda: None)
    monkeypatch.setattr("arkad.auth.client.load_oauth_tokens", lambda: {"access_token": "a", "refresh_token": "r"})
    monkeypatch.setattr("arkad.auth.client.KEY_FILE", tmp_path / "missing-key")
    # Clear saved preferences so _resolve_provider falls through to the provider file
    monkeypatch.setattr("arkad.storage.prefs.load_saved_preferences", lambda: ("", ""))
    monkeypatch.setattr("arkad.storage.prefs.load_saved_provider", lambda: "")
    assert _resolve_provider(interactive=True) == PROVIDER_ANTHROPIC


def test_make_client_first_run_uses_arkad_agent(tmp_path, monkeypatch, tmp_path_factory):
    """Stale auth marker files without tokens should still boot Arkad Agent."""
    settings_dir = tmp_path / "cfg"
    settings_dir.mkdir()
    settings_file = settings_dir / "settings.json"
    settings_file.write_text("{}\n")
    monkeypatch.setattr("arkad.storage.settings.SETTINGS_FILE", settings_file)
    monkeypatch.setattr("arkad.storage.settings.CONFIG_DIR", settings_dir)
    monkeypatch.setattr("arkad.storage.settings._singleton", None)
    monkeypatch.setattr("arkad.auth.client.AUTH_MODE_FILE", tmp_path / "auth_mode")
    monkeypatch.setattr("arkad.auth.client.PROVIDER_FILE", tmp_path / "provider")
    monkeypatch.setattr("arkad.auth.client.KEY_FILE", tmp_path / "missing-key")
    (tmp_path / "auth_mode").write_text("oauth")
    monkeypatch.setattr("arkad.auth.client.load_oauth_tokens", lambda: None)
    monkeypatch.setattr("arkad.auth.client.load_codex_oauth_tokens", lambda: None)
    monkeypatch.setattr("arkad.auth.client._has_usable_provider_credentials", lambda: False)
    monkeypatch.setattr("arkad.auth.client._resolve_provider", lambda **kwargs: "opencode_zen")
    monkeypatch.setattr("arkad.storage.prefs.load_saved_model", lambda: "")
    monkeypatch.setattr("arkad.storage.prefs.should_use_first_run_arkad_defaults", lambda: True)
    monkeypatch.setattr("arkad.auth.client._build_opencode_zen_client_for_model", lambda *a, **k: MagicMock())
    monkeypatch.setattr("arkad.auth.arkad_agent.build_arkad_agent_client", lambda: MagicMock())
    from arkad import state
    from arkad.constants.providers import ARKAD_AGENT_FALLBACK_MODEL, PROVIDER_OPENCODE_ZEN
    state.MODEL = ARKAD_AGENT_FALLBACK_MODEL
    client = make_client(interactive=False)
    assert client is not None
    assert state.provider == PROVIDER_OPENCODE_ZEN
    assert state.MODEL == ARKAD_AGENT_FALLBACK_MODEL
    assert state.arkad_agent_free is True


def test_make_client_falls_back_when_codex_oauth_missing(tmp_path, monkeypatch):
    provider_file = tmp_path / "provider"
    provider_file.write_text(PROVIDER_OPENAI_CODEX)
    monkeypatch.setattr("arkad.auth.client.PROVIDER_FILE", provider_file)
    monkeypatch.setattr("arkad.constants.paths.PROVIDER_FILE", provider_file)
    monkeypatch.setattr("arkad.auth.client._build_codex_client", lambda: None)
    monkeypatch.setattr(
        "arkad.auth.client._pick_fallback_provider",
        lambda **kwargs: PROVIDER_ANTHROPIC,
    )

    fake_client = MagicMock()
    monkeypatch.setattr("arkad.storage.prefs.load_saved_model", lambda: "claude-sonnet-4-6")
    monkeypatch.setattr("arkad.storage.prefs.should_use_first_run_arkad_defaults", lambda: False)
    # Prevent _resolve_provider from returning the user's real saved provider
    monkeypatch.setattr("arkad.storage.prefs.load_saved_preferences", lambda: ("", ""))
    monkeypatch.setattr("arkad.storage.prefs.load_saved_provider", lambda: "")
    with patch("arkad.auth.client._build_client_from_mode", return_value=fake_client):
        with patch("arkad.auth.client.sync_anthropic_model_ids"):
            monkeypatch.setattr("arkad.auth.client.load_oauth_tokens", lambda: {"access_token": "a", "refresh_token": "r"})
            monkeypatch.setattr("arkad.auth.client.AUTH_MODE_FILE", tmp_path / "auth_mode")
            monkeypatch.setattr("arkad.auth.client.KEY_FILE", tmp_path / "key")
            client = make_client(interactive=True)
    assert client is fake_client


def test_removed_provider_lands_on_a_free_model(tmp_path, monkeypatch):
    """A saved Kimchi choice (provider removed) starts on the free tier with a
    model it serves — never the old Kimchi model, which would fail every turn."""
    from arkad import state
    from arkad.constants.providers import ARKAD_AGENT_FALLBACK_MODEL, PROVIDER_OPENCODE_ZEN

    provider_file = tmp_path / "provider"
    provider_file.write_text("kimchi")
    monkeypatch.setattr("arkad.auth.client.PROVIDER_FILE", provider_file)
    monkeypatch.setattr("arkad.auth.client.AUTH_MODE_FILE", tmp_path / "auth_mode")
    monkeypatch.setattr("arkad.auth.client.KEY_FILE", tmp_path / "missing-key")
    monkeypatch.setattr("arkad.auth.client.load_oauth_tokens", lambda: None)
    monkeypatch.setattr("arkad.auth.client.load_codex_oauth_tokens", lambda: None)
    monkeypatch.setattr("arkad.auth.client._has_usable_provider_credentials", lambda: False)
    monkeypatch.setattr("arkad.storage.prefs.should_use_first_run_arkad_defaults", lambda: False)
    monkeypatch.setattr("arkad.storage.prefs.load_saved_model", lambda: "kimi-k2.6")
    monkeypatch.setattr("arkad.storage.prefs.load_saved_preferences", lambda: ("kimi-k2.6", "kimchi"))
    monkeypatch.setattr("arkad.storage.prefs.load_saved_provider", lambda: "kimchi")
    monkeypatch.setattr("arkad.auth.client._build_opencode_zen_client_for_model", lambda *a, **k: MagicMock())
    client = make_client(interactive=False)
    assert client is not None
    assert state.provider == PROVIDER_OPENCODE_ZEN and state.arkad_agent_free is True
    assert state.MODEL == ARKAD_AGENT_FALLBACK_MODEL
