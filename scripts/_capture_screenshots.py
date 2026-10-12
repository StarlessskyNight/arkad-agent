#!/usr/bin/env python3
"""Dev-only: capture authentic screenshots of Arkad's interfaces for the README.

Run from the repo root:

    .venv/bin/pip install cairosvg pyte      # render helpers (dev-only)
    .venv/bin/python scripts/_capture_screenshots.py

Outputs (real application output, nothing mocked):

    assets/screenshots/tui-welcome.png       `arkad` — Textual TUI, fresh launch
    assets/screenshots/tui-model-picker.png  the /model picker modal
    assets/screenshots/repl-legacy.png       `arkad --legacy` — Rich REPL
    assets/screenshots/web-ui.png            browser remote (real local server)

Hermetic: HOME points at a throwaway dir, updates and MCP auto-connect are
stubbed, and no model turn is ever executed — only launch/welcome screens.
The web shot starts the app's own loopback server and drives it with a
headless Chromium (system python3 + playwright) in a child process.
"""
from __future__ import annotations

import asyncio
import codecs
import os
import pty
import re
import shutil
import site
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import fcntl
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHOTS = ROOT / "assets" / "screenshots"

# Pristine process env, captured before any hermetic mutation: the browser
# child must keep the real HOME (playwright + its browser cache live there)
# and the real user site-packages (playwright is installed per-user).
BASE_ENV = dict(os.environ)
USER_SITE = site.getusersitepackages()

TUI_SIZE = (140, 42)
WEB_VIEWPORT = {"width": 1440, "height": 900}


# ── helpers ──────────────────────────────────────────────────────────────────

def _hermetic_env(home: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        HOME=home,
        ARKAD_SKIP_UPDATE="1",
        ARKAD_WEB="0",
        ANTHROPIC_API_KEY="sk-ant-dummy",  # pins a provider; never used, no turn runs
        TERM="xterm-256color",
    )
    env.pop("CLAUDE_MODEL", None)
    return env


def _stub_side_effects() -> None:
    """Silence auto-update, MCP auto-connect (would touch network/processes)."""
    import arkad.updater as updater
    import arkad.mcp.registry as mcp_registry

    updater.maybe_update_and_reexec = lambda: None  # type: ignore[assignment]
    mcp_registry.auto_connect_servers = lambda console_print=None, **kw: None  # type: ignore[assignment]


def _svg_to_png(svg: str, out: pathlib.Path, scale: float = 1.0) -> None:
    """Rasterise Rich's terminal SVG with a locally installed monospace face.

    The SVG references Fira Code from a CDN; GitHub renders that fine in a
    browser, but for a hermetic offline render we point it at JetBrains Mono
    (installed system-wide) and drop the @font-face block.
    """
    import cairosvg

    svg = re.sub(r"@font-face\s*\{.*?\}", "", svg, flags=re.S)
    svg = svg.replace("font-family: Fira Code, monospace;",
                      'font-family: "JetBrains Mono", monospace;')
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(out), scale=scale)
    print("saved", out.relative_to(ROOT))


# ── TUI shots (textual Pilot, headless) ──────────────────────────────────────

async def shot_tui() -> None:
    home = tempfile.mkdtemp(prefix="arkad-shot-home-")
    os.environ.clear()
    os.environ.update(_hermetic_env(home))
    os.chdir(ROOT)
    _stub_side_effects()

    from arkad.tui.app import ArkadTUI

    # 1) Fresh launch — welcome block, stats bar, composer.
    app = ArkadTUI()
    async with app.run_test(size=TUI_SIZE) as pilot:
        await pilot.pause(1.0)
        svg = app.export_screenshot(title="arkad-agent")
        _svg_to_png(svg, SHOTS / "tui-welcome.png")

    # 2) /model picker.
    app = ArkadTUI()
    async with app.run_test(size=TUI_SIZE) as pilot:
        await pilot.pause(1.0)
        await pilot.press("slash")
        for ch in "model":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause(2.5)  # rows are built from cache; live refresh may swap in
        svg = app.export_screenshot(title="arkad-agent /model")
        _svg_to_png(svg, SHOTS / "tui-model-picker.png")


# ── web UI shot: real server + headless Chromium ─────────────────────────────

