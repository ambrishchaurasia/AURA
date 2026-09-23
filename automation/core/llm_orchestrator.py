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
        Retries automatically on 429/503 errors.
        """
        max_retries = 4
        response = None
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model="models/gemini-3.5-flash-lite",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=self.system_instruction,
                        temperature=0.0
                    )
                )
                break  # Success
            except Exception as e:
                err_str = str(e)
                if ("429" in err_str or "503" in err_str or "RESOURCE_EXHAUSTED" in err_str or "UNAVAILABLE" in err_str) and attempt < max_retries - 1:
                    import time
                    wait_secs = 2 ** attempt  # 1s, 2s, 4s
                    print(f"[LLMOrchestrator] API busy (attempt {attempt+1}/{max_retries}). Retrying in {wait_secs}s...")
                    time.sleep(wait_secs)
                else:
                    print(f"[LLMOrchestrator] API Error: {e}")
                    return {"message": f"API Error: {e}", "actions": []}

        if response is None:
            return {"message": "API unavailable after retries.", "actions": []}

        try:
            text = response.text.strip()
            # Clean up markdown code blocks if model accidentally includes them
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
            return {"message": "Failed to parse LLM response.", "actions": []}
        except Exception as e:
            print(f"[LLMOrchestrator] Error: {e}")
            return {"message": f"Error: {e}", "actions": []}

if __name__ == "__main__":
    # Quick test
    orchestrator = LLMOrchestrator()
    plan = orchestrator.plan("Open Notepad, type Hello Ambrish, and save as my_test.txt")
    print(json.dumps(plan, indent=2))
