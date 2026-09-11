# AURA App Agents
# Each agent implements the BaseAgent contract for a specific application.

from automation.agents.notepad_agent import NotepadAgent

# Agent registry — maps application name to agent class
AGENT_REGISTRY = {
    "notepad": NotepadAgent,
}


def get_agent(app_name: str):
    """Get an agent instance by application name."""
    app_key = app_name.strip().lower()
    agent_class = AGENT_REGISTRY.get(app_key)
    if agent_class is None:
        raise ValueError(
            f"No agent registered for application: {app_name!r}. "
            f"Available: {list(AGENT_REGISTRY.keys())}"
        )
    return agent_class()


def list_agents():
    """List all registered agent names."""
    return list(AGENT_REGISTRY.keys())