async def shot_web() -> None:
    home = tempfile.mkdtemp(prefix="arkad-shot-home-")
    os.environ.clear()
    os.environ.update(_hermetic_env(home))
    os.chdir(ROOT)
    _stub_side_effects()

    from arkad import state
    from arkad.tui.app import ArkadTUI

    with socket.socket() as s:  # a definitely-free loopback port
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    state.web_enabled = True
    state.web_port = free_port

    app = ArkadTUI()
    async with app.run_test(size=TUI_SIZE) as pilot:
        await pilot.pause(1.5)
        url = app._web_primary_url
        assert url and url.startswith("http"), f"no web url: {url!r}"
        print("web url:", url.split("?")[0] + "?token=…")
        # The browser half needs playwright — run it under whichever python3
        # on PATH has it, with the *original* HOME and user site restored.
        child_env = dict(BASE_ENV)
        prior_pp = child_env.get("PYTHONPATH")
        child_env["PYTHONPATH"] = USER_SITE + (os.pathsep + prior_pp if prior_pp else "")
        proc = await asyncio.create_subprocess_exec(
            shutil.which("python3", path=BASE_ENV.get("PATH")) or sys.executable,
            str(ROOT / "scripts/_capture_screenshots.py"),
            "--shot-browser", url, str(SHOTS / "web-ui.png"),
            env=child_env,
        )
        rc = await proc.wait()
        if rc != 0:
            raise SystemExit(f"browser capture failed (rc={rc})")


def shot_browser(url: str, out: str) -> None:
    """Child mode, run under a python that has playwright installed."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport=WEB_VIEWPORT, device_scale_factor=1.5)
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector("#starters, #prompt", timeout=20_000)
        page.wait_for_timeout(2_500)  # SSE connect + initial snapshot
        page.screenshot(path=out)
        browser.close()
    print("saved", pathlib.Path(out).name)


# ── legacy REPL shot: real pty + a real VT emulator (pyte) ───────────────────

def shot_repl() -> None:
    import pyte
    from PIL import Image, ImageDraw, ImageFont

    home = tempfile.mkdtemp(prefix="arkad-shot-home-")
    cols, rows = 120, 40
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "agent.py"), "--legacy"],
        cwd=ROOT, stdin=slave, stdout=slave, stderr=slave,
        env=_hermetic_env(home), start_new_session=True,
    )
    os.close(slave)

    screen = pyte.Screen(cols, rows)
    stream = pyte.Stream(screen)
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    deadline = time.time() + 20
    got_first = False
    quiet_since = None
    os.set_blocking(master, False)
    while time.time() < deadline:
        try:
            data = os.read(master, 65536)
        except (BlockingIOError, OSError):
            data = b""
        if data:
            stream.feed(decoder.decode(data))
            got_first = True
            quiet_since = None
        elif got_first:  # grace: don't treat boot latency as "quiet"
            if quiet_since is None:
                quiet_since = time.time()
            elif time.time() - quiet_since > 2.5:
                break
        time.sleep(0.1)
    stream.feed(decoder.decode(b"", True))
    if not got_first:
        raise SystemExit("legacy REPL produced no output on the pty")
    try:
        proc.kill()
    except Exception:
        pass
    os.close(master)
    proc.wait()

    # Render the emulated screen — every char/colour the REPL actually printed.
    cell_w, cell_h, fs = 9, 18, 15
    font = ImageFont.truetype(
        "/usr/share/fonts/jetbrains-mono-fonts/JetBrainsMono-Regular.otf", fs)
    img = Image.new("RGB", (cols * cell_w, rows * cell_h), (5, 7, 10))
    d = ImageDraw.Draw(img)

    def colour(c, default=(0, 0, 0)):
        if c in ("default", None):
            return default
        if c.startswith("#") and len(c) == 7:
            return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
        return default

    for y in range(rows):
        x = 0
        while x < cols:
            cell = screen.buffer[y][x]
            bg = colour(cell.bg)
            fg = colour(cell.fg, (185, 202, 219))
            run, w = "", 0
            while x + w < cols and screen.buffer[y][x + w].data != "\x00":
                b = screen.buffer[y][x + w]
                if colour(b.bg) != bg or colour(b.fg, (185, 202, 219)) != fg:
                    break
                run += b.data if b.data != "\x00" else " "
                w += 1
            if bg != (0, 0, 0):
                d.rectangle([x * cell_w, y * cell_h,
                             (x + w) * cell_w - 1, (y + 1) * cell_h - 1], fill=bg)
            if run.strip():
                d.text((x * cell_w, y * cell_h + 1), run, font=font, fill=fg)
            x += max(w, 1)
    out = SHOTS / "repl-legacy.png"
    img.save(out, optimize=True)
    print("saved", out.relative_to(ROOT))


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] == "--shot-browser":
        shot_browser(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--web":
        asyncio.run(shot_web())
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--repl":
        shot_repl()
        return
    asyncio.run(shot_tui())
    asyncio.run(shot_web())
    shot_repl()


if __name__ == "__main__":
    main()
