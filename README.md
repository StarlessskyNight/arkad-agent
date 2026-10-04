# Arkad Agent

A terminal-native AI coding agent — starts on the free Arkad Agent tier, with
opt-in cloud providers (Anthropic, OpenRouter, OpenCode, Codex, models.dev).
It reads your project, plans, edits files, runs shell commands, and checks its
own work — with a Textual TUI (default) and a legacy Rich REPL.

Requires Python 3.10+.

## Install

Linux / macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/StarlessskyNight/arkad-agent/main/scripts/install | bash
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/StarlessskyNight/arkad-agent/main/scripts/install.ps1 | iex"
```

Uninstall (removes everything — install, config, data, shims, PATH entries):

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/StarlessskyNight/arkad-agent/main/scripts/uninstall | bash
```

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/StarlessskyNight/arkad-agent/main/scripts/uninstall.ps1 | iex"
```

From a checkout:

```bash
# from a checkout
cd arkad-agent
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/arkad-agent        # or: arkad

# or the installer script
./scripts/install
```

## Usage

```bash
arkad                  # Textual TUI (default)
arkad --legacy         # Rich REPL
arkad --web [PORT]     # browser mirror of the console
arkad update           # pull latest and reinstall (alias: arkad upgrade)
```

Inside the session: slash commands (`/model`, `/mcp`, `/memory`, `/skill`, …),
agent switching, persistent memory, lessons, session history, MCP servers.

## Models & providers

- Out of the box Arkad uses the free **Arkad Agent** tier — no API key needed.
- Cloud providers — Anthropic, OpenRouter, OpenCode (Go + Zen), OpenAI Codex,
  and models.dev catalog providers — are opt-in via `/login`, `/key`, or the
  provider file at `~/.config/arkad-agent/provider`.
- Switch models with `/model`; `/provider` (or the TUI provider hub) changes backend.

## Repository layout

```
agent.py               Thin entrypoint -> arkad/tui/app.py (default) or arkad/main.py (--legacy)
arkad/                 Main package
  cli.py               argparse entrypoint: `arkad` / `arkad-agent`
  main.py              Legacy Rich REPL loop
  loop.py              Agentic tool-call loop
  state.py             Module-level shared state (client, messages, model, flags)
  bootstrap.py         Startup wiring
  console.py, media.py, path_resolve.py, project_context.py, install_sync.py, updater.py, …
  auth/                API key, OAuth PKCE, OpenRouter/OpenCode/Codex clients, provider catalogs
  commands/            Slash command handlers (dispatch.py routes)
  constants/           Paths, model/provider ids, system prompt, OAuth endpoints
  mcp/                 MCP server install/manager/registry/config/auth
  repl/                Stream handling, rendering, hallucination guard, context trimming
  storage/             SQLite sessions, memory, skills, lessons, prefs, settings
  tools/               Tool implementations; router.py picks schemas per turn
    mac/               macOS control (apps, AppleScript, UI, clicks, keystrokes, clipboard)
    web/               Web fetch + verified-source search
    context/           Context bundling helpers
  tui/                 Textual app, modals (provider/model/mcp/session/…), transcript
  utils/               clipboard, paths, json repair, http, schema, tool repair
  web/                 Browser mirror UI + actions/commands APIs
editors/               Zed / Neovim / Emacs integration snippets
scripts/               install, install-global, install.ps1, test-install, …
tests/                 pytest suite (conftest isolates HOME)
.arkad/                Project-local agents (coding.md, fast.md, qa-help.md, …) and skills
assets/                Logos + social preview
```

## Data & config

- Global config: `~/.config/arkad-agent/` (sessions.db, provider, settings.json)
- User agents/skills/commands: `~/.arkad/`
- Project-local overrides: `.arkad/` in the repo
- Sessions/lessons/memory are compact SQLite/JSON by design. No telemetry.

## Environment variables

| Var | Default | Meaning |
| --- | --- | --- |
| `ARKAD_PROVIDER` | *(auto)* | Force provider: `anthropic`, `openrouter`, `opencode`, `opencode_zen`, `openai_codex` |
| `CLAUDE_MODEL` | *(unset)* | Override model id at startup |
| `ARKAD_MAX_PARALLEL_TOOLS` | `64` | Cap on parallel tool calls |
| `ARKAD_HTTP_READ_TIMEOUT` | 240–600s | Max seconds between bytes on a streaming response |
| `ARKAD_HTTP_CONNECT_TIMEOUT` | `30` | Connection timeout in seconds |

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests -q
```

## License

GNU GPL v3.0 — see [LICENSE](LICENSE).
