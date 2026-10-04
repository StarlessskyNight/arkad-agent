"""Shared test isolation."""
import atexit
import os
import shutil
import tempfile

import pytest

# Tests must never touch the developer's real Arkad config. A plain `pytest`
# (or `!pytest` inside Arkad) used to rewrite ~/.config/arkad-agent —
# settings.json, provider, auth_mode, history.json, sessions.db — so the saved
# provider/model flipped to whatever the last test set. Paths are computed when
# arkad is imported, so HOME is pointed at a throwaway directory here, before
# any test module imports it. The real home stays readable via ARKAD_REAL_HOME
# (tests that only *read* local data). Opt out: ARKAD_TESTS_REAL_HOME=1.
if os.environ.get("ARKAD_TESTS_REAL_HOME") != "1" and "ARKAD_REAL_HOME" not in os.environ:
    os.environ["ARKAD_REAL_HOME"] = os.path.expanduser("~")
    _test_home = tempfile.mkdtemp(prefix="arkad-test-home-")
    os.environ["HOME"] = _test_home
    atexit.register(shutil.rmtree, _test_home, True)



@pytest.fixture(autouse=True)
def _isolated_models_dev(tmp_path, monkeypatch):
    """The models.dev catalog (``arkad/auth/models_dev.py``) adds a provider
    for every key in the environment. Without this, a developer's real cache
    plus an OPENAI_API_KEY in their shell would change what every picker test
    sees. Each test starts with an empty catalog, its own keys file and no
    network; tests that need a catalog seed one with ``models_dev.store``."""
    from arkad.auth import models_dev
    from arkad.constants import paths

    monkeypatch.setattr(models_dev, "CACHE_FILE", tmp_path / "models_dev.json")
    monkeypatch.setattr(paths, "PROVIDER_KEYS_FILE", tmp_path / "provider_keys.json")

    def _offline(*_a, **_k):
        raise OSError("network disabled in tests (models.dev)")

    monkeypatch.setattr(models_dev, "_http_get", _offline)
    # OpenCode Go / Zen "served now" lists (auth/opencode_catalog.py): offline
    # too, and empty unless a test seeds them.
    from arkad.auth import opencode_catalog

    monkeypatch.setattr(opencode_catalog, "_fetch", lambda *_a, **_k: None)
    monkeypatch.setattr(opencode_catalog, "served_ids", lambda provider: set())
    models_dev._memo.update(mtime=None, path=None, providers={}, native={}, meta={})
    models_dev._memo.pop("shared", None)
    yield
    models_dev._memo.update(mtime=None, path=None, providers={}, native={}, meta={})
    models_dev._memo.pop("shared", None)


@pytest.fixture(autouse=True)
def _no_macos_permission_prompts(monkeypatch):
    """Never let a test pop the macOS Screen Recording prompt or open System
    Settings on the developer's machine."""
    import importlib

    shot = importlib.import_module("arkad.tools.screenshot")
    monkeypatch.setattr(shot, "request_screen_recording", lambda: None)
    monkeypatch.setattr(shot, "_permission_requested", False)


@pytest.fixture()
def ext_env(tmp_path, monkeypatch):
    """Skills / MCP installs against a scratch HOME + project folder.

    Nothing reaches the real ``~/.config/arkad-agent``, ``~/.arkad``,
    ``~/.claude`` … or the current project, and no config is saved to settings.
    """
    import pathlib
    import types

    import arkad.mcp.auth as mcp_auth
    import arkad.mcp.config as mcp_config
    import arkad.mcp.secrets as mcp_secrets
    import arkad.storage.skill_install as skill_install
    import arkad.storage.skills as skills
    from arkad import state

    home = tmp_path / "home"
    proj = tmp_path / "proj"
    home.mkdir()
    proj.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(mcp_config, "MCP_GLOBAL_CONFIG_FILE", home / ".config" / "arkad-agent" / "mcp.json")
    monkeypatch.setattr(
        mcp_config, "_global_sources",
        lambda: [("arkad", mcp_config.MCP_GLOBAL_CONFIG_FILE, "")],
    )
    monkeypatch.setattr(mcp_secrets, "SECRETS_FILE", home / ".config" / "arkad-agent" / "mcp_secrets.json")
    monkeypatch.setattr(mcp_auth, "AUTH_DIR", home / ".config" / "arkad-agent" / "mcp-auth")
    monkeypatch.setattr(skill_install, "ARKAD_SKILLS_DIR", home / ".arkad" / "skills")
    monkeypatch.setattr(skills, "ARKAD_SKILLS_DIR", home / ".arkad" / "skills")
    monkeypatch.setattr(skills, "CONFIG_DIR", home / ".config" / "arkad-agent")
    monkeypatch.chdir(proj)
    monkeypatch.setattr(state, "global_mcp", False)
    monkeypatch.setattr(state, "global_skills", False)
    monkeypatch.setattr(state, "save_mcp_config", lambda: None)
    monkeypatch.setattr(state, "save_skills_config", lambda: None)
    monkeypatch.setattr(mcp_config, "_config", None)
    skills.invalidate_cache()
    yield types.SimpleNamespace(home=home, proj=proj)
    monkeypatch.setattr(mcp_config, "_config", None)
    skills.invalidate_cache()
