import json
import sys
sys.coinit_flags = 0  # Force pywinauto to use MTA (Multithreaded Apartment) to prevent deadlocks in async worker threads!
import uiautomation as auto
from mcp.server.mcpserver import MCPServer
from automation.core.registry import registry

# Create the MCP Server instance
from mcp.server.mcpserver import MCPServer
mcp = MCPServer("AURA")

# ---------------------------------------------------------------------------
# 1. TOOLS
# ---------------------------------------------------------------------------

@mcp.tool()
def aura_list_agents() -> str:
    """Lists all available AURA desktop agents (e.g. browser, settings, notepad)."""
    agents = list(registry.get_all_agents().keys())
    return json.dumps({"agents": agents})

@mcp.tool()
def aura_get_agent_info(agent_name: str) -> str:
    """Gets the capabilities and supported actions for a specific agent."""
    agent = registry.get_agent(agent_name)
    if not agent:
        return f"Agent {agent_name} not found."
    return json.dumps(agent.get_capabilities(), indent=2)

@mcp.tool()
def aura_execute_action(agent_name: str, action_name: str, params_json: str) -> str:
    """Executes a low-level action on a specific AURA agent. 
    Use this to click buttons, type text, or navigate the UI.
    params_json must be valid JSON representing the arguments dictionary.
    """
    import pythoncom
    pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
    
    agent = registry.get_agent(agent_name)
    if not agent:
        return f"Error: Agent {agent_name} not found."
    
    try:
        params = json.loads(params_json) if params_json else {}
    except json.JSONDecodeError:
        return "Error: params_json must be valid JSON."
        
    try:
        result = agent.execute(action_name, params)
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error executing {action_name}: {e}"
    finally:
        pythoncom.CoUninitialize()

@mcp.tool()
def aura_list_windows() -> str:
    """Lists all top-level windows currently open on the Windows desktop."""
    import pythoncom
    pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
    try:
        windows = []
        for w in auto.GetRootControl().GetChildren():
            if w.ControlType == auto.ControlType.WindowControl and w.Name:
                windows.append({"name": w.Name, "class_name": w.ClassName})
        return json.dumps({"windows": windows}, indent=2)
    except Exception as e:
        return f"Error listing windows: {e}"
    finally:
        pythoncom.CoUninitialize()

# ---------------------------------------------------------------------------
# 2. RESOURCES
# ---------------------------------------------------------------------------

@mcp.resource("aura://system/health")
def get_system_health() -> str:
    """Returns the current health and status of the AURA backend."""
    return json.dumps({"status": "online", "agents_loaded": len(registry.get_all_agents())})

@mcp.resource("aura://ui/windows")
def get_active_windows() -> str:
    """A resource containing the live list of open windows."""
    return aura_list_windows()

# ---------------------------------------------------------------------------
# 3. PROMPTS
# ---------------------------------------------------------------------------

@mcp.prompt()
def orchestrate_task(task_description: str) -> str:
    """Prompt for orchestrating a complex desktop automation task using AURA tools."""
    return f"I need you to automate the following task on the user's computer using the AURA MCP tools: {task_description}. First, list the agents available using aura_list_agents."
