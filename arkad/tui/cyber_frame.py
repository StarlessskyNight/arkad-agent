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
    Horizontal#cyber_prompt {
        height: 3;
        border: round $jv-accent;
        padding: 0 1;
    }
    Static#cyber_prefix {
        width: auto;
        color: $jv-accent;
        padding: 1 0 0 0;
    }
    Input#cyber_input {
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
        with Horizontal(id="cyber_mid"):
            yield Tree("ROOT_DIR", id="cyber_tree")
            yield Static("", id="cyber_info")

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
        self.call_after_refresh(self._grab_focus)

    def _grab_focus(self) -> None:
        try:
            self.app.query_one("#prompt").focus()
        except Exception:
            pass
        try:  # clean up any previously docked cyber prompt
            self.app.query_one("#cyber_prompt").remove()
        except Exception:
            pass

    def _dock_prompt(self) -> None:
        pass  # removed: the real composer (#prompt) is used instead

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

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if not data or data[0] != "file":
            return
        from .transcript import FilePreviewBlock, Transcript

        path = data[1]
        text = Text()
        text.append(f"📄 {path}\n\n", style=f"bold {ui.ACCENT}")
        try:
            low = path.lower()
            if low.endswith(".pdf"):
                import pypdf

                reader = pypdf.PdfReader(path)
                body = reader.pages[0].extract_text()[:2000] if reader.pages else "(empty pdf)"
                text.append(body, style=ui.FG_MUTE)
            elif low.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
                from PIL import Image

                im = Image.open(path).convert("L")
                text.append(f"image: {im.size[0]}x{im.size[1]}\n", style=ui.FG_MUTE)
                w = 48
                h = max(1, int(im.size[1] / im.size[0] * w * 0.5))
                im = im.resize((w, h))
                chars = " .:-=+*#%@"
                for y in range(h):
                    row = ""
                    for x in range(w):
                        row += chars[min(9, im.getpixel((x, y)) * 10 // 256)]
                    text.append(row + "\n", style=ui.ACCENT_2)
            else:
                from rich.syntax import Syntax

                src = "\n".join(Path(path).read_text(errors="replace").splitlines()[:80])
                block = FilePreviewBlock(
                    path,
                    Syntax(src, lexer=Path(path).suffix.lstrip(".") or "text", theme="monokai", line_numbers=True),
                )
                self.app.query_one("#transcript", Transcript).mount(block)
                return
        except Exception as exc:
            text.append(f"(cannot render: {exc})", style=ui.ERR)
        transcript = self.app.query_one("#transcript", Transcript)
        transcript.mount(FilePreviewBlock(path, text))

    def _tick(self) -> None:
        self._stats.pump()
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
