"""Handlers for history/search/new/reset/clear."""
import json

from ..console import console, Table
from ..storage.sessions import db_create_session
from ..repl.banners import welcome_banner, header_panel
from .. import state


def handle_history(c: str, arg: str):
    """Return (handled, new_inp_or_None)."""
    if c in ("/reset", "/new"):
        state.messages = []
        state.tool_calls_count = 0
        state.total_in = 0
        state.total_out = 0
        state.total_tokens = 0
        state.current_session_id = db_create_session(state.MODEL)
        if c == "/new":
            console.clear(); welcome_banner(); header_panel()
        console.print(f"[green]✨ fresh conversation (session #{state.current_session_id})[/]")
        return True, None
    if c == "/clear":
        console.clear(); header_panel(); return True, None
    if c == "/history":
        if not state.messages: console.print("[dim]empty[/]"); return True, None
        t = Table(show_header=True, header_style="bold cyan", box=None)
        t.add_column("#"); t.add_column("role"); t.add_column("preview")
        for i, m in enumerate(state.messages):
            cn = m["content"]
            if isinstance(cn, str):
                preview = cn[:80]
            else:
                kinds = [getattr(b, "type", b.get("type") if isinstance(b, dict) else "?") for b in cn]
                preview = ",".join(kinds)
            t.add_row(str(i), m["role"], preview)
        console.print(t)
        return True, None
    if c == "/search":
        if not arg: console.print("usage: /search <query>"); return True, None
        q = arg.lower(); hits = 0
        for i, m in enumerate(state.messages):
            cn = m["content"]
            text = cn if isinstance(cn, str) else json.dumps(
                [b.model_dump() if hasattr(b, "model_dump") else b for b in cn])
            if q in text.lower():
                hits += 1
                idx = text.lower().find(q)
                snippet = text[max(0, idx-40):idx+80].replace("\n", " ")
                console.print(f"[cyan]{i}[/] [{m['role']}] …{snippet}…")
        console.print(f"[dim]{hits} hits[/]")
        return True, None
    return False, None
