# AURA Developer Guide: Building New Agents

Welcome to the AURA project! AURA uses a highly modular **Plugin Architecture**. This means you can build your assigned agent (e.g., File Explorer, Settings, Word) entirely independently. 

You **never** need to edit the core engine, the `api.py`, or the `LLMOrchestrator`. As long as you follow this blueprint, AURA will automatically discover your agent and start using it!

## The 3-Step Blueprint

### Step 1: Create Your App Map
*Location: `app_maps/<your_app>.json`*

Before you write any Python, you need to map out the UI elements of your application so AURA knows how to click them.
1. Create a new JSON file (e.g., `app_maps/file_explorer.json`).
2. Define the tree of UI elements (e.g., search bar, address bar) using `name` and `automation_id`.
3. *(Tip: Use the `automation/builder/crawler.py` script to help automatically map out the UI tree of your app!)*

### Step 2: Create Your Agent Class
*Location: `automation/agents/<your_app>_agent.py`*

1. Create a new Python file in the `agents` folder (it **must** end in `_agent.py` for the registry to find it).
2. Inherit from `BaseAgent`.
3. Implement the required abstract methods.

**Boilerplate Example:**
```python
from automation.core.base_agent import BaseAgent
from automation.core import window_manager, input_handler

class FileExplorerAgent(BaseAgent):
    def __init__(self):
        from automation.core.app_map import load_app_map
        from automation.core.resolver import TieredResolver
        self.app_map = load_app_map("file_explorer") # Matches your JSON name
        self.resolver = TieredResolver(self.app_map)

    def get_agent_name(self) -> str:
        # The unique ID the LLM uses to call you
        return "explorer" 

    def get_llm_capabilities(self) -> str:
        # VERY IMPORTANT: This tells the LLM what you can do.
        return """
Agent `explorer` supports:
- `open`: Opens File Explorer (No params).
- `navigate`: Goes to a path. Params: `{"path": "<string>"}`.
"""

    def get_window(self):
        return window_manager.find_window(class_name="CabinetWClass")

    def resolve(self, intent: str, **kwargs) -> dict:
        pass # Optional: implement if you need complex UI resolving
        
    def execute(self, action: str, params: dict) -> dict:
        # Route actions to your private methods
        if action == "open":
            return self._action_open()
        elif action == "navigate":
            return self._action_navigate(params.get("path"))
        return {"status": "failure", "details": f"Unknown action: {action}"}
```

### Step 3: Implement Your Actions
Write the private methods (e.g., `_action_open`) using the tools in `automation/core/`:
- Use `input_handler` to press keys or type (`Ctrl+L` is great for focusing address bars!).
- Use `window_manager` to focus your app before doing anything.

### That's it!
Once your `_agent.py` file is saved, **restart the backend API**. AURA's `AgentRegistry` will automatically detect your code, and the LLM will instantly know how to route user requests to you.

---

> [!CAUTION]
> **Safety Warning:** If you are building an agent capable of destructive actions (e.g., deleting files, sending emails), please consult the lead architect before implementing them. All destructive actions must eventually pass through a User Confirmation Gate!
