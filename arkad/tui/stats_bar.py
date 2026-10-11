"""Persistent top header bar with live system stats (RAM/CPU/UPTIME)."""
from __future__ import annotations

import time

from rich.text import Text
from textual.widgets import Static

from . import theme as ui


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
        height: 2;
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
