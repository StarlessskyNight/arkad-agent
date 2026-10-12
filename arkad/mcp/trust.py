"""Trust for project-scope MCP servers — a repo's ``.mcp.json`` must not run
code the moment you open the folder.

The project file ships with the repo, so whoever wrote the repo chooses the
commands. Auto-connect would run them at startup, before the user has seen
anything. Claude Code asks "do you trust these servers?" — Arkad records the
answer here:

* ``~/.config/arkad-agent/mcp_trust.json`` (mode 600), keyed by
  ``project root → server name → fingerprint``.
* The fingerprint is a SHA-256 of what the server *does*: its command + args
  (stdio) or its URL (remote). Editing the entry in ``.mcp.json`` therefore
  re-requires trust; secret *values* don't count (they live in
  ``mcp/secrets.py``, the config only names the variable).
* An untrusted project server is skipped at startup
  (``registry.auto_connect_servers``) and surfaced as *pending trust*.
  Connecting it asks the user (``tools/extensions.mcp_connect``), and the
  approval is remembered here. Connecting it any other way (a ``/mcp connect``
  or a UI button — explicit user consent) also records trust
  (``registry.MCPRegistry._grant_project_trust``).

Global-scope servers (the user's own config files) are never gated.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import threading
import time
from typing import Any

from ..constants import paths

TRUST_FILE = paths.CONFIG_DIR / "mcp_trust.json"

_lock = threading.Lock()


def fingerprint(entry: dict[str, Any]) -> str:
    """What trust is pinned to: the command a stdio server runs (args included —
    they change what runs) or the URL a remote one answers on."""
    if entry.get("url"):
        canonical = "remote\n" + str(entry["url"])
    else:
        canonical = (
            "stdio\n" + str(entry.get("command") or "")
            + "\n" + json.dumps([str(a) for a in (entry.get("args") or [])], ensure_ascii=False)
        )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read() -> dict[str, Any]:
    try:
        raw = json.loads(TRUST_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write(data: dict[str, Any]) -> None:
    TRUST_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TRUST_FILE.with_name(TRUST_FILE.name + ".tmp")
    # Created 600 from the start — never world-readable, not even briefly.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, TRUST_FILE)


def is_project(config: Any, name: str) -> bool:
    """True when ``name`` comes from a project ``.mcp.json`` (never a global)."""
    get_scope = getattr(config, "get_scope", None)
    if callable(get_scope):
        try:
            return get_scope(name) == "project"
        except Exception:
            return False
    return name in getattr(config, "_project_servers", {})


def project_root(config: Any) -> pathlib.Path:
    """Canonical root trust is keyed by — the folder holding ``.mcp.json``."""
    getter = getattr(config, "project_config_path", None)
    path = None
    if callable(getter):
        try:
            path = getter()
        except Exception:
            path = None
    if not path:
        path = pathlib.Path.cwd() / ".mcp.json"
    return pathlib.Path(path).parent.resolve()


def _entry_trusted(store: dict[str, Any], root: pathlib.Path, name: str, entry: dict[str, Any]) -> bool:
    rec = (store.get("projects") or {}).get(str(root), {}).get(name)
    return isinstance(rec, dict) and rec.get("fingerprint") == fingerprint(entry or {})


def is_trusted(root: pathlib.Path, name: str, entry: dict[str, Any]) -> bool:
    """Has the user ok'd this exact server entry for this project before?"""
    with _lock:
        return _entry_trusted(_read(), root, name, entry)


def grant(root: pathlib.Path, name: str, entry: dict[str, Any]) -> None:
    """Remember the user's approval (idempotent — same fingerprint is a no-op)."""
    with _lock:
        data = _read()
        if _entry_trusted(data, root, name, entry):
            return
        data.setdefault("projects", {}).setdefault(str(root), {})[name] = {
            "fingerprint": fingerprint(entry or {}),
            "trusted_at": time.time(),
        }
        data["version"] = 1
        _write(data)


def requires_trust(config: Any, name: str, entry: dict[str, Any] | None) -> bool:
    """Project-scope server the user hasn't ok'd yet (globals are never gated)."""
    if not is_project(config, name):
        return False
    with _lock:
        return not _entry_trusted(_read(), project_root(config), name, entry or {})


def pending_trust(config: Any, entries: dict[str, dict[str, Any]]) -> list[str]:
    """Project-scope, not-yet-trusted names out of ``entries`` (one store read)."""
    candidates = [(n, e) for n, e in entries.items() if is_project(config, n)]
    if not candidates:
        return []
    with _lock:
        store = _read()
        root = project_root(config)
        return [n for n, e in candidates if not _entry_trusted(store, root, n, e or {})]
