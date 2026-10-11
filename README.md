# AURA

Windows desktop and browser automation engine designed for MCP clients (Claude Desktop) and local LLMs.

## Features

### Browser & Ticket Automation
- [x] Portal login and dashboard navigation via Playwright
- [x] Automated support ticket creation with dynamic dropdown handling and form submission

### Notepad Automation
- [x] Launch, focus, and direct text input/editing (Win 11 & Classic)
- [x] File saving workflow with Save-As dialog and overwrite prompt handling

### Windows & System Control
- [x] Top-level window enumeration, focus, and state control (minimize/maximize)
- [x] Windows Settings navigation across core system panels
- [x] Settings control via Windows APIs, each change read back: Bluetooth / Wi-Fi on, off, restart; volume, mute, brightness, dark mode, power plans, battery, storage, display inspection
- [x] Settings troubleshooting: network diagnosis, DNS flush, radio restart, Bluetooth device presence, Windows Update check
- [x] Any other Settings toggle / dropdown / button by name (`read_page`, `set_toggle`, `select_option`, `click`)

### MCP Integration
- [x] Stdio MCP server exposing 4 tools (`aura_list_windows`, `aura_list_agents`, `aura_get_agent_info`, `aura_execute_action`)
- [x] Thread-safe Windows COM (MTA) initialization to prevent async worker deadlocks

---

## Roadmap

- [ ] Local LLM integration (offline inference without cloud APIs)
- [ ] Expand portal capabilities (attendance, schedule, notices)
- [ ] File Explorer agent (navigation, file management, search)

---

## HTTP API

`python -m automation.api` serves `POST /api/execute` on `http://127.0.0.1:5000`. It drives the desktop, so it is locked down by default:

| Variable | Purpose |
| --- | --- |
| `AURA_API_TOKEN` | Shared secret every request must send in the `X-AURA-Token` header (401 otherwise). If unset, a random token is generated and printed at startup. |
| `AURA_ALLOWED_ORIGINS` | Comma-separated front-end origins allowed by CORS, e.g. `http://localhost:5173`. Default: none (same-origin only). |

Flask debug mode is off unless `AURA_DEBUG=1`.

---

## Claude Desktop Setup

Add to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aura": {
      "command": "E:\\mycodes\\AURA\\automation\\venv\\Scripts\\python.exe",
      "args": [
        "E:\\mycodes\\AURA\\mcp_wrapper.py"
      ]
    }
  }
}
```
