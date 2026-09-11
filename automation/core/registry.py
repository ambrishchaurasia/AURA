import os
import importlib
import inspect
from automation.core.base_agent import BaseAgent

class AgentRegistry:
    def __init__(self):
        self._agents = {}
        self._discover_agents()

    def _discover_agents(self):
        """
        Dynamically load all agent classes from the `automation/agents/` directory
        and instantiate them.
        """
        agents_dir = os.path.join(os.path.dirname(__file__), "..", "agents")
        
        for filename in os.listdir(agents_dir):
            if filename.endswith("_agent.py") and not filename.startswith("__"):
                module_name = f"automation.agents.{filename[:-3]}"
                try:
                    module = importlib.import_module(module_name)
                    # Find any class in this module that inherits from BaseAgent (but isn't BaseAgent itself)
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if issubclass(obj, BaseAgent) and obj is not BaseAgent:
                            agent_instance = obj()
                            agent_name = agent_instance.get_agent_name()
                            self._agents[agent_name] = agent_instance
                            print(f"[Registry] Loaded agent: {agent_name} from {filename}")
                except Exception as e:
                    print(f"[Registry] Failed to load agent from {filename}: {e}")

    def get_agent(self, agent_name: str) -> BaseAgent | None:
        """Retrieve an initialized agent instance by its name."""
        return self._agents.get(agent_name.lower())

    def get_all_agents(self) -> dict[str, BaseAgent]:
        """Return a dictionary of all initialized agents."""
        return self._agents

# Singleton instance
registry = AgentRegistry()
