"""Project-MCP trust gate: a repo's .mcp.json must not run code at startup
without the user's approval (see arkad/mcp/trust.py)."""
import os
import stat

import pytest

import arkad.mcp.trust as trust


class _FakeConfig:
    """Config with one project-scope and one global-scope server."""

    def __init__(self, root, project_entry=None, global_entry=None):
        self._root = str(root)
        self._servers = {}
        if project_entry is not None:
            self._servers["proj"] = project_entry
        if global_entry is not None:
            self._servers["glob"] = global_entry

    def get_auto_connect(self):
        return list(self._servers)

    def get_server(self, name):
        return self._servers.get(name)

    def list_servers(self):
        return dict(self._servers)

    def get_scope(self, name):
        return "project" if name == "proj" else "global"

    def project_config_path(self):
        from pathlib import Path
        return Path(self._root) / ".mcp.json"


@pytest.fixture()
def trust_store(tmp_path, monkeypatch):
    """Isolate the trust store in a throwaway file."""
    store = tmp_path / "mcp_trust.json"
    monkeypatch.setattr(trust, "TRUST_FILE", store)
    return store


@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _stdio_entry(cmd="npx", args=("-y", "some-server")):
    return {"type": "stdio", "command": cmd, "args": list(args)}


class TestTrustStore:
    def test_grant_then_is_trusted(self, trust_store, project):
        entry = _stdio_entry()
        assert not trust.is_trusted(project, "proj", entry)
        trust.grant(project, "proj", entry)
        assert trust.is_trusted(project, "proj", entry)

    def test_grant_is_idempotent(self, trust_store, project):
        entry = _stdio_entry()
        trust.grant(project, "proj", entry)
        trust.grant(project, "proj", entry)
        data = trust_store.read_text()
        assert data.count('"proj"') == 1

    def test_command_change_invalidates_trust(self, trust_store, project):
        trust.grant(project, "proj", _stdio_entry("npx"))
        assert not trust.is_trusted(project, "proj", _stdio_entry("bash", ["-c", "evil"]))

    def test_args_change_invalidates_trust(self, trust_store, project):
        trust.grant(project, "proj", _stdio_entry("npx", ["-y", "a"]))
        assert not trust.is_trusted(project, "proj", _stdio_entry("npx", ["-y", "b"]))

    def test_different_project_is_independent(self, trust_store, project, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        entry = _stdio_entry()
        trust.grant(project, "proj", entry)
        assert not trust.is_trusted(other, "proj", entry)

    def test_store_file_is_0600(self, trust_store, project):
        trust.grant(project, "proj", _stdio_entry())
        mode = stat.S_IMODE(os.stat(trust_store).st_mode)
        assert mode == 0o600

    def test_corrupt_store_does_not_crash(self, trust_store, project):
        trust_store.write_text("{not json")
        assert not trust.is_trusted(project, "proj", _stdio_entry())


class TestRequiresTrust:
    def test_project_server_untrusted(self, trust_store, project):
        cfg = _FakeConfig(project, project_entry=_stdio_entry())
        assert trust.requires_trust(cfg, "proj", cfg.get_server("proj"))

    def test_project_server_trusted(self, trust_store, project):
        cfg = _FakeConfig(project, project_entry=_stdio_entry())
        trust.grant(project, "proj", cfg.get_server("proj"))
        assert not trust.requires_trust(cfg, "proj", cfg.get_server("proj"))

    def test_global_server_never_gated(self, trust_store, project):
        cfg = _FakeConfig(project, global_entry=_stdio_entry())
        assert not trust.requires_trust(cfg, "glob", cfg.get_server("glob"))

    def test_pending_trust_lists_only_untrusted(self, trust_store, project):
        cfg = _FakeConfig(project, project_entry=_stdio_entry(), global_entry=_stdio_entry())
        assert trust.pending_trust(cfg, cfg.list_servers()) == ["proj"]
        trust.grant(project, "proj", cfg.get_server("proj"))
        assert trust.pending_trust(cfg, cfg.list_servers()) == []


class TestAutoConnectGate:
    """auto_connect_servers must skip untrusted project servers and connect
    trusted ones; globals are never gated."""

    def _run_auto_connect(self, monkeypatch, cfg):
        from arkad.mcp import config as mcp_config
        from arkad.mcp import registry as reg

        monkeypatch.setattr(mcp_config, "get_config", lambda: cfg)
        monkeypatch.setattr(reg.mcp_registry, "_health", {})
        monkeypatch.setattr(reg.mcp_registry, "_connecting", set())
        connected: list[str] = []
        untrusted: list[str] = []

        def fake_connect(name, server_cfg):
            connected.append(name)
            return None

        monkeypatch.setattr(reg.mcp_registry, "connect", fake_connect)
        monkeypatch.setattr(reg.mcp_registry, "note_untrusted", untrusted.append)
        reg.auto_connect_servers()
        return connected, untrusted

    def test_untrusted_project_server_skipped(self, monkeypatch, trust_store, project):
        cfg = _FakeConfig(project, project_entry=_stdio_entry())
        connected, untrusted = self._run_auto_connect(monkeypatch, cfg)
        assert connected == []
        assert untrusted == ["proj"]

    def test_trusted_project_server_connects(self, monkeypatch, trust_store, project):
        cfg = _FakeConfig(project, project_entry=_stdio_entry())
        trust.grant(project, "proj", cfg.get_server("proj"))
        connected, untrusted = self._run_auto_connect(monkeypatch, cfg)
        assert connected == ["proj"]
        assert untrusted == []

    def test_global_server_connects_without_trust(self, monkeypatch, trust_store, project):
        cfg = _FakeConfig(project, global_entry=_stdio_entry())
        connected, untrusted = self._run_auto_connect(monkeypatch, cfg)
        assert connected == ["glob"]
        assert untrusted == []

    def test_mixed(self, monkeypatch, trust_store, project):
        cfg = _FakeConfig(project, project_entry=_stdio_entry(), global_entry=_stdio_entry())
        trust.grant(project, "proj", cfg.get_server("proj"))
        connected, untrusted = self._run_auto_connect(monkeypatch, cfg)
        assert connected == ["proj", "glob"]
        assert untrusted == []


class TestTeardownHook:
    def test_hook_registered_and_idempotent(self, monkeypatch):
        import atexit

        from arkad.mcp import registry as reg

        calls: list[int] = []
        monkeypatch.setattr(reg, "_atexit_installed", False)
        monkeypatch.setattr(atexit, "register", lambda fn: calls.append(fn))
        reg._install_atexit_teardown()
        reg._install_atexit_teardown()
        assert len(calls) == 1

    def test_teardown_disconnects_and_stops_loop(self, monkeypatch):
        from arkad.mcp import registry as reg

        done: list[str] = []
        monkeypatch.setattr(reg.mcp_registry, "disconnect_all",
                            lambda: done.append("disconnect"))
        loop = type("Loop", (), {"stop": lambda self: done.append("stop")})()
        monkeypatch.setattr(reg, "_loop", loop)
        reg._teardown_at_exit()
        assert done == ["disconnect", "stop"]
        assert reg._loop is None

    def test_teardown_survives_disconnect_failure(self, monkeypatch):
        from arkad.mcp import registry as reg

        def boom():
            raise RuntimeError("disconnect exploded")

        monkeypatch.setattr(reg.mcp_registry, "disconnect_all", boom)
        monkeypatch.setattr(reg, "_loop", None)
        reg._teardown_at_exit()  # must not raise
