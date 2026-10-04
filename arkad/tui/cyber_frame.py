"""Cybernode welcome frame: live system header, interactive project tree,
and a real prompt input wired into the app's normal submit pipeline."""
from __future__ import annotations

import getpass
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Input, Static, Tree

from . import theme as ui

_STATS_BIN = (
    Path(__file__).resolve().parents[2]
    / "rust" / "arkad-stats" / "target" / "release" / "arkad-stats"
)


class _SysStats:
    """Pump the Rust arkad-stats daemon; parse the newest JSON line."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.buf = ""
        self.last: dict[str, Any] | None = None

    def pump(self) -> dict[str, Any] | None:
        try:
            if self.proc is None and _STATS_BIN.is_file():
                self.proc = subprocess.Popen(
                    [str(_STATS_BIN)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                )
                os.set_blocking(self.proc.stdout.fileno(), False)
            if self.proc is None or self.proc.stdout is None:
                return None
            try:
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if chunk:
                    self.buf += chunk.decode(errors="replace")
            except BlockingIOError:
                pass
            if "\n" in self.buf:
                *lines, self.buf = self.buf.split("\n")
                for line in reversed(lines):
                    try:
                        parsed = json.loads(line)
                        if "ram_used_gb" in parsed and "cpu_pct" in parsed:
                            self.last = parsed
                            break
                    except ValueError:
                        continue
            return self.last
        except Exception:
            return None

    def fallback(self) -> dict[str, Any]:
        used = total = 0.0
        try:
            mem = {}
            for line in open("/proc/meminfo"):
                k, _, rest = line.partition(":")
                mem[k] = int(rest.strip().split()[0])
            total = mem["MemTotal"] / 1024 / 1024
            avail = mem.get("MemAvailable", 0) / 1024 / 1024
            used = total - avail
        except Exception:
            pass
        try:
            uptime = float(open("/proc/uptime").read().split()[0])
        except Exception:
            uptime = 0.0
        return {"ram_used_gb": used, "ram_total_gb": total, "cpu_pct": 0.0, "uptime_secs": uptime, "net_ok": True}


class CyberFrame(Widget):
    """Interactive boot frame mounted in place of WelcomeBlock."""

    DEFAULT_CSS = """
    CyberFrame {
        height: auto;
        margin: 1 0 0 0;
        padding: 0 2;
    }
    CyberFrame Static#cyber_header {
        color: $jv-fg-mute;
        dock: top;
        height: 1;
        margin: 0 0 1 0;
    }
    CyberFrame Horizontal#cyber_mid {
        height: 14;
        margin: 0 0 1 0;
    }
    CyberFrame Tree#cyber_tree {
        width: 34;
        height: 14;
        border: round $jv-border;
        padding: 0 1;
    }
    CyberFrame Static#cyber_info {
        width: 1fr;
        height: 14;
        border: round $jv-border;
        padding: 1 2;
        color: $jv-fg-mute;
    }
    CyberFrame Horizontal#cyber_prompt {
        height: 3;
        border: round $jv-accent;
        padding: 0 1;
    }
    CyberFrame Static#cyber_prefix {
        width: auto;
        color: $jv-accent;
        padding: 1 0 0 0;
    }
    CyberFrame Input#cyber_input {
        width: 1fr;
        border: none;
        background: transparent;
    }
    """

    can_focus_children = True

    def __init__(self, info: dict[str, Any]) -> None:
        super().__init__()
        self.info = info
        self._stats = _SysStats()
        self._t0 = time.monotonic()

    def compose(self) -> ComposeResult:
        yield Static("", id="cyber_header")
        with Horizontal(id="cyber_mid"):
            yield Tree("ROOT_DIR", id="cyber_tree")
            yield Static("", id="cyber_info")
        with Horizontal(id="cyber_prompt"):
            try:
                user = getpass.getuser()
                host = socket.gethostname().split(".")[0]
            except Exception:
                user, host = "harness", "cybernode"
            yield Static(f"{user}@{host}:~$ ", id="cyber_prefix")
            yield Input(placeholder="type a command, paste something, or ask…", id="cyber_input")

    def on_mount(self) -> None:
        tree = self.query_one("#cyber_tree", Tree)
        tree.show_root = True
        root = tree.root
        root.expand()
        try:
            names = sorted(
                (n for n in os.listdir(".") if not n.startswith(".")),
                key=lambda n: (not os.path.isdir(n), n.lower()),
            )[:24]
        except Exception:
            names = []
        for n in names:
            if os.path.isdir(n):
                node = root.add(f"{n}/", data=("dir", os.path.abspath(n)))
                node.allow_expand = True
            else:
                root.add_leaf(n, data=("file", n))
        self._tick()
        self.set_interval(1.0, self._tick)
        try:
            self.app.query_one("#composer", Horizontal).display = False  # type here, not there
        except Exception:
            pass
        self.call_after_refresh(lambda: self.query_one("#cyber_input", Input).focus())

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        if not node.data or node.data[0] != "dir" or node.children:
            return
        try:
            for n in sorted(os.listdir(node.data[1]), key=lambda x: (not os.path.isdir(os.path.join(node.data[1], x)), x.lower()))[:50]:
                if n.startswith("."):
                    continue
                full = os.path.join(node.data[1], n)
                if os.path.isdir(full):
                    child = node.add(f"{n}/", data=("dir", full))
                    child.allow_expand = True
                else:
                    node.add_leaf(n, data=("file", full))
        except Exception:
            pass

    def _tick(self) -> None:
        s = self._stats.pump() or self._stats.fallback()
        used, total, cpu = s.get("ram_used_gb", 0.0), s.get("ram_total_gb", 0.0), s.get("cpu_pct", 0.0)
        up = int(s.get("uptime_secs", time.monotonic() - self._t0))
        ram_fill = max(0, min(8, int(used / total * 8))) if total else 0
        cpu_fill = max(0, min(4, int(cpu / 25)))
        header = Text()
        header.append("▒" * ram_fill + "░" * (8 - ram_fill), style=ui.ACCENT)
        header.append(f" RAM {used:.0f}G/{total:.0f}G   ", style=ui.FG_MUTE)
        header.append("▇" * cpu_fill + "░" * (4 - cpu_fill), style=ui.ACCENT_2)
        header.append(f" CPU {cpu:.0f}%   ", style=ui.FG_MUTE)
        header.append(f"UPTIME {up // 3600}:{(up % 3600) // 60:02d}:{up % 60:02d}", style=ui.ACCENT_3)
        self.query_one("#cyber_header", Static).update(header)

        info = Text()
        info.append(f"v{self.info.get('version', '')}\n", style=ui.FG_DIM)
        info.append(f"{self.info.get('cwd', '')}\n\n", style=f"bold {ui.FG}")
        if self.info.get("branch"):
            info.append(f"⎇ {self.info['branch']}\n\n", style=ui.ACCENT_2)
        ctx = self.info.get("context") or []
        if ctx:
            info.append(" · ".join(ctx) + "\n\n", style=ui.FG_DIM)
        info.append("Click folders to expand. Type below:\n", style=ui.FG_DIM)
        info.append("  /cmd   — slash command\n", style=ui.FG_MUTE)
        info.append("  !cmd   — run in shell\n", style=ui.FG_MUTE)
        info.append("  paste  — examined by the model\n", style=ui.FG_MUTE)
        info.append("  other  — sent to the model\n", style=ui.FG_MUTE)
        self.query_one("#cyber_info", Static).update(info)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        if not text:
            return
        event.input.clear()
        app = self.app
        routed = self._route(text)
        from .prompt_area import PromptArea

        app.on_prompt_area_submitted(PromptArea.Submitted(routed))

    @staticmethod
    def _route(text: str) -> str:
        """Real slash-commands and !shell pass through; pasted/multi-line
        content is examined; everything else goes to the model."""
        if text.startswith("/") or text.startswith("!"):
            return text
        if "\n" in text or len(text) > 400:
            return f"Examine the following pasted content:\n\n{text}"
        return text
