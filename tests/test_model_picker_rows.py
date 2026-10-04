"""Model picker always exposes Arkad Agent rows — and never blocks on I/O."""
import pytest

from arkad.constants.providers import ARKAD_AGENT_FALLBACK_MODEL, PROVIDER_ARKAD_AGENT
from arkad.tui.model_modal import model_picker_rows

_FETCH = "arkad.auth.zen_catalog.fetch_free_models"
_CACHED = "arkad.auth.zen_catalog.cached_free_models"


@pytest.fixture(autouse=True)
def _cold_cache(monkeypatch):
    """Default to an empty catalog cache so these assertions don't depend on
    whatever the developer's machine happens to have fetched."""
    monkeypatch.setattr(_CACHED, lambda *a, **k: [])
    monkeypatch.setattr(
        "arkad.auth.openrouter_catalog.cached_free_models", lambda *a, **k: []
    )


def test_model_picker_rows_always_includes_arkad_agent(monkeypatch):
    monkeypatch.setattr(_FETCH, lambda *a, **k: None)
    rows = model_picker_rows()
    arkad = [(src, mid) for src, mid, _ in rows if src == PROVIDER_ARKAD_AGENT]
    assert arkad == [(PROVIDER_ARKAD_AGENT, ARKAD_AGENT_FALLBACK_MODEL)]
    assert rows[0][0] == PROVIDER_ARKAD_AGENT


def test_model_picker_rows_surfaces_live_free_models(monkeypatch):
    """A brand-new free model on OpenCode Zen appears without a code change."""
    from arkad.auth import models_dev, opencode_catalog

    models_dev.store(models_dev.trim({"opencode": {
        "id": "opencode", "name": "OpenCode Zen", "npm": "@ai-sdk/openai-compatible",
        "api": "https://opencode.ai/zen/v1", "env": ["OPENCODE_ZEN_API_KEY"],
        "models": {"brand-new-free": {
            "id": "brand-new-free", "name": "Brand New Free", "tool_call": True,
            "cost": {"input": 0, "output": 0}, "release_date": "2026-09-01",
            "modalities": {"input": ["text"], "output": ["text"]},
            "limit": {"context": 128000, "output": 8192},
        }},
    }}))
    monkeypatch.setattr(opencode_catalog, "served_ids", lambda provider: {"brand-new-free"})
    rows = model_picker_rows(live=True)
    assert rows[0][:2] == (PROVIDER_ARKAD_AGENT, "brand-new-free")


def test_model_picker_rows_reads_cache_without_network(monkeypatch):
    """The default (what the picker uses on open) must never hit the network."""
    monkeypatch.setattr(_FETCH, lambda *a, **k: pytest.fail("network used on open"))
    monkeypatch.setattr(_CACHED, lambda *a, **k: [("cached-free", "Cached Free")])
    rows = model_picker_rows()
    ids = [mid for src, mid, _ in rows if src == PROVIDER_ARKAD_AGENT]
    assert ids == ["cached-free"]  # no built-in list padding it out any more


def test_model_picker_rows_falls_back_offline(monkeypatch):
    monkeypatch.setattr(_FETCH, lambda *a, **k: None)
    rows = model_picker_rows()
    assert rows, "picker must never be empty"
    assert rows[0][1] == ARKAD_AGENT_FALLBACK_MODEL


# ─── Tags: free · sees images (same rules as the web picker) ───────────


def test_model_tags_line_up_and_strip_the_word_free():
    from arkad.tui.model_modal import _free_less, model_tags, tags_width

    assert tags_width(True, True) == 9 and tags_width(False, True) == 3 and tags_width(False, False) == 0
    assert model_tags(free=True, images=True).plain == "  free  ◩"
    assert model_tags(free=False, images=True, free_slot=True).plain == "        ◩"
    assert model_tags(free=False, images=False).plain == ""
    for desc, want in (("1M ctx, free", "1M ctx"), ("Nemotron 3 Ultra Free", "Nemotron 3 Ultra"),
                       ("free", ""), ("OpenRouter Free — auto-routed", "OpenRouter Free — auto-routed"),
                       ("carefree", "carefree")):
        assert _free_less(desc) == want


