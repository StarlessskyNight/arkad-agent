"""Persistent top header bar with live system stats (RAM/CPU/UPTIME)."""
from __future__ import annotations

import time

from rich.cells import cell_len
from rich.text import Text
from textual.widgets import Static

from ..constants import VERSION
from . import theme as ui

_LOGO = (  # 2-row block wordmark — same art as the welcome banner
    "▄▀█ █▀█ █ █ ▄▀█ █▀▄",
    "█▀█ █▀▄ █▀▄ █▀█ █▄▀",
)
_CREDIT = "StarlessskyNight"


class _SysStats:
    """Pure-Python /proc reader for live RAM/CPU/uptime."""

    def __init__(self) -> None:
        self._last_cpu = None

    def pump(self):
        try:
            mem = {}
            for line in open("/proc/meminfo"):
                k, _, rest = line.partition(":")
                mem[k] = int(rest.strip().split()[0])
            total = mem["MemTotal"] / 1024 / 1024
            avail = mem.get("MemAvailable", mem.get("MemFree", 0)) / 1024 / 1024
            used = total - avail
        except Exception:
            used, total = 0.0, 0.0
        try:
            uptime = float(open("/proc/uptime").read().split()[0])
        except Exception:
            uptime = 0.0
        try:
            nums = [int(x) for x in open("/proc/stat").readline().split()[1:]]
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
            total_j = sum(nums)
            if self._last_cpu is None:
                self._last_cpu = (total_j, idle)
                cpu = 0.0
            else:
                dt = total_j - self._last_cpu[0]
                di = idle - self._last_cpu[1]
                self._last_cpu = (total_j, idle)
                cpu = 0.0 if dt <= 0 else max(0.0, min(100.0, (1 - di / dt) * 100))
        except Exception:
            cpu = 0.0
        return {"ram_used_gb": used, "ram_total_gb": total, "cpu_pct": cpu, "uptime_secs": uptime, "net_ok": True}

    def fallback(self):
        return self.pump() or {"ram_used_gb": 0.0, "ram_total_gb": 0.0, "cpu_pct": 0.0, "uptime_secs": 0.0, "net_ok": True}


class StatsBar(Static):
    DEFAULT_CSS = """
    StatsBar {
        /* 3 content rows (logo + logo + credit) + the bottom border. */
        height: 4;
        width: 100%;
        dock: top;
        border-bottom: solid $jv-border;
        background: $jv-bg-1;
        padding: 0 1;
        color: $jv-fg-mute;
    }
    """

    def on_mount(self) -> None:
        self._stats = _SysStats()
        self._t0 = time.monotonic()
        self.set_interval(1.0, self._tick)
        self._tick()

    @staticmethod
    def _fit(parts: list[Text], need: int, width: int) -> Text:
        """Longest prefix of *parts* whose joined width fits in *width*.

        On a terminal too narrow for even the first fragment the stats are
        dropped entirely — the logo always renders (never wraps).
        """
        for i in range(len(parts), 0, -1):
            cand = Text()
            for p in parts[:i]:
                cand.append_text(p)
            if need + cell_len(cand.plain) <= width:
                return cand
        return Text()

    @staticmethod
    def _art(out: Text, line: str) -> None:
        """Append one wordmark row with the accent gradient used by the welcome."""
        hi = ui.blend(ui.ACCENT, ui.ACCENT_3, 0.35)
        n = max(1, len(line) - 1)
        for col, ch in enumerate(line):
            out.append(ch, style=f"bold {ui.blend(ui.ACCENT, hi, col / n)}")

    def _tick(self) -> None:
        s = self._stats.pump() or self._stats.fallback()
        used, total, cpu = (s.get(k, 0.0) for k in ("ram_used_gb", "ram_total_gb", "cpu_pct"))
        up = int(s.get("uptime_secs", time.monotonic() - self._t0))
        ram_fill = max(0, min(8, int(used / total * 8))) if total else 0
        cpu_fill = max(0, min(4, int(cpu / 25)))

        ram = Text()
        ram.append("▒" * ram_fill + "░" * (8 - ram_fill), style=ui.ACCENT_2)
        ram.append(" RAM ", style=ui.FG_DIM)
        ram.append(f"{used:.0f}G/{total:.0f}G", style=ui.ACCENT_2)
        cpu_p = Text()
        cpu_p.append("   |   ", style=ui.FG_DIM)
        cpu_p.append("▇" * cpu_fill + "░" * (4 - cpu_fill), style=ui.ACCENT_2)
        cpu_p.append(" CPU ", style=ui.FG_DIM)
        cpu_p.append(f"{cpu:.0f}%", style=ui.ACCENT_2)
        up_p = Text()
        up_p.append("   |   ", style=ui.FG_DIM)
        up_p.append("UPTIME ", style=ui.FG_DIM)
        up_p.append(f"{up // 3600}:{(up % 3600) // 60:02d}:{up % 60:02d}", style=ui.ACCENT_2)

        content_w = max(24, (self.size.width or 80) - 2)  # minus StatsBar padding
        right = self._fit([ram, cpu_p, up_p], len(_LOGO[0]) + 4, content_w)

        out = Text()
        for row, art in enumerate(_LOGO):
            if row:
                out.append("\n")
            self._art(out, art)
            if row == 0 and cell_len(right.plain):
                out.append(" " * max(1, content_w - len(_LOGO[0]) - cell_len(right.plain)))
                out.append_text(right)
        out.append("\n  ")
        out.append("✦ ", style=ui.ACCENT)
        out.append("created by ", style=ui.FG_DIM)
        head_w = 15  # the two-space indent + "✦ created by "
        name = _CREDIT
        if head_w + len(name) > content_w:  # narrow: clip, never wrap (bar is 3 rows)
            room = content_w - head_w
            name = name[: max(1, room - 1)] + "…" if room > 1 else ""
        if name:
            out.append(name, style=f"bold {ui.ACCENT}")
        ver = f"v{VERSION}"
        pad = content_w - head_w - len(name) - len(ver)
        if pad >= 1:
            out.append(" " * pad)
            out.append(ver, style=ui.FG_DIM)
        self.update(out)
