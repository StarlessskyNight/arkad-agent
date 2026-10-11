"""Workspace: persistent directory tree (left) + file preview (right),
both independently scrollable, locked between the pinned header and the
input bar. Pure Textual layout — no external CSS/HTML."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import Static, Tree

from . import theme as ui


class Workspace(Widget):
    """Fixed middle band: tree pane | preview pane, independent scrolling."""

    DEFAULT_CSS = """
    Workspace {
        height: 45%;
    }
    Workspace Horizontal#ws_main {
        height: 100%;
    }
    Workspace Container#ws_tree_box {
        width: 34;
        height: 100%;
        border: solid $jv-border;
    }
    Workspace Tree#ws_tree {
        height: 100%;
    }
    Workspace Container#ws_preview_box {
        width: 1fr;
        height: 100%;
        border: solid $jv-border;
    }
    Workspace VerticalScroll#ws_preview_scroll {
        height: 100%;
    }
    """

    def __init__(self, info: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.info = info

    def compose(self) -> ComposeResult:
        with Horizontal(id="ws_main"):
            with Container(id="ws_tree_box"):
                yield Tree("ROOT_DIR", id="ws_tree")
            with Container(id="ws_preview_box"):
                yield VerticalScroll(
                    Static("", id="ws_preview"),
                    id="ws_preview_scroll",
                )

    def on_mount(self) -> None:
        tree = self.query_one("#ws_tree", Tree)
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
        # note: focus deliberately stays on the prompt — the tree is focusable
        # but not auto-focused, so the welcome block still mounts first.

    # ── tree interaction ────────────────────────────────────────────────

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        if not node.data or node.data[0] != "dir" or node.children:
            return
        try:
            base = node.data[1]
            for n in sorted(os.listdir(base), key=lambda x: (not os.path.isdir(os.path.join(base, x)), x.lower()))[:50]:
                if n.startswith("."):
                    continue
                full = os.path.join(base, n)
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
        self._preview(data[1])

    def _preview(self, path: str) -> None:
        static = self.query_one("#ws_preview", Static)
        scroll = self.query_one("#ws_preview_scroll", VerticalScroll)
        scroll.scroll_to(0, 0, animate=False)  # reset preview scroll on new file
        try:
            low = path.lower()
            if low.endswith(".pdf"):
                import pypdf

                reader = pypdf.PdfReader(path)
                body = reader.pages[0].extract_text()[:2000] if reader.pages else "(empty pdf)"
                static.update(f"📄 {path}\n\n{body}")
            elif low.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
                from PIL import Image

                im = Image.open(path).convert("L")
                w = 48
                h = max(1, int(im.size[1] / im.size[0] * w * 0.5))
                im = im.resize((w, h))
                chars = " .:-=+*#%@"
                rows = []
                for y in range(h):
                    rows.append("".join(chars[min(9, im.getpixel((x, y)) * 10 // 256)] for x in range(w)))
                static.update(f"🖼 {path}  {im.size[0]}x{im.size[1]}\n\n" + "\n".join(rows))
            else:
                src = "\n".join(Path(path).read_text(errors="replace").splitlines()[:80])
                static.update(
                    Syntax(src, lexer=Path(path).suffix.lstrip(".") or "text", theme="monokai", line_numbers=True)
                )
        except Exception as exc:
            static.update(f"(cannot render {path}: {exc})")
