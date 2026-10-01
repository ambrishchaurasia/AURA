# AURA

AURA is a Windows desktop and browser automation engine. It exposes per-application agents to MCP clients such as Claude Desktop, and also contains an LLM planner (Groq-hosted model) behind a small Flask API. Each application is handled by one agent class; new agents are picked up automatically, so applications can be added without touching the core. The goal is to let a language model operate Windows apps and settings through a small, verifiable set of named actions instead of raw clicking.

## Agents

| Agent | Name used in calls | What it does |
|---|---|---|
| Notepad | `notepad` | Open, new file, clear, type, select all, copy, paste, save, save as, close. UI Automation plus keyboard input, Windows 11 and classic Notepad. |
| Browser | `browser` | One action, `create_service_request`: logs in to the MyUPES portal with Playwright, fills the service-request form (department, category, subcategory, descriptions) and submits it. Saves the login session to skip the CAPTCHA on later runs. |
| Settings | `settings` | 35 actions for Windows 11 settings. Calls Windows APIs directly and reads the state back after each change: Bluetooth and Wi-Fi (WinRT radios), volume and mute (Core Audio), brightness (WMI), dark/light theme (registry), power plans (powercfg), Wi-Fi networks and DNS (netsh), displays. Also opens any Settings page by name or `ms-settings:` URI, and operates named toggles, dropdowns and buttons on the open page. See `docs/ARCHITECTURE.md`. |

The MCP server also exposes a window lister (`aura_list_windows`) for top-level windows.

## Architecture

```
MCP client (Claude Desktop)                 HTTP client
        |  stdio                                 |  POST /api/execute
        v                                        v
automation/mcp/server.py                   automation/api.py
 4 tools                                     LLMOrchestrator (Groq) -> JSON plan
        \                                       /
         v                                     v
              automation/core/registry.py   (auto-discovers *_agent.py)
                          |
          +---------------+----------------+
          v               v                v
    notepad_agent    browser_agent    settings_agent
    (UIA + keys)     (Playwright)     (Windows APIs + UIA)
```

Every agent subclasses `automation/core/base_agent.py`. The registry imports each `automation/agents/*_agent.py`, instantiates the `BaseAgent` subclasses it finds, and keys them by `get_agent_name()`. Details are in `docs/ARCHITECTURE.md`.

## Repository layout

```
automation/
  agents/            notepad_agent.py, browser_agent.py, settings_agent.py
    settings_ops/    radios, system, ui, displays, display_config, display_modes
  core/              base_agent, registry, llm_orchestrator, planner (rule-based),
                     window_manager, element_finder, input_handler, verifier,
                     resolver, app_map, logger
  mcp/               MCP server (server.py), CLI (cli.py), `python -m automation.mcp`
  builder/           crawlers that generate app maps / portal categories
  api.py             Flask API
  main.py            Notepad-only CLI using the rule-based planner
  requirements.txt
app_maps/            UI maps (notepad.json, browser.json, settings.json) and developer_guide.md
tests/               offline pytest tests for the settings agent
docs/                PRD, architecture, tasks, timeline
mcp_wrapper.py       MCP entry script with a thread-dump debug hook
run_mcp.bat          Windows launcher (paths are hardcoded, edit before use)
```

## Prerequisites

- Windows 10/11 (the agents use UI Automation, WinRT, Core Audio, WMI; the settings agent targets Windows 11).
- Python 3 with `venv`. The exact supported version is not recorded in the repo.
- For the browser agent: Playwright and its Chromium browser. These are imported by `browser_agent.py` but are not listed in `automation/requirements.txt`.
- For the Flask API: the `groq` package (also not in `requirements.txt`) and a `GROQ_API_KEY`.

## Install

```powershell
cd <path-to-repo>
python -m venv automation\venv
automation\venv\Scripts\activate
pip install -r automation\requirements.txt
# only if you use the browser agent / the Flask API:
pip install playwright groq
playwright install chromium
```

Configuration is read from environment variables or a `.env` file (never commit it):

- `GROQ_API_KEY` for `LLMOrchestrator` / the Flask API.
- `MYUPES_USERNAME`, `MYUPES_PASSWORD` for the browser agent.

The MCP server and the settings and notepad agents need none of these.

## Run the MCP server

From the repo root, with the venv active:

```powershell
python -m automation.mcp                  # stdio (default)
python -m automation.mcp --list-tools
python -m automation.mcp --generate-configs
```

Tools: `aura_list_agents`, `aura_get_agent_info`, `aura_execute_action(agent_name, action_name, params_json)`, `aura_list_windows`. `run_mcp.bat` does the same but contains hardcoded paths; edit them first.

### Claude Desktop

Add to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aura": {
      "command": "<path-to-repo>\automation\venv\Scripts\python.exe",
      "args": ["-m", "automation.mcp"],
      "env": { "PYTHONPATH": "<path-to-repo>" }
    }
  }
}
```

The previous README used `mcp_wrapper.py` as the entry script instead. It runs the same server and additionally prints a thread dump to stderr after 3 seconds. This config has not been re-tested on this branch.

## Run the Flask API

```powershell
python -m automation.api     # http://127.0.0.1:5000
```

`POST /api/execute` with `{"prompt": "..."}`. The LLM returns a JSON plan, the API runs the steps in order through the registry and stops at the first failure. Without `GROQ_API_KEY` it starts but returns an error for every request.

## Tests

```powershell
python -m pytest tests
```

The 4 tests cover the settings agent and run offline (the Windows radio API is faked). They do not touch a real Settings window.

## Adding an agent

Create `automation/agents/<name>_agent.py` containing a `BaseAgent` subclass; restart the process and the registry loads it. See `app_maps/developer_guide.md` for the blueprint. Note that guide describes the app-map approach; the settings agent no longer uses one.

## Safety notes

- Actions run with the permissions of the user who started the server and operate on the live desktop.
- The confirmation gate is only partly implemented. Agents tag actions with a `safety` value in `get_capabilities()`, but nothing in the MCP server or API enforces it. The one enforced guard is in the settings agent: `click` refuses buttons whose name looks irreversible (reset, remove, uninstall, ...) unless called with `confirm=true`.
- The settings agent reports real failures in `details` and reads state back after changes. Several actions are not yet tested against a live system; see `docs/TASKS.md`.
- Credentials live in `.env`, which is git-ignored. The browser agent stores a login session at `automation/myupes_session.json`; that path is not in `.gitignore`, so do not commit it.

## Documentation

- `docs/PRD.md` product requirements
- `docs/ARCHITECTURE.md` components and request flow
- `docs/TASKS.md` done / in progress / todo
- `docs/TIMELINE.md` milestones and phases
- `app_maps/developer_guide.md` how to write an agent
