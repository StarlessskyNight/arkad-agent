"""Filesystem paths used by the agent."""
import pathlib
import sys

CWD = pathlib.Path.cwd()
CONFIG_DIR = pathlib.Path.home() / ".config" / "arkad-agent"

# New canonical home for user-authored agents + skills (~/.arkad/).
# Read alongside the legacy CONFIG_DIR locations so existing users keep working.
ARKAD_HOME = pathlib.Path.home() / ".arkad"
ARKAD_AGENTS_DIR = ARKAD_HOME / "agents"
ARKAD_SKILLS_DIR = ARKAD_HOME / "skills"
ARKAD_COMMANDS_DIR = ARKAD_HOME / "commands"
ARKAD_SETTINGS_FILE = ARKAD_HOME / "settings.json"

# Project-local Arkad directory (per-repo .arkad/).
PROJECT_ARKAD_DIRNAME = ".arkad"
PROJECT_AGENTS_DIRNAME = ".arkad/agents"
PROJECT_SKILLS_DIRNAME = ".arkad/skills"
PROJECT_COMMANDS_DIRNAME = ".arkad/commands"
PROJECT_ARKAD_SETTINGS = ".arkad/settings.json"


def set_cwd(path: str | pathlib.Path) -> pathlib.Path:
    """Update Arkad' project root across already-imported modules."""
    new_cwd = pathlib.Path(path).expanduser().resolve()
    global CWD
    CWD = new_cwd

    for name, mod in list(sys.modules.items()):
        if not name.startswith("arkad.") or mod is None:
            continue
        if hasattr(mod, "CWD"):
            try:
                setattr(mod, "CWD", new_cwd)
            except Exception:
                pass
    return new_cwd

SESSIONS_LIST_LIMIT = 50
SESSION_TITLE_MAX_LENGTH = 80
KEY_FILE = CONFIG_DIR / "key"
OPENROUTER_KEY_FILE = CONFIG_DIR / "openrouter_key"
OPENCODE_KEY_FILE = CONFIG_DIR / "opencode_key"
OPENCODE_ZEN_KEY_FILE = CONFIG_DIR / "opencode_zen_key"
# API keys for providers discovered from models.dev ({"md:<id>": key}, 600).
PROVIDER_KEYS_FILE = CONFIG_DIR / "provider_keys.json"
OAUTH_FILE = CONFIG_DIR / "oauth.json"
CODEX_OAUTH_FILE = CONFIG_DIR / "codex_oauth.json"
AUTH_MODE_FILE = CONFIG_DIR / "auth_mode"
PROVIDER_FILE = CONFIG_DIR / "provider"
HIST_FILE = CONFIG_DIR / "history.json"
NOTES_FILE = CONFIG_DIR / "notes.md"
PIN_FILE = CONFIG_DIR / "pinned.txt"
ALIAS_FILE = CONFIG_DIR / "aliases.json"
SESSIONS_DB = CONFIG_DIR / "sessions.db"
MEMORY_FILE = CONFIG_DIR / "memory.json"
LESSONS_FILE = CONFIG_DIR / "lessons.json"
LAST_MODEL_FILE = CONFIG_DIR / "last_model.json"
LAST_THEME_FILE = CONFIG_DIR / "last_theme.json"
SKILLS_CONFIG_FILE = CONFIG_DIR / "skills_config.json"
THINK_CONFIG_FILE = CONFIG_DIR / "think_config.json"
MCP_PREFS_FILE = CONFIG_DIR / "mcp_config.json"
