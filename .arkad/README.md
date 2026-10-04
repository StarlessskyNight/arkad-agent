# .arkad/

Per-project Arkad configuration:

- `agents/<name>.md` — project-local agents (frontmatter + body markdown).
- `skills/<name>/SKILL.md` — instruction packs the LLM auto-invokes when
  their `description:` matches the task.
- `settings.json` — overrides for this project (merged over the global
  `~/.config/arkad-agent/settings.json`).

See `/agent` and `/skill` for activation and `~/.arkad/` for the
user-global counterpart.
