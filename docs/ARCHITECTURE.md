# AURA Architecture

## Components

| Component | Path | Role |
|---|---|---|
| Agents | `automation/agents/*_agent.py` | One class per application, subclass of `BaseAgent`. |
| Settings operations | `automation/agents/settings_ops/` | Windows API code used by the settings agent. |
| Registry | `automation/core/registry.py` | Discovers and instantiates agents; module-level singleton `registry`. |
| BaseAgent | `automation/core/base_agent.py` | Abstract contract. |
| MCP server | `automation/mcp/server.py`, `cli.py`, `__main__.py` | `MCPServer("AURA")` over stdio (`--transport http` runs SSE). |
| Flask API | `automation/api.py` | `POST /api/execute`, port 5000. |
| LLM orchestrator | `automation/core/llm_orchestrator.py` | Builds a system prompt from every agent's `get_llm_capabilities()`, calls Groq model `openai/gpt-oss-120b`, parses a JSON plan. Retries up to 4 times on 429/503. |
| UI helpers | `window_manager`, `element_finder`, `input_handler`, `verifier`, `resolver`, `app_map` in `automation/core/` | pywinauto-based helpers used by the Notepad agent. |
| Rule-based planner | `automation/core/planner.py`, used by `automation/main.py` | Regex planner for Notepad-only CLI runs. |
| Builders | `automation/builder/` | Crawlers for UI trees and portal categories. |
| App maps | `app_maps/*.json` | UI element maps loaded by `core/app_map.py`. |

## Request flow: MCP tool call to action

1. The client (Claude Desktop) starts `python -m automation.mcp`. `server.py` sets `sys.coinit_flags = 0` (MTA) before UI libraries load, imports the registry (which loads all agents), and `mcp.run()` serves stdio.
2. The client calls `aura_list_agents` and `aura_get_agent_info(agent_name)`; the latter returns the agent's `get_capabilities()` as JSON.
3. The client calls `aura_execute_action(agent_name, action_name, params_json)`.
4. The tool calls `pythoncom.CoInitializeEx(COINIT_MULTITHREADED)` on the worker thread, looks up the agent with `registry.get_agent`, parses `params_json`, calls `agent.execute(action, params)`, serialises the result, and calls `CoUninitialize()` in `finally`.
5. The agent returns `{"status", "action", "details", "data"?, "duration_ms"}`. An exception comes back as an `Error ...` string.

Flask path: `/api/execute` -> `LLMOrchestrator.plan(prompt)` -> list of `{agent, action, params}` -> the same `registry.get_agent(...).execute(...)` per step, stopping on the first `failure`.

`aura_execute_action` has no confirmation step; `safety` metadata in `get_capabilities()` is advisory.

## BaseAgent contract

Abstract members an agent must implement:
- properties `app_name`, `process_name`
- `get_agent_name()`: the lowercase key used in calls
- `get_llm_capabilities()`: text injected into the LLM prompt
- `get_capabilities()`: `{"application", "actions": {name: {description, parameters, safety}}}`
- `resolve(intent, **kwargs)`
- `execute(action, params)`: returns the result dict above
- `verify(expected_state)`: returns `{"verified", "expected", "actual", "details"}`

Optional: `get_window()`, `is_running()`.

## Registry discovery

On import, `AgentRegistry` lists `automation/agents/`, imports every file ending `_agent.py`, and instantiates every `BaseAgent` subclass found in the module (via `inspect.getmembers`, so a `BaseAgent` subclass merely imported into an agent file would also be instantiated). Results are keyed by `get_agent_name()`; `get_agent` lowercases its argument. A load failure is printed to stderr and skipped, so a broken agent silently disappears from `aura_list_agents`. The registry is built at import time, so a new agent needs a process restart.

Separate and older: `automation/agents/__init__.py` has its own `AGENT_REGISTRY` containing only Notepad, used by `automation/main.py`.

## Settings agent: three layers

Defined by the `ACTIONS` table in `settings_agent.py` (action -> handler, description, parameters, safety). `execute` looks up the handler, converts `ActionError` into a failure carrying its message, and any other exception into `ExceptionType: message`.

1. Direct Windows APIs (`settings_ops/radios.py`, `system.py`, `displays.py`):
   - Bluetooth / Wi-Fi: WinRT `Radio` API; state is re-read after setting.
   - Volume / mute: Core Audio endpoint volume via ctypes COM calls.
   - Brightness: WMI (built-in panels only). Theme: registry. Power plans: `powercfg`. Wi-Fi networks, connect, DNS: `netsh`.
   - Displays: Windows display configuration and mode APIs via ctypes (`display_config.py`, `display_modes.py`). Refresh-rate actions only preview.
2. `ms-settings:` URIs: `ui.PAGES` maps page names to URIs. `resolve_page` accepts a name, a close misspelling (difflib) or a raw URI. `ui.open_page` launches the page and waits for the Settings window.
3. Named-control access (`settings_ops/ui.py`, `uiautomation` package): finds a toggle, dropdown or button by name on the open page and drives it through UIA patterns (Toggle, Invoke, SelectionItem, ExpandCollapse) without moving the mouse, then polls until the new state is visible. `click` refuses names matching `ui.RISKY` unless `confirm=true`.

`app_maps/settings.json` is no longer read by this agent.

## Threading and COM notes

- `server.py` sets `sys.coinit_flags = 0` so pywinauto/comtypes initialise as MTA, to avoid deadlocks in async worker threads.
- Each MCP tool call initialises and uninitialises COM on its own worker thread.
- `radios._run` runs the asyncio WinRT call in a fresh single-thread `ThreadPoolExecutor`, because the caller may already be inside an event loop.
- `system.set_volume` runs in its own thread so its COM apartment does not clash with the caller's (UI Automation, MCP worker).
- `mcp_wrapper.py` adds `faulthandler` and a thread dump to stderr after 3 seconds, for debugging hangs.

## Not covered

The Notepad resolution tiers (`resolver.py`: app map, live UIA search, Tier 3 stub) and the browser agent's Playwright flow were read at summary level only.
