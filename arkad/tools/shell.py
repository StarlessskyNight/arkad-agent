"""Shell execution tool with approval prompt."""
import os
import re
import shlex
import signal
import subprocess
import threading
import time

from rich.markup import escape

from ..console import console
from ..constants import CWD, MAX_TOOL_OUTPUT, DEFAULT_BASH_TIMEOUT
from .. import file_changes, state

_bash_lock = threading.Lock()

# How often a running command checks whether its turn was stopped (Esc / web
# Stop / New chat). Short enough to feel instant, long enough to cost nothing.
_CANCEL_POLL = 0.2

CANCELLED_RESULT = "CANCELLED: the command was stopped because the turn was interrupted"

# Hard ceiling on a single shell command. The timeout is model-written; without
# a clamp a tool call could hold `_bash_lock` (and every other shell tool) for
# hours.
MAX_BASH_TIMEOUT = 600

# In-memory capture cap for a running command's output. The final result is
# trimmed to MAX_TOOL_OUTPUT chars anyway; this keeps a runaway producer
# (`yes`, an infinite log loop) from exhausting RAM while it runs.
MAX_CAPTURE_BYTES = 512 * 1024


class _Cancelled(Exception):
    """The turn running this command was cancelled; the command is stopped."""


def _descendants(root: int) -> list[int]:
    """Every process started (directly or not) by ``root``, via ``ps``."""
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=3,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    children: dict[int, list[int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    found: list[int] = []
    stack = [root]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found:
                found.append(child)
                stack.append(child)
    return found


def _kill_tree(proc: subprocess.Popen) -> None:
    """Stop ``proc`` and everything it started: TERM, a moment, then KILL.

    The shell (``sh -c …``) is rarely the process doing the work; killing only
    it would leave e.g. ``pytest`` running with the output pipes open.
    Children are collected first — once the shell dies they're reparented
    and can't be found from it any more.
    """
    pids = _descendants(proc.pid) if os.name == "posix" else []
    for sig in (signal.SIGTERM, getattr(signal, "SIGKILL", signal.SIGTERM)):
        for pid in pids:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        try:
            proc.send_signal(sig)
        except OSError:
            pass
        try:
            proc.wait(timeout=1.0)
            if sig == signal.SIGTERM and not any(_pid_alive(p) for p in pids):
                return
        except subprocess.TimeoutExpired:
            pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class _BoundedBuffer:
    """Capture output with a hard memory ceiling: keeps a head plus a rolling
    tail and counts dropped bytes, so memory stays bounded no matter how much
    the command emits."""

    def __init__(self, cap: int = MAX_CAPTURE_BYTES):
        self._cap = max(2, cap)
        self._head: list[bytes] = []
        self._head_len = 0
        self._tail: list[bytes] = []
        self._tail_len = 0
        self._dropped = 0
        self._lock = threading.Lock()

    def feed(self, data: bytes) -> None:
        with self._lock:
            half = self._cap // 2
            if self._head_len < half:
                keep = data[: half - self._head_len]
                self._head.append(keep)
                self._head_len += len(keep)
                data = data[len(keep):]
            if not data:
                return
            self._tail.append(data)
            self._tail_len += len(data)
            while self._tail_len > half and self._tail:
                excess = self._tail_len - half
                first = self._tail[0]
                if len(first) <= excess:
                    self._tail.pop(0)
                    self._tail_len -= len(first)
                    self._dropped += len(first)
                else:
                    self._tail[0] = first[excess:]
                    self._tail_len -= excess
                    self._dropped += excess

    def get(self) -> str:
        with self._lock:
            head, tail, dropped = b"".join(self._head), b"".join(self._tail), self._dropped

        def decode(b: bytes) -> str:
            # errors="replace": one invalid byte must not kill the command
            # (text-mode Popen used to crash with UnicodeDecodeError).
            return b.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")

        text = decode(head)
        if dropped:
            text += f"\n[… {dropped} bytes of output truncated …]\n"
        return text + decode(tail)


def _pump(stream, buf: _BoundedBuffer) -> None:
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            buf.feed(chunk)
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _run_process(cmd: str, timeout: int, env: dict) -> tuple[int, str, str]:
    """Run ``cmd`` like ``subprocess.run(shell=True, capture_output=True)``,
    but stop it as soon as the turn is cancelled.

    Raises ``subprocess.TimeoutExpired`` on timeout and ``_Cancelled`` on a
    cancelled turn — in both cases after the whole process tree is gone, so
    the shell lock is never held by a command nobody is waiting for.
    """
    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(CWD),
        env=env,
    )
    out_buf, err_buf = _BoundedBuffer(), _BoundedBuffer()
    pumps = [
        threading.Thread(target=_pump, args=(proc.stdout, out_buf), daemon=True),
        threading.Thread(target=_pump, args=(proc.stderr, err_buf), daemon=True),
    ]
    for t in pumps:
        t.start()
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                code = proc.wait(timeout=_CANCEL_POLL)
                for t in pumps:
                    t.join(timeout=2)
                return code, out_buf.get(), err_buf.get()
            except subprocess.TimeoutExpired:
                pass
            if state.turn_cancelled():
                _kill_tree(proc)
                raise _Cancelled()
            if time.monotonic() >= deadline:
                _kill_tree(proc)
                raise subprocess.TimeoutExpired(cmd, timeout)
    except BaseException:
        # KeyboardInterrupt injected by Esc, or anything else: never leave the
        # command running behind us.
        if proc.poll() is None:
            _kill_tree(proc)
        raise

# Read-only agent tools (search_code, git_status, …) must not block on approval.
_SAFE_READONLY = re.compile(
    r"^(?:"
    r"rg\b|grep\b|"
    r"git(?:\s+--no-pager)?\s+(?:status|log|diff|show|rev-parse|branch|remote)\b|"
    r"which\b|file\b|wc\b|head\b|tail\b|cat\b|pwd\b|echo\b|test\b|\["
    r")",
    re.IGNORECASE,
)


# A token made entirely of shell punctuation: `;`, `&&`, `|`, `>`, `>(`, …
_OPERATOR_TOKEN = re.compile(r"^[;|&<>()]+$")


def _has_shell_operators(cmd: str) -> bool:
    """True when ``cmd`` chains, pipes, redirects or substitutes — i.e. a
    prefix-allowlisted first command says nothing about the rest of it.
    Quoted operators stay inside one shlex token and are not flagged."""
    if "\n" in cmd or "\r" in cmd or "`" in cmd or "$(" in cmd:
        return True
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        # Unbalanced quotes: not provably a single command — ask the user.
        return True
    return any(_OPERATOR_TOKEN.match(tok) for tok in tokens)


def _is_safe_readonly_command(cmd: str) -> bool:
    cmd = (cmd or "").strip()
    if not cmd or _has_shell_operators(cmd):
        return False
    return bool(_SAFE_READONLY.match(cmd))


_DANGEROUS = ["rm -rf /", "mkfs", ":(){:|:&};:", "dd if=/dev/zero"]


def _rm_deletes_root_or_home(cmd: str) -> bool:
    """``rm -rf /…`` / ``rm -fr ~…``: recursive+force on an absolute or home
    path. ``rm -rf build`` stays allowed. (The legacy ``rm -rf /`` substring
    already refused any absolute target — this keeps that and adds ``~``.)"""
    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError:
        return "rm -rf /" in cmd
    for i, tok in enumerate(tokens):
        if tok != "rm":
            continue
        recursive_force = False
        j = i + 1
        while j < len(tokens) and tokens[j].startswith("-") and tokens[j] != "--":
            flags = tokens[j].lstrip("-")
            if ("r" in flags or "R" in flags) and "f" in flags:
                recursive_force = True
            j += 1
        if j < len(tokens) and tokens[j] == "--":
            j += 1
        if recursive_force and j < len(tokens):
            target = tokens[j]
            if target.startswith(("/", "~")) or target == "..":
                return True
    return False


def _find_is_destructive(cmd: str) -> bool:
    """``find / -delete``, ``find . -exec rm`` (unfiltered): refuse outright.
    A filtered local delete (``find . -name '*.pyc' -exec rm {} ;``) is a
    normal dev command and stays allowed."""
    for seg in re.split(r";|&&|\|\||\|", cmd):
        seg = seg.strip()
        if not re.match(r"\bfind\b", seg):
            continue
        if "-delete" not in seg and not re.search(r"-exec\s+rm\b", seg):
            continue
        try:
            tokens = shlex.split(seg, posix=True)
        except ValueError:
            return True
        start = tokens[1] if len(tokens) > 1 and not tokens[1].startswith("-") else "."
        filtered = bool(re.search(r"-(?:name|path|regex|iname|ipath|iregex)\b", seg))
        if start.startswith(("/", "~")) or (start in (".", "..", "./", "../") and not filtered):
            return True
    return False


def is_dangerous(cmd: str) -> bool:
    return (
        any(d in cmd for d in _DANGEROUS)
        or _rm_deletes_root_or_home(cmd)
        or _find_is_destructive(cmd)
    )


def ask_approval(cmd: str) -> str | None:
    """Ask the user before running ``cmd`` (unless auto-approved / read-only).

    Returns ``"USER DENIED"`` when refused, else None. Call with
    ``_bash_lock`` held so approval prompts never overlap.
    """
    if state.auto_approve or _is_safe_readonly_command(cmd):
        return None
    # The command is model-written text: a `[x for x in y]` in it must print as
    # text, not be read as a Rich style tag (the TUI crashes on an unknown one).
    console.print(f"[yellow]→ run:[/] [cyan]{escape(cmd)}[/]")
    try:
        approve = getattr(console, "prompt_shell_approval", None)
        if approve is not None:
            ok = approve(cmd).strip().lower()
        else:
            ok = console.input(
                "[dim]approve? [Y/n/a=always] [/]"
            ).strip().lower()
    except (RuntimeError, EOFError):
        ok = ""
    if ok == "a":
        state.auto_approve = True
    elif ok == "n" or ok == "":
        return "USER DENIED"
    if state.turn_cancelled():
        raise KeyboardInterrupt()
    return None


def _clamp_timeout(timeout) -> int:
    """Bound a model-written timeout to [1, MAX_BASH_TIMEOUT]; garbage falls
    back to the default."""
    try:
        t = int(timeout)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_BASH_TIMEOUT
    return max(1, min(MAX_BASH_TIMEOUT, t))


def run_bash(cmd: str, timeout: int = DEFAULT_BASH_TIMEOUT) -> str:
    timeout = _clamp_timeout(timeout)
    if is_dangerous(cmd):
        return "BLOCKED: dangerous command"

    with _bash_lock:
        denied = ask_approval(cmd)
        if denied:
            return denied
        try:
            env = os.environ.copy()
            env.setdefault("GIT_PAGER", "cat")
            env.setdefault("PAGER", "cat")
            # Files the command deletes / renames / edits in place show up in
            # the web Changes panel (nothing is recorded if nothing changed).
            settle_changes = file_changes.watch_shell(cmd)
            try:
                code, stdout, stderr = _run_process(cmd, timeout, env)
            finally:
                settle_changes()
            out = (stdout or "") + (f"\n[stderr]\n{stderr}" if stderr else "")
            return f"$ {cmd}\nexit={code}\n{out[-MAX_TOOL_OUTPUT:]}"
        except subprocess.TimeoutExpired:
            return f"TIMEOUT after {timeout}s"
        except _Cancelled:
            return CANCELLED_RESULT
