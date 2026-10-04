"""Keep the running arkad install in sync with its git checkout."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
from dataclasses import dataclass


MANAGED_INSTALL_DIR = pathlib.Path("~/.local/share/arkad-agent").expanduser()


def find_install_root() -> pathlib.Path | None:
    """Locate the arkad-agent git checkout backing this install."""
    candidates: list[pathlib.Path] = []

    # Editable install: arkad/*.py live directly under the repo.
    here = pathlib.Path(__file__).resolve().parent
    for parent in [here, *here.parents[:14]]:
        if (parent / ".git").is_dir() and (parent / "pyproject.toml").is_file():
            candidates.append(parent)

    # Standard install: `arkad` symlink → ~/.local/share/arkad-agent/.venv/bin/arkad
    try:
        arkad_bin = shutil.which("arkad")
        if arkad_bin:
            resolved = pathlib.Path(arkad_bin).resolve()
            for repo in (resolved.parent.parent, resolved.parent.parent.parent):
                if (repo / ".git").is_dir() and (repo / "pyproject.toml").is_file():
                    candidates.insert(0, repo)
    except Exception:
        pass

    seen: set[pathlib.Path] = set()
    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except Exception:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "arkad" / "cli.py").is_file():
            return candidate
    return None


def is_managed_install(repo_root: pathlib.Path) -> bool:
    """True for the standard installer checkout (safe to hard-reset on upgrade)."""
    try:
        return repo_root.resolve() == MANAGED_INSTALL_DIR.resolve()
    except Exception:
        return False


def _git_run(
    repo_root: pathlib.Path,
    args: list[str],
    *,
    timeout: int = 120,
) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"Timed out after {timeout}s"
    except FileNotFoundError as e:
        return -1, "", f"Command not found: {e}"
    except Exception as e:
        return -1, "", str(e)


def git_dirty_files(repo_root: pathlib.Path) -> list[str]:
    rc, out, _ = _git_run(repo_root, ["status", "--porcelain"], timeout=30)
    if rc != 0 or not out:
        return []
    return [line[3:] for line in out.splitlines() if len(line) > 3]


@dataclass(frozen=True)
class SyncResult:
    ok: bool
    error: str = ""
    branch: str = "main"
    discarded_local: tuple[str, ...] = ()
    method: str = ""  # "pull" | "reset"


def sync_repo_to_remote(
    repo_root: pathlib.Path,
    *,
    branch: str | None = None,
    fetch_timeout: int = 120,
    sync_timeout: int = 120,
) -> SyncResult:
    """Fetch and fast-forward *repo_root* to ``origin/<branch>``.

    Managed installs (``~/.local/share/arkad-agent``) always hard-reset to
    match the remote — local edits are never preserved. Dev clones abort when
    the working tree is dirty.
    """
    if not (repo_root / ".git").is_dir():
        return SyncResult(ok=False, error="not a git repository")

    rc, _, err = _git_run(repo_root, ["fetch", "origin"], timeout=fetch_timeout)
    if rc != 0:
        return SyncResult(ok=False, error=err or "git fetch failed")

    if branch is None:
        rc, out, _ = _git_run(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"], timeout=10)
        branch = out.strip() if rc == 0 and out else "main"

    remote_ref = f"origin/{branch}"
    dirty = git_dirty_files(repo_root)

    if is_managed_install(repo_root):
        rc, _, err = _git_run(
            repo_root,
            ["reset", "--hard", remote_ref],
            timeout=sync_timeout,
        )
        if rc != 0:
            return SyncResult(ok=False, branch=branch, error=err or "git reset failed")
        return SyncResult(
            ok=True,
            branch=branch,
            discarded_local=tuple(dirty),
            method="reset",
        )

    if dirty:
        preview = ", ".join(dirty[:4])
        if len(dirty) > 4:
            preview += f", … (+{len(dirty) - 4} more)"
        return SyncResult(
            ok=False,
            branch=branch,
            error=f"uncommitted local changes: {preview}",
        )

    rc, _, err = _git_run(
        repo_root,
        ["pull", "--ff-only", "origin", branch],
        timeout=sync_timeout,
    )
    if rc != 0:
        return SyncResult(ok=False, branch=branch, error=err or "git pull failed")
    return SyncResult(ok=True, branch=branch, method="pull")


def running_python() -> str:
    """Python interpreter actually executing arkad right now."""
    return sys.executable


def pip_install_repo(repo_root: pathlib.Path, *, timeout: int = 180) -> bool:
    """Editable install into the *running* venv so git pull = live code after restart."""
    try:
        r = subprocess.run(
            [running_python(), "-m", "pip", "install", "-e", "."],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode == 0
    except Exception:
        return False


def arkad_agent_models_available() -> bool:
    """True when this process can list free Arkad Agent models."""
    try:
        from .constants.providers import arkad_agent_models_for_picker
        return bool(arkad_agent_models_for_picker())
    except Exception:
        return False


def reexec_arkad(*, update_banner: dict | None = None) -> None:
    """Replace this process so Python reloads modules from disk."""
    if update_banner:
        import json
        os.environ["ARKAD_UPDATE_RESULT"] = json.dumps(update_banner)
    os.environ["ARKAD_UPDATED_REEXEC"] = "1"
    os.execv(sys.executable, [sys.executable, *sys.argv])
