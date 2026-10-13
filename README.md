# AURA

Windows desktop and browser automation engine designed for MCP clients (Claude Desktop) and local LLMs.

## Features

### Browser & Ticket Automation
- [x] Portal login and dashboard navigation via Playwright
- [x] Automated support ticket creation with dynamic dropdown handling and form submission
- [x] Web search and opening a site in the default browser (`search`, `open_url`)
- [x] Answering a question from web search results (`answer_question`)

### Notepad Automation
- [x] Launch, focus, and direct text input/editing (Win 11 & Classic)
- [x] File saving workflow with Save-As dialog and overwrite prompt handling

### Windows & System Control
- [x] Top-level window enumeration, focus, and state control (minimize/maximize)
- [x] Windows Settings navigation across core system panels
- [x] Settings control via Windows APIs, each change read back: Bluetooth / Wi-Fi on, off, restart; volume, mute, brightness (set, or turned up / down from the current level), dark mode, power plans, battery, storage, display inspection
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

## Small local model client

`python -m automation.mcp.slm_client "open notepad and type hello"` starts the MCP server over stdio and drives it with a small local model. AURA runs the model itself with a bundled llama.cpp server, started hidden on first use and stopped when AURA exits; nothing else needs to be installed or kept running. The model only answers schema-constrained questions (split the request into steps, pick one action per step, fill in its parameter values), so it cannot produce a malformed tool call. Actions not marked `safe` ask for a `y` first.

| Variable | Purpose |
| --- | --- |
| `AURA_SLM_URL` | Use an OpenAI-compatible server you run yourself instead of the bundled llama.cpp, e.g. `http://127.0.0.1:11434/v1` for Ollama. Default: unset. |
| `AURA_SLM_MODEL` | Model to use (or pass `--model`). Default: `aura-qwen-0.5b`, the 0.5 GB model fine-tuned for AURA. `install.bat 1.5b` adds `aura-qwen-1.5b` and `install.bat llama` adds the stock `llama3.2-3b`. A path to any GGUF file also works. |
| `AURA_REPLY_MODEL` | Model that writes sentences (web answers, spoken replies). Default: same as `AURA_SLM_MODEL`. |

`python -m automation.mcp.slm_eval [model ...]` scores models on fixed commands without touching the desktop.

### Voice

`install.bat` sets everything up once (Python environment, the llama.cpp runtime, the default model from [Somansh1/aura-models](https://github.com/Somansh1/aura-models), the voice). Then:

- `.venv\Scripts\pythonw.exe -m automation.mcp.tray` runs AURA in the system tray; the menu pauses listening or quits. `python -m automation.mcp.tray --startup on` makes it start with Windows (`off` removes it).
- `python -m automation.mcp.voice` runs the same loop in a terminal; `--push-to-talk` uses Enter instead of the wake phrase.

Say "hey aura, turn bluetooth off" (or "hey aura", wait for the chime, then the command). When AURA hears its name it plays a soft chord, glows around the screen edge and shows what it heard in a caption at the top of the screen. It speaks the outcome with a local neural voice (Kokoro), and asks "say yes or no" before any action not marked `safe`. Speech is transcribed locally with Whisper (`faster-whisper`).

| Variable | Purpose |
| --- | --- |
| `AURA_WHISPER_MODEL` | Whisper model size. Default: `base.en`. |
| `AURA_WHISPER_DEVICE` | `cpu` (default) or `cuda` (needs the cuBLAS/cuDNN DLLs). |
| `AURA_MIC_THRESHOLD` | Fixed loudness (0-1) that counts as speech. Default: follows the room noise. |
| `AURA_VOICE` | Kokoro voice name. Default: `af_heart`. |

### Fine-tuning a smaller model

`automation/mcp/finetune/` trains a small model on exactly the questions the client asks:

1. `python -m automation.mcp.finetune.make_dataset train.jsonl val.jsonl` generates the data from `commands.py` (phrasings for every action), `replies.py` (agent results as spoken sentences) and the live agent capabilities. `squad_answers.py` adds answer-from-web-text examples built from SQuAD 2.0.
2. `train.py` (LoRA, one GPU; needs `torch`, `transformers`, `peft`) fine-tunes a base model and saves it merged; `train.pbs` runs it for Qwen2.5 0.5B and 1.5B on a PBS cluster and converts both to GGUF with llama.cpp.
3. Put the GGUF in `%LOCALAPPDATA%\AURA\models` and score it with `python -m automation.mcp.slm_eval aura-qwen-0.5b` (the name is the start of the file name). `Modelfile` is only for loading it into Ollama.

When an agent gains or renames an action, add its phrasings to `commands.py` (and its result format to `replies.py`) and retrain. The base models are Qwen2.5 Instruct (Apache-2.0).

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
