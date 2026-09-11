"""
AURA Rule-Based Planner (Stub for Milestone 5)

Parses natural language prompts and translates them into a sequence
of actionable steps for the agents, without needing an LLM.
"""

import re
from typing import List, Dict

class SimplePlanner:
    def plan(self, prompt: str) -> List[Dict]:
        """
        Parses a prompt like:
        'Open Notepad, type Hello World, and save it as test.txt'
        
        Returns a list of actions.
        """
        prompt_lower = prompt.lower()
        actions = []
        
        # Action 1: Open
        if "notepad" in prompt_lower or "open" in prompt_lower:
            actions.append({
                "agent": "notepad",
                "action": "open",
                "params": {}
            })
            
        # Action 2: Type
        if any(w in prompt_lower for w in ["type", "write", "wite", "writ", "text", "enter", "put"]):
            # Extract text preserving original casing
            match = re.search(
                r"(?:type|write|wite|writ|enter|put)\s+(?:['\"](?P<quoted>[^'\"]+)['\"]|(?P<unquoted>.+?))(?:\s+(?:and\s+save|and\s+close|and\s+quit)|\s+save\s+as|[,.;]|$)",
                prompt,
                re.IGNORECASE,
            )
            if match:
                text_to_type = (match.group("quoted") or match.group("unquoted") or "").strip()
            else:
                text_to_type = "Hello from AURA!"
                
            actions.append({
                "agent": "notepad",
                "action": "type",
                "params": {"text": text_to_type}
            })
            
        # Action 3: Save
        if "save" in prompt_lower:
            match = re.search(r"save(?:\s+it)?\s+as\s+['\"]?([^,.\s'\"]+(?:\.[a-zA-Z0-9]+)?)['\"]?", prompt, re.IGNORECASE)
            filename = match.group(1).strip() if match else "aura_output.txt"
            actions.append({
                "agent": "notepad",
                "action": "save_as",
                "params": {"filename": filename}
            })
            
        # Action 4: Close
        if "close" in prompt_lower or "quit" in prompt_lower:
            actions.append({
                "agent": "notepad",
                "action": "close",
                "params": {}
            })
            
        return actions
