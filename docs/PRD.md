# AURA Product Requirements

Status: draft, written from the code on branch `settings-agent-direct-apis`. Items under "Open questions" are not settled by the code or history.

## Problem

Language-model assistants can reason but cannot act on a Windows PC. Operating the desktop by screenshots and mouse clicks is slow and unreliable, and it tells the caller nothing about whether the action worked. AURA gives an MCP client (such as Claude Desktop) a small set of named, parameterised actions per application, implemented with the most direct reliable mechanism available (Windows APIs, UI Automation patterns, Playwright), and reports the real result of each action.

## Target users

- Windows users who want to drive apps and settings from Claude Desktop or another MCP client in natural language.
- The project team (see `docs/TIMELINE.md`) extending AURA with new agents.
- Developers who want an LLM planner behind an HTTP endpoint (the Flask API).

## Goals

1. Expose each application as an agent with a uniform contract (`BaseAgent`) that is auto-discovered.
2. Prefer direct APIs over UI clicking where Windows offers one; otherwise use UI Automation patterns.
3. Read back state after changes and report failures truthfully instead of assuming success.
4. Keep new agents independent of the core: adding one means adding one file.
5. Work with MCP clients over stdio.

## Non-goals

- Cross-platform support (Windows only).
- Controlling arbitrary applications out of the box; only agents that exist are supported.
- Vision/OCR fallback in the current scope (the resolver's Tier 3 is a stub that does nothing).
- Long-term memory or personalisation.

## Functional requirements

### Platform
- MCP stdio server with tools to list agents, read an agent's capabilities, execute an action with JSON parameters, and list open windows. It also registers 2 resources (`aura://system/health`, `aura://ui/windows`) and 1 prompt.
- Flask endpoint `POST /api/execute` that turns a prompt into a JSON plan with an LLM and runs it step by step, stopping at the first failure.
- Agents return `{"status": "success"|"failure", "action", "details", "duration_ms"}`.

### Notepad agent
Open (or find) Notepad, new file, clear text, type, select all, copy, paste, save, save as (including the Save As dialog and overwrite prompt), close. Verify window exists / text contains.

### Browser agent
Create a support service request on the MyUPES portal: log in, reuse a saved session, choose department / category / subcategory in dynamic dropdowns, fill the short description and description, submit. Credentials come from the environment.

### Settings agent
35 actions in these groups:
- Radios: get / set / restart Bluetooth and Wi-Fi, find a Bluetooth device, list Wi-Fi networks, connect to a saved network, airplane mode.
- Network troubleshooting: diagnose network, flush DNS.
- Sound: get volume, set volume, mute.
- Display: brightness, theme, inspect displays, preview a refresh rate (nominal or exact). Preview only; nothing is applied.
- Power and system: battery, power plans, set power plan, storage status, system info, check for updates.
- Settings app: open, navigate to a page by name or `ms-settings:` URI, read page, get / set toggle, select option, click button.

## Non-functional requirements

- Reliability: a failed or denied action returns `status: failure` with the real reason. Calls must not deadlock inside MCP worker threads (see COM handling in `docs/ARCHITECTURE.md`).
- Verification after action: settings changes are read back and compared with the requested value before success is reported. The browser agent's `verify()` always returns true, so it does not meet this requirement.
- Safety / confirmation gate: actions that are hard to undo must require explicit confirmation. Today only the settings `click` action enforces this (irreversible-button guard, `confirm=true`). Notepad `save`, `save_as` and `close` are tagged `needs_confirmation` in metadata but not enforced anywhere. A shared gate is a requirement that is not yet met.
- Secrets: credentials only from the environment or `.env`; never logged or committed.
- Platform: Windows 11 for the settings agent.

## Success metrics

The repo does not define any. Proposed, for the team to agree:
- Every settings action exercised on a live machine at least once (the untested list in `docs/TASKS.md` is open).
- Zero irreversible actions executed without the confirmation flag.
- Offline test suite passes (`python -m pytest tests`; 4 tests today).
- An end-to-end MCP call from Claude Desktop verified for each agent.

## Open questions

- Is the Flask API still wanted now that the frontend directory was removed (commit "Remove frontend directory")? It still imports and runs.
- Is Groq the intended long-term LLM, or will the planned local LLM replace it? `groq` is imported but not in `requirements.txt`.
- Should the confirmation gate live in the MCP server (all agents) or per agent?
- Should `app_maps/settings.json`, which the settings agent no longer reads, be deleted?
- Which Python and Windows versions are supported?
- Is the MyUPES portal agent a core feature or a team-specific demo? Portal expansion (attendance, schedule, notices) is on the roadmap.