def test_picker_tags_free_and_vision_models_and_filters_them(monkeypatch):
    import asyncio

    import arkad.constants.providers as providers
    import arkad.tui.model_modal as mm

    rows = [
        ("arkad_agent", "mimo-v2.5-free", "MiMo V2.5 Free — default"),
        ("openrouter", "qwen/qwen3.8-27b:free", "Qwen3.8 27B — free"),
        ("anthropic_api", "claude-sonnet-5-5", "Sonnet 5.5 — latest Sonnet"),
        ("anthropic_api", "claude-text-only", "no pictures"),
    ]
    monkeypatch.setattr(mm, "model_picker_rows", lambda live=False: rows)
    monkeypatch.setattr(mm, "_unconnected_catalog_providers", lambda: [])
    monkeypatch.setattr(mm, "model_sees_images", lambda mid, src: mid in ("qwen/qwen3.8-27b:free", "claude-sonnet-5-5"))
    monkeypatch.setattr(mm, "free_model_ids", lambda: {"openrouter": {"qwen/qwen3.8-27b:free"}})
    monkeypatch.setattr(providers, "model_catalogs_are_fresh", lambda: True)
    monkeypatch.setattr(mm, "_recent_models", lambda: [])

    def shown(screen) -> dict[str, str]:
        from rich.console import Console

        opts = screen.query_one("#model_list")
        out = {}
        for i in range(opts.option_count):
            opt = opts.get_option_at_index(i)
            if opt.id and "::" in str(opt.id):
                con = Console(width=110, color_system=None)
                with con.capture() as cap:
                    con.print(opt.prompt)
                out[str(opt.id).split("::", 1)[1]] = cap.get().rstrip()
        return out

    monkeypatch.setenv("ARKAD_SKIP_UPDATE", "1")
    import arkad.mcp.registry as mcp_registry
    import arkad.storage.sessions as sessions
    import arkad.tui.prompt_history as prompt_history
    import arkad.updater as updater
    from arkad.tui.app import ArkadTUI

    monkeypatch.setattr(updater, "maybe_update_and_reexec", lambda: None)
    monkeypatch.setattr(mcp_registry, "auto_connect_servers", lambda console_print=None, **kw: None,
                        raising=False)
    monkeypatch.setattr(sessions, "db_init", lambda: None)
    monkeypatch.setattr(sessions, "db_create_session", lambda model: None)
    monkeypatch.setattr(prompt_history.PromptHistory, "_save", lambda self: None)
    monkeypatch.setattr(ArkadTUI, "_warm_model_catalogs_background", lambda self: None)

    async def run():
        app = ArkadTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            screen = mm.ModelPickerScreen()
            app.push_screen(screen)
            await pilot.pause(0.2)
            lines = shown(screen)
            assert lines["mimo-v2.5-free"].endswith("free")
            assert lines["qwen/qwen3.8-27b:free"].endswith("free  ◩")
            assert lines["claude-sonnet-5-5"].endswith("◩") and "free" not in lines["claude-sonnet-5-5"]
            assert not lines["claude-text-only"].endswith(("◩", "free"))
            # Each tag sits in the same column on every row that has it.
            assert len({v.rindex("◩") for v in lines.values() if "◩" in v}) == 1, lines
            assert len({v.rindex("free") for k, v in lines.items() if k != "claude-text-only"
                        and v.rstrip().endswith(("free", "◩")) and "free" in v[-10:]}) == 1, lines
            screen._populate("free")
            assert set(shown(screen)) == {"mimo-v2.5-free", "qwen/qwen3.8-27b:free"}
            screen._populate("vision")
            assert set(shown(screen)) == {"qwen/qwen3.8-27b:free", "claude-sonnet-5-5"}

    asyncio.run(run())
