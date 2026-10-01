# AURA Tasks

## Done

Platform
- [x] Plugin architecture: `BaseAgent` contract and auto-discovering registry
- [x] MCP stdio server with 4 tools, 2 resources, 1 prompt
- [x] MTA COM initialisation to avoid worker-thread deadlocks
- [x] Flask API and Groq-based LLM orchestrator
- [x] Rule-based planner and Notepad CLI (`automation/main.py`)
- [x] UI crawlers for app maps and portal categories

Notepad agent
- [x] Open, new file, clear, type, select all, copy, paste, save, save as (with dialog and overwrite handling), close

Browser agent
- [x] MyUPES login with saved session, service-request creation with dynamic dropdowns

Settings agent (branch `settings-agent-direct-apis`)
- [x] Rewrite on direct Windows APIs with read-back (35 actions)
- [x] Tested live: Bluetooth on/off, a Settings toggle, all read actions, irreversible-button guard
- [x] 4 offline pytest tests

## In progress

- [ ] Review and merge of `settings-agent-direct-apis`

## Todo

Settings agent: live testing
- [ ] Wi-Fi off / restart
- [ ] Airplane mode
- [ ] `connect_wifi`
- [ ] `flush_dns`
- [ ] `set_power_plan`
- [ ] `select_option`
- [ ] `check_updates`
- [ ] MCP server end to end (Claude Desktop calling the settings agent)

Settings agent: known limits
- [ ] Brightness works only on built-in panels
- [ ] `list_wifi_networks` needs Windows Location services on
- [ ] Listing all Bluetooth devices takes about 30 seconds
- [ ] Refresh-rate actions are preview only; no apply
- [ ] No default audio device switching
- [ ] `read_page` output includes the left navigation items
- [ ] Remove or archive `app_maps/settings.json` (no longer read)

Platform
- [ ] Shared confirmation gate for irreversible actions (today only settings `click` enforces one; Notepad `save`/`save_as`/`close` are metadata only)
- [ ] Add `groq`, `playwright` and `playwright-stealth` (optional import) to dependencies, or document them
- [ ] Remove hardcoded `E:\mycodes\AURA` paths from `run_mcp.bat`
- [ ] Tests for the Notepad and browser agents
- [ ] Decide the future of the Flask API after the frontend removal
- [ ] Add `automation/myupes_session.json` to `.gitignore`
- [ ] Remove stray files from the repo root (`windows.txt`, `debug_windows.txt`, `@AutomationLog.txt`) if they are not needed
- [ ] Unify the two registries (`agents/__init__.py` `AGENT_REGISTRY` vs `core/registry.py`)

Roadmap (from the previous README)
- [ ] Local LLM integration (offline inference without cloud APIs)
- [ ] Expand portal capabilities (attendance, schedule, notices)
- [ ] File Explorer agent (navigation, file management, search)
