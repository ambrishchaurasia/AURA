# AURA (Automated Universal Robotic Agent)

AURA is a lightweight, extensible desktop and web automation framework for Windows. It enables AI agents (via the **Model Context Protocol (MCP)**, REST APIs, or local LLMs) to inspect windows, interact with native desktop applications, and automate complex browser workflows.

---

## 🚀 Key Achievements & Features

### 1. 🎫 Browser & Portal Automation (Ticket Creation)
- **Portal Login & Navigation**: Automatically logs in and navigates the university student portal.
- **Automated Service Requests / Ticket Creation**:
  - Automatically clicks and opens the "Create Request" workflow.
  - Interacts with dynamic Kendo UI dropdowns: selects **Department**, **Category**, and **Subcategory**.
  - Populates short description, detailed description, and submits support tickets end-to-end.
- **Playwright DOM Engine**: Uses headless/headful browser automation with resilient CSS and text-based element selectors.

---

### 2. 📝 Desktop Notepad Automation
- **App Lifecycle**: Launch, focus, or connect to existing instances of both modern Windows 11 Notepad and classic Notepad.
- **Text Operations**:
  - Direct typing and text appending without clipboard pollution.
  - Content reading and verification.
  - Editor clearing.
- **File Management & Dialog Handling**:
  - Automated "Save As" flow (handles file naming, target directory, and keyboard shortcuts).
  - Handles confirmation dialogs (e.g. overwrite warnings).

---

### 3. ⚙️ Windows Settings & System Agents
- **Settings Agent**: Navigates Windows 11 Settings pages (Display, Bluetooth & devices, Sound, Network, Power & battery).
- **Window Management**:
  - Enumerates all active top-level Windows applications and PIDs.
  - Focuses, brings to front, maximizes, minimizes, and restores target application windows.

---

### 4. 🔌 Model Context Protocol (MCP) Integration
- **Claude Desktop & MCP Client Support**: Direct stdio-based MCP protocol server allowing Claude Desktop and any MCP client to trigger system actions.
- **Exposed MCP Tools**:
  - `aura_list_windows`: Returns currently active desktop windows.
  - `aura_list_agents`: Returns available registered automation agents (`notepad`, `browser`, `settings`).
  - `aura_get_agent_info`: Inspects supported actions and schemas for a specific agent.
  - `aura_execute_action`: Invokes an action with JSON arguments (e.g., writing a poem in Notepad and saving it).
- **Windows COM Multithreading Fix**:
  - Solved the AnyIO worker thread deadlock under Windows by enforcing Multithreaded Apartment (MTA) mode (`sys.coinit_flags = 0`).
  - Ensures smooth, non-blocking UI automation calls from asynchronous MCP handlers.

---

### 5. 🧱 Architecture & Streamlining
- **Decoupled Architecture**: Automation agents (`automation.agents.*`) and core resolvers are decoupled from UI or transport protocols.
- **Frontend Deprecation**: Removed the legacy web frontend to focus purely on headless MCP and local AI orchestrators.
- **Dual Transport Option**:
  - **MCP Stdio Server**: Preferred for AI assistants (Claude Desktop, etc.).
  - **REST API (`automation.api`)**: Optional Flask service for HTTP/REST integrations.

---

## 📂 Project Structure

```
AURA/
├── app_maps/                 # UI Maps defining element selectors and paths
│   ├── browser.json          # Portal & ticket creation UI mapping
│   ├── notepad.json          # Notepad controls mapping
│   └── settings.json         # Windows Settings mapping
├── automation/
│   ├── agents/               # Application-specific agent logic
│   │   ├── browser_agent.py  # Web & ticket creation agent
│   │   ├── notepad_agent.py  # Notepad editor & save agent
│   │   └── settings_agent.py # Windows Settings agent
│   ├── core/                 # Core engine & utilities
│   │   ├── base_agent.py     # Base agent interface
│   │   ├── window_manager.py # Window listing & focus control
│   │   ├── resolver.py       # Element lookup & actions
│   │   └── llm_orchestrator.py
│   ├── mcp/                  # Model Context Protocol implementation
│   │   ├── server.py         # MCP server instance & tool definitions
│   │   └── cli.py            # CLI entrypoint
│   ├── api.py                # Optional Flask REST server
│   └── main.py               # Main CLI executor
├── mcp_wrapper.py            # Clean stdio wrapper for Claude Desktop
├── run_mcp.bat               # Batch launcher for MCP
└── README.md
```

---

## 🛠️ Setup & Usage

### 1. Prerequisites
- Windows 10/11
- Python 3.10+
- Virtual environment with dependencies installed:
  ```powershell
  cd automation
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  pip install -r requirements.txt
  ```

---

### 2. Running the MCP Server for Claude Desktop

Add AURA to your Claude Desktop configuration file:
`%APPDATA%\Claude\claude_desktop_config.json`:

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

Restart Claude Desktop, and you will see the 4 AURA tools available.

---

### 3. Running the REST API (Optional)

If you want to trigger actions over HTTP:
```powershell
.\automation\venv\Scripts\python.exe -m automation.api
```
Server runs on `http://127.0.0.1:5000`.

---

## 🔮 Roadmap / Next Steps
- [ ] **Local LLM Orchestrator**: Direct local model execution (Ollama / GGUF / transformers) without cloud API dependencies.
- [ ] **Expanded Desktop Maps**: Extend app maps for VS Code, File Explorer, and Office tools.
- [ ] **Self-Healing Selectors**: Automatic selector fallbacks using vision/OCR when UI layout changes.
