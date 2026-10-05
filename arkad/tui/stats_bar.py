"""Persistent top header bar with live system stats (RAM/CPU/UPTIME)."""
from __future__ import annotations

import time

from rich.text import Text
from textual.widgets import Static

from . import theme as ui
from .cyber_frame import _SysStats


class StatsBar(Static):
    DEFAULT_CSS = """
    StatsBar {
        height: 2;
        width: 100%;
        dock: top;
        border-bottom: solid $jv-border;
        padding: 0 1;
        color: $jv-fg-mute;
    }
    """

    def on_mount(self) -> None:
        self._stats = _SysStats()
        self._t0 = time.monotonic()
        self.set_interval(1.0, self._tick)
        self._tick()

    def _tick(self) -> None:
        s = self._stats.pump() or self._stats.fallback()
        used, total, cpu = (s.get(k, 0.0) for k in ("ram_used_gb", "ram_total_gb", "cpu_pct"))
        up = int(s.get("uptime_secs", time.monotonic() - self._t0))
        ram_fill = max(0, min(8, int(used / total * 8))) if total else 0
        cpu_fill = max(0, min(4, int(cpu / 25)))

        right = Text()
        right.append("▒" * ram_fill + "░" * (8 - ram_fill), style=ui.ACCENT_2)
        right.append(" RAM ", style=ui.FG_DIM)
        right.append(f"{used:.0f}G/{total:.0f}G", style=ui.ACCENT_2)
        right.append("   |   ", style=ui.FG_DIM)
        right.append("▇" * cpu_fill + "░" * (4 - cpu_fill), style=ui.ACCENT_2)
        right.append(" CPU ", style=ui.FG_DIM)
        right.append(f"{cpu:.0f}%", style=ui.ACCENT_2)
        right.append("   |   ", style=ui.FG_DIM)
        right.append("UPTIME ", style=ui.FG_DIM)
        right.append(f"{up // 3600}:{(up % 3600) // 60:02d}:{up % 60:02d}", style=ui.ACCENT_2)

        line = Text()
        line.append(" arkad", style=f"bold {ui.ACCENT}")
        pad = max(2, (self.size.width or 80) - 8 - len(str(right)))
        line.append(" " * pad)
        line.append_text(right)
        self.update(line)
