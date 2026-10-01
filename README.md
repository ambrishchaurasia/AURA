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

### MCP Integration
- [x] Stdio MCP server exposing 4 tools (`aura_list_windows`, `aura_list_agents`, `aura_get_agent_info`, `aura_execute_action`)
- [x] Thread-safe Windows COM (MTA) initialization to prevent async worker deadlocks

---

## Roadmap

- [ ] Local LLM orchestrator (offline execution via Ollama/GGUF without cloud APIs)
- [ ] Additional agents for File Explorer and PowerShell
- [ ] Vision/OCR fallback for self-healing UI selectors

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
