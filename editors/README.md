# Editor integrations for Arkad Agent

Arkad is a terminal agent — these configs make it reachable from your editor without leaving the buffer.

## Zed

Copy `zed/tasks.json` to `.zed/tasks.json` in your project and `zed/keybindings.json` entries into `~/.config/zed/keymap.json`.

- `cmd-shift-a` (macOS) — ask Arkad about the current selection
- `cmd-shift-alt-a` — start Arkad with the current file attached

## Neovim

Copy `nvim/arkad.lua` to `~/.config/nvim/lua/arkad.lua` and `require('arkad').setup()` from your init.

- `<leader>aa` — ask about the current line/selection
- `<leader>ad` — ask about diagnostics at point
- `<leader>at` — toggle an Arkad terminal split

## Emacs

Add `emacs/arkad.el` to your load path and `(require 'arkad)`.

- `M-x arkad-ask-region` — send the marked region
- `M-x arkad-ask` — ask with a minibuffer prompt
- `M-x arkad-toggle-terminal` — open/close the Arkad vterm
