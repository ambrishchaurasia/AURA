# AURA (Automated Universal Robotic Agent)

Lightweight, extensible desktop and web automation framework for Windows powered by **MCP (Model Context Protocol)** and LLMs.

---

## ✅ Completed (`[x]`)

### 🎫 Browser Automation (Ticket Creation)
- [x] Automated login & session handling for university student portal
- [x] Portal navigation (dashboard, service requests)
- [x] Dynamic Kendo UI dropdown interaction (Department, Category, Subcategory)
- [x] Form fill (short description, body) & end-to-end ticket submission
- [x] Playwright DOM automation with resilient selector engine

### 📝 Notepad Automation
- [x] Launch, connect, and focus instances (Windows 11 Modern & Classic Notepad)
- [x] Type and append text directly
- [x] Read editor content & clear editor
- [x] Automated "Save As" flow (handles file naming, path, and keyboard shortcuts)
- [x] Overwrite confirmation dialog handling

### ⚙️ Windows & System Control
- [x] Enumerate all active top-level Windows apps & process IDs (PIDs)
- [x] Window focus, bring-to-front, minimize, maximize, and restore
- [x] Windows 11 Settings navigation (Display, Bluetooth, Sound, Network, Power)

### 🔌 MCP (Model Context Protocol) Integration
- [x] Stdio MCP server for Claude Desktop & MCP clients
- [x] Tool: `aura_list_windows`
- [x] Tool: `aura_list_agents`
- [x] Tool: `aura_get_agent_info`
- [x] Tool: `aura_execute_action`
- [x] Multithreaded Apartment (MTA) COM fix (`sys.coinit_flags = 0`) preventing async thread deadlocks on Windows

### 🧱 Architecture
- [x] Core automation logic decoupled from presentation layer
- [x] Removed legacy web frontend to focus on headless MCP & local AI orchestration
- [x] Lightweight fallback REST API (`automation.api`)

---

## 📋 To-Do / Roadmap (`[ ]`)

- [ ] **Local LLM Orchestrator**: Direct local LLM control (Ollama / GGUF) without cloud API dependency
- [ ] **Self-Healing Selectors**: Vision / OCR fallback when UI elements shift or update
- [ ] **Additional Desktop Agents**:
  - [ ] File Explorer agent (file move, copy, search)
  - [ ] Calculator / basic utility agents
  - [ ] Terminal / PowerShell automation agent
- [ ] **Multi-Step Goal Planner**: Complex task decomposition directly inside the local agent loop

---

## ⚡ Quick Start (Claude Desktop MCP)

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
