"""Persistent personal memory — small JSON store of facts about the user.

Shape on disk:
    {"facts": [{"id": 1, "text": "name: Prajwal", "ts": 1710000000}, ...],
     "next_id": 2}
"""
import json, re, threading, time
from typing import List, Dict, Optional

from ..constants import MEMORY_FILE, CONFIG_DIR
from ..utils.io import _atomic_write, _quarantine_corrupt

# Thread-level lock so concurrent tool calls (from ThreadPoolExecutor in
# render.py) don't race on read/write of the JSON file.
_file_lock = threading.Lock()


def _empty() -> Dict:
    return {"facts": [], "next_id": 1}


def _load() -> Dict:
    if not MEMORY_FILE.exists():
        return _empty()
    try:
        raw = MEMORY_FILE.read_text(encoding="utf-8")
    except OSError:
        return _empty()          # unreadable — leave the file alone, non-fatal
    except UnicodeDecodeError:
        raw = None               # binary garbage — corrupt, quarantine below
    if raw is None:
        _quarantine_corrupt(MEMORY_FILE)
        return _empty()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None              # corrupt — quarantine below so it isn't erased
    if not isinstance(data, dict):
        _quarantine_corrupt(MEMORY_FILE)
        return _empty()
    data.setdefault("facts", [])
    data.setdefault("next_id", 1)
    return data


def _save(data: Dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Atomic: a crash mid-write can never truncate the store, and the file
    # is 0600 from its first byte (utils/io._atomic_write).
    _atomic_write(MEMORY_FILE, json.dumps(data, indent=2, ensure_ascii=False))


def list_facts() -> List[Dict]:
    with _file_lock:
        return _load()["facts"]


# ── sensitive-data scrubber ───────────────────────────────────────────────
# Lives here (not in tools/memory.py) so EVERY save path — the memory_save
# tool AND the /memory add slash command — is covered. Deliberately narrow
# patterns to keep false positives low; long random/base64-ish blobs are
# NOT matched (too aggressive for free-form personal facts).
_SECRET_RES = [
    # PEM private key blocks (whole block, incl. truncated tail)
    (re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
        re.DOTALL), "[redacted]"),
    # OpenAI / Anthropic-style keys: sk-…
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[redacted]"),
    # GitHub tokens: ghp_ / gho_ / github_pat_
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "[redacted]"),
    (re.compile(r"\bgho_[A-Za-z0-9]{20,}\b"), "[redacted]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[redacted]"),
    # AWS access key id
    (re.compile(r"\bAKIA[A-Z0-9]{16}\b"), "[redacted]"),
    # Authorization header: keep the "Bearer" scheme, redact the token
    (re.compile(r"\b(Bearer\s+)[A-Za-z0-9._~+/=-]{16,}"), r"\1[redacted]"),
    # api_key / api-key / apikey assignments: keep the label, redact the
    # value (requires an explicit ``=``/``:`` and a single token of >=8,
    # so prose like "api key rotation policy" is left alone)
    (re.compile(
        r"\b(api[-_ ]?key\s*[=:]\s*)([\"']?)[A-Za-z0-9._+/-]{8,}\2",
        re.IGNORECASE), r"\1[redacted]"),
]


def scrub_secrets(text):
    """Replace obvious secret material with ``[redacted]``.

    Returns ``(text, changed)``; non-str input passes through untouched.
    Called from ``add_fact`` (storage invariant: secrets never persisted)
    and from ``tools/memory.memory_save`` (to append the user-facing notice).
    """
    if not isinstance(text, str):
        return text, False
    changed = False
    for rx, repl in _SECRET_RES:
        new = rx.sub(repl, text)
        if new != text:
            changed = True
            text = new
    return text, changed


def add_fact(text: str) -> Dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty fact")
    text, _ = scrub_secrets(text)   # never persist obvious secrets
    with _file_lock:
        data = _load()
        # dedupe on case-insensitive exact text
        for f in data["facts"]:
            if f["text"].lower() == text.lower():
                return f
        fact = {"id": data["next_id"], "text": text, "ts": int(time.time())}
        data["facts"].append(fact)
        data["next_id"] += 1
        _save(data)
    return fact


def delete_fact(fact_id: int) -> bool:
    with _file_lock:
        data = _load()
        before = len(data["facts"])
        data["facts"] = [f for f in data["facts"] if f["id"] != fact_id]
        if len(data["facts"]) == before:
            return False
        _save(data)
    return True


def clear_all() -> int:
    with _file_lock:
        data = _load()
        n = len(data["facts"])
        data["facts"] = []
        _save(data)
    return n


def as_prompt_block() -> str:
    """Render current memory as a short block for injection into the system prompt.

    Only includes a count summary — not the full facts. The full facts are
    loaded on demand when the agent calls memory_list(). This saves ~2-4K
    chars per turn when many facts are stored.
    """
    facts = list_facts()
    if not facts:
        return ""
    n = len(facts)
    return (
        f"WHAT YOU REMEMBER ABOUT THE USER: {n} fact{'s' if n != 1 else ''} stored. "
        f"Use memory_list() to view all when relevant — summaries are not injected here to save tokens."
    )
