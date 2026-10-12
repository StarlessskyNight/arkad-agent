"""Storage hardening: private-by-create writes, atomic memory/lessons saves,
corrupt-file quarantine, sessions.db PRAGMAs, the guarded PIN read, and the
memory secret scrubber.

Covers the P1/P2/P3 fixes from .audit/security.md #6 and
.audit/state_context.md #3/#4/#9.
"""
from __future__ import annotations

import json
import os
import stat

import pytest

from arkad import state
from arkad.storage import lessons as les
from arkad.storage import memory as mem
from arkad.tools import memory as tmem
from arkad.utils import io as io_mod


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def memstore(tmp_path, monkeypatch):
    f = tmp_path / "memory.json"
    monkeypatch.setattr(mem, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(mem, "MEMORY_FILE", f)
    return f


@pytest.fixture()
def lesstore(tmp_path, monkeypatch):
    f = tmp_path / "lessons.json"
    monkeypatch.setattr(les, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(les, "LESSONS_FILE", f)
    return f


@pytest.fixture()
def sdb(tmp_path, monkeypatch):
    import arkad.storage.sessions as sessions

    monkeypatch.setattr(sessions, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(sessions, "SESSIONS_DB", tmp_path / "sessions.db")
    sessions.db_init()
    return sessions


def _spy_fdopen(monkeypatch, seen):
    """Record mode+size of the file at the moment fdopen receives the fd —
    i.e. after open, before any data is written."""
    real_fdopen = os.fdopen

    def spy(fd, *args, **kwargs):
        st = os.fstat(fd)
        seen["mode"] = stat.S_IMODE(st.st_mode)
        seen["size"] = st.st_size
        return real_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", spy)


# ── utils/io._secure_write ──────────────────────────────────────────────────

def test_secure_write_is_0600_from_the_first_byte(tmp_path, monkeypatch):
    path = tmp_path / "key.txt"
    monkeypatch.setattr(io_mod, "CONFIG_DIR", tmp_path)
    seen = {}
    _spy_fdopen(monkeypatch, seen)
    io_mod._secure_write(path, "sk-secret")
    # mode locked down and no data written yet at the moment of fdopen
    assert seen["mode"] == 0o600
    assert seen["size"] == 0
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text(encoding="utf-8") == "sk-secret"


def test_secure_write_tightens_preexisting_world_readable_file(tmp_path, monkeypatch):
    path = tmp_path / "key.txt"
    path.write_text("old-key")
    os.chmod(path, 0o644)
    monkeypatch.setattr(io_mod, "CONFIG_DIR", tmp_path)
    seen = {}
    _spy_fdopen(monkeypatch, seen)
    io_mod._secure_write(path, "new-secret")
    # pre-existing loose mode tightened BEFORE the new secret lands
    assert seen["mode"] == 0o600
    assert seen["size"] == 0          # old content already truncated, none new yet
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text(encoding="utf-8") == "new-secret"


def test_secure_write_raises_and_never_writes_when_lockdown_fails(tmp_path, monkeypatch):
    """The old version swallowed a failed chmod and left the secret exposed;
    now it raises and the data is never written at all."""
    path = tmp_path / "key.txt"
    monkeypatch.setattr(io_mod, "CONFIG_DIR", tmp_path)

    def boom(fd, mode):
        raise OSError("simulated fchmod failure")

    monkeypatch.setattr(os, "fchmod", boom)
    with pytest.raises(OSError):
        io_mod._secure_write(path, "sk-secret")
    assert not path.exists() or path.read_text(encoding="utf-8") == ""


def test_secure_write_propagates_open_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(io_mod, "CONFIG_DIR", tmp_path)
    with pytest.raises(OSError):
        io_mod._secure_write(tmp_path / "no-such-dir" / "key.txt", "x")


# ── utils/io._atomic_write ──────────────────────────────────────────────────

def test_atomic_write_is_private_and_leaves_no_temp(tmp_path):
    path = tmp_path / "store.json"
    io_mod._atomic_write(path, "{}")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not path.with_name("store.json.tmp").exists()


def test_atomic_write_failure_keeps_destination_intact(tmp_path, monkeypatch):
    path = tmp_path / "store.json"
    io_mod._atomic_write(path, '{"old": true}')

    def boom(a, b):
        raise OSError("simulated crash mid-save")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        io_mod._atomic_write(path, '{"new": false}')
    assert path.read_text(encoding="utf-8") == '{"old": true}'


# ── storage/memory: atomic save + corrupt quarantine ───────────────────────

def test_memory_save_is_atomic_private_and_leaves_no_temp(memstore):
    mem.add_fact("name: Prajwal")
    assert stat.S_IMODE(memstore.stat().st_mode) == 0o600
    assert not memstore.with_name("memory.json.tmp").exists()
    data = json.loads(memstore.read_text(encoding="utf-8"))
    assert [f["text"] for f in data["facts"]] == ["name: Prajwal"]


def test_memory_save_failure_preserves_previous_store(memstore, monkeypatch):
    mem.add_fact("first fact")
    before = memstore.read_text(encoding="utf-8")

    def boom(a, b):
        raise OSError("simulated crash mid-save")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        mem.add_fact("second fact")
    assert memstore.read_text(encoding="utf-8") == before


def test_memory_corrupt_file_is_quarantined_not_erased(memstore):
    garbage = b'{"facts": [{"id": 1, "te'
    memstore.write_bytes(garbage)
    assert mem.list_facts() == []                       # load stays non-fatal
    backup = memstore.with_name("memory.json.corrupt")
    assert backup.read_bytes() == garbage               # original bytes preserved
    assert not memstore.exists()
    # a fresh save recreates the store; the backup is kept for inspection
    mem.add_fact("after crash")
    assert memstore.exists()
    assert backup.read_bytes() == garbage


def test_memory_wrong_shape_is_quarantined(memstore):
    memstore.write_text("[1, 2, 3]")
    assert mem.list_facts() == []
    assert memstore.with_name("memory.json.corrupt").read_text() == "[1, 2, 3]"


def test_memory_binary_garbage_is_quarantined(memstore):
    memstore.write_bytes(b"\xff\xfe\x00broken")
    assert mem.list_facts() == []
    assert memstore.with_name("memory.json.corrupt").exists()


def test_memory_unreadable_file_load_is_non_fatal_and_left_alone(tmp_path, monkeypatch):
    # A directory in place of the file raises IsADirectoryError on read for
    # any user (chmod-000 would not, when tests run as root).
    monkeypatch.setattr(mem, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(mem, "MEMORY_FILE", tmp_path)
    assert mem.list_facts() == []
    assert tmp_path.is_dir()                             # not quarantined/moved


def test_corrupt_backup_is_single_most_recent(memstore):
    memstore.write_text("old corrupt one")
    mem.list_facts()
    memstore.write_text("new corrupt two")
    mem.list_facts()
    backup = memstore.with_name("memory.json.corrupt")
    assert backup.read_text() == "new corrupt two"


# ── storage/lessons: same hardening ─────────────────────────────────────────

def test_lessons_save_is_atomic_private_and_leaves_no_temp(lesstore):
    les.add_lesson("git rebase", "use --autostash", ["git"])
    assert stat.S_IMODE(lesstore.stat().st_mode) == 0o600
    assert not lesstore.with_name("lessons.json.tmp").exists()
    assert json.loads(lesstore.read_text(encoding="utf-8"))["lessons"][0]["task"] == "git rebase"


def test_lessons_corrupt_file_is_quarantined_not_erased(lesstore):
    garbage = b'{"lessons": [broke'
    lesstore.write_bytes(garbage)
    assert les.list_lessons() == []
    backup = lesstore.with_name("lessons.json.corrupt")
    assert backup.read_bytes() == garbage
    assert not lesstore.exists()


# ── storage/sessions: PRAGMAs ───────────────────────────────────────────────

def test_db_conn_applies_hardening_pragmas(sdb):
    c = sdb.db_conn()
    try:
        assert c.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        c.close()


def test_foreign_key_cascade_is_enforced(sdb):
    sid = sdb.db_create_session("m")
    sdb.db_append_message(sid, 0, {"role": "user", "content": "hi"})
    with sdb.db_conn() as c:
        # plain session delete — no manual message cleanup like db_delete_session
        c.execute("DELETE FROM sessions WHERE id=?", (sid,))
    with sdb.db_conn() as c:
        n = c.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=?", (sid,)
        ).fetchone()[0]
    assert n == 0                                        # ON DELETE CASCADE fired


def test_session_roundtrip_still_works(sdb):
    sid = sdb.db_create_session("m")
    sdb.db_append_message(sid, 0, {"role": "user", "content": "hi"})
    sdb.db_append_message(sid, 1, {"role": "assistant", "content": "yo"})
    assert [m["role"] for m in sdb.db_load_session(sid)] == ["user", "assistant"]
    assert sdb.db_delete_session(sid)
    assert sdb.db_load_session(sid) is None


# ── state: guarded PIN read ─────────────────────────────────────────────────

def test_read_pin_file_returns_content(tmp_path, monkeypatch):
    pin = tmp_path / "pinned.txt"
    pin.write_text("always be concise")
    monkeypatch.setattr(state, "PIN_FILE", pin)
    assert state._read_pin_file() == "always be concise"


def test_read_pin_file_missing_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "PIN_FILE", tmp_path / "nope.txt")
    assert state._read_pin_file() == ""


def test_read_pin_file_unreadable_does_not_raise(tmp_path, monkeypatch):
    pin = tmp_path / "pinned.txt"
    pin.mkdir()                                          # IsADirectoryError on read
    monkeypatch.setattr(state, "PIN_FILE", pin)
    assert state._read_pin_file() == ""


# ── memory: secret scrubber ─────────────────────────────────────────────────

@pytest.mark.parametrize("raw,secret", [
    ("openai key: sk-proj-Abc123Def456Ghi789", "sk-proj-Abc123Def456Ghi789"),
    ("my ci token is ghp_a1B2a1B2a1B2a1B2a1B2a1B2 thanks", "ghp_a1B2a1B2a1B2a1B2a1B2a1B2"),
    ("rotated gho_0123456789abcdefghijklmn last week", "gho_0123456789abcdefghijklmn"),
    ("leaked github_pat_abcdefghij1234567890abcdefghij today",
     "github_pat_abcdefghij1234567890abcdefghij"),
    ("aws access key AKIAABCDEF1234567890", "AKIAABCDEF1234567890"),
    ("header: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
     "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"),
    ("api_key = Abc12345Secret", "Abc12345Secret"),
    ("api_key: \"Qu0t3dSecret99\"", "Qu0t3dSecret99"),
    ("API KEY: hunter2secret", "hunter2secret"),
    ("private key:\n-----BEGIN RSA PRIVATE KEY-----\nMIIEpQIBAAK\n-----END RSA PRIVATE KEY-----\nend",
     "MIIEpQIBAAK"),
])
def test_scrub_secrets_hits(raw, secret):
    scrubbed, changed = mem.scrub_secrets(raw)
    assert changed
    assert secret not in scrubbed
    assert "[redacted]" in scrubbed


def test_scrub_secrets_keeps_the_bearer_scheme():
    scrubbed, changed = mem.scrub_secrets("Bearer eyJhbGciOiJIUzI1NiJ9abcdefghij")
    assert changed and scrubbed.startswith("Bearer [redacted]")


@pytest.mark.parametrize("raw", [
    "name: Prajwal",
    "prefers concise replies",
    "favorite editor: VS Code",
    "email is firstname.lastname@example.com",
    "api key rotation policy reviewed quarterly",
    "worked on sk-learn models daily",
    "bearer of good news",
    "remembers birthdays in the family",
])
def test_scrub_secrets_misses(raw):
    scrubbed, changed = mem.scrub_secrets(raw)
    assert not changed
    assert scrubbed == raw


def test_scrub_secrets_passes_through_non_strings():
    assert mem.scrub_secrets(None) == (None, False)
    assert mem.scrub_secrets(42) == (42, False)


def test_memory_save_tool_redacts_with_notice(memstore):
    out = tmem.memory_save(text="deploy uses sk-proj-Abc123Def456Ghi789 for CI")
    assert out.startswith("saved #1:")
    assert "[redacted]" in out
    assert "must not be stored in memory" in out
    stored = mem.list_facts()[0]["text"]
    assert "sk-proj-Abc123Def456Ghi789" not in stored
    assert "[redacted]" in stored


def test_memory_save_tool_plain_fact_has_no_notice(memstore):
    out = tmem.memory_save(text="prefers concise replies")
    assert out == "saved #1: prefers concise replies"


def test_add_fact_scrubs_without_the_tool(memstore):
    # /memory add calls storage directly — still redacted on disk
    f = mem.add_fact("github token ghp_0123456789abcdefghij for releases")
    assert "ghp_0123456789abcdefghij" not in f["text"]
    assert "[redacted]" in f["text"]


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
