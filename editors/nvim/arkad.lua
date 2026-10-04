local M = {}

local function visual_selection()
  local _, srow, scol = unpack(vim.fn.getpos("'<"))
  local _, erow, ecol = unpack(vim.fn.getpos("'>"))
  local lines = vim.fn.getline(srow, erow)
  if #lines == 0 then return "" end
  lines[#lines] = string.sub(lines[#lines], 1, ecol)
  lines[1] = string.sub(lines[1], scol)
  return table.concat(lines, "\n")
end

local function ask(question)
  vim.cmd("vsplit | terminal arkad-agent")
  vim.defer_fn(function()
    vim.fn.chansend(vim.b.terminal_job_id, question .. "\n")
  end, 800)
end

function M.ask_selection()
  ask("Explain this code:\n" .. visual_selection())
end

function M.ask_diagnostics()
  local diags = vim.diagnostic.get(0)
  local lines = {}
  for _, d in ipairs(diags) do
    table.insert(lines, string.format("L%d: %s", d.lnum + 1, d.message))
  end
  ask("Fix these diagnostics:\n" .. table.concat(lines, "\n"))
end

function M.toggle_terminal()
  for _, buf in ipairs(vim.api.nvim_list_bufs()) do
    if vim.bo[buf].buftype == "terminal" then
      for _, win in ipairs(vim.api.nvim_list_wins()) do
        if vim.api.nvim_win_get_buf(win) == buf then
          vim.api.nvim_win_close(win, true)
          return
        end
      end
    end
  end
  vim.cmd("vsplit | terminal arkad-agent")
end

function M.setup()
  vim.keymap.set("v", "<leader>aa", M.ask_selection, { desc = "Arkad: ask about selection" })
  vim.keymap.set("n", "<leader>ad", M.ask_diagnostics, { desc = "Arkad: ask about diagnostics" })
  vim.keymap.set("n", "<leader>at", M.toggle_terminal, { desc = "Arkad: toggle terminal" })
end

return M
