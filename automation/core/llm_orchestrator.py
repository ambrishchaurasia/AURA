import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

from automation.core.registry import registry

class LLMOrchestrator:
    def __init__(self):
        # We need the API key to use Google Gemini
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set in the environment or .env file.")
        
        self.client = genai.Client(api_key=api_key)
        
        # Build dynamic capabilities string from the registry
        capabilities = ""
        for name, agent in registry.get_all_agents().items():
            capabilities += agent.get_llm_capabilities() + "\n"

        # System instructions to enforce the JSON structure for the agents
        self.system_instruction = """
You are the Orchestrator for AURA (Agentic UI Routing Assistant).
Your job is to translate the user's natural language request into a sequence of JSON actions for desktop automation agents.

Available Agents and their capabilities:
""" + capabilities + """
You MUST respond with a RAW JSON object containing an optional message and the steps to execute.
Do not use markdown blocks like ```json. Return ONLY the raw JSON string.

Format:
{
  "message": "<A conversational response to the user, if needed>",
  "actions": [
    {
      "agent": "<agent_name>",
      "action": "<action_name>",
      "params": { ... }
    }
  ]
}
"""

    def plan(self, prompt: str) -> dict:
        """
        Sends the user prompt to Gemini and parses the resulting JSON.
        Returns a list of action dictionaries.
        """
        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_instruction,
                    temperature=0.0
                )
            )
            
            # Extract text from response
            text = response.text.strip()
            
            # Clean up markdown code blocks if the model accidentally includes them
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            
            text = text.strip()
            
            response_data = json.loads(text)
            if not isinstance(response_data, dict):
                print(f"[LLMOrchestrator] Error: LLM returned non-dict JSON: {response_data}")
                return {"message": "Invalid response format from LLM.", "actions": []}
                
            return response_data
            
        except json.JSONDecodeError as e:
            print(f"[LLMOrchestrator] JSON Parse Error: {e}")
            print(f"[LLMOrchestrator] Raw Response: {response.text}")
            return {"message": "Failed to understand the response.", "actions": []}
        except Exception as e:
            print(f"[LLMOrchestrator] API Error: {e}")
            return {"message": f"API Error: {e}", "actions": []}

if __name__ == "__main__":
    # Quick test
    orchestrator = LLMOrchestrator()
    plan = orchestrator.plan("Open Notepad, type Hello Ambrish, and save as my_test.txt")
    print(json.dumps(plan, indent=2))
