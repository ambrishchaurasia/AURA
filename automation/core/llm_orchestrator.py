import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

from automation.core.registry import registry

GROQ_MODEL = "openai/gpt-oss-120b"


class LLMOrchestrator:
    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set in the environment or .env file.")

        self.client = Groq(api_key=api_key)

        # Build dynamic capabilities string from the registry
        capabilities = ""
        for name, agent in registry.get_all_agents().items():
            capabilities += agent.get_llm_capabilities() + "\n"

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
        Sends the user prompt to Groq and parses the resulting JSON.
        Retries automatically on rate limit errors.
        """
        max_retries = 4
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[
                        {"role": "system", "content": self.system_instruction},
                        {"role": "user",   "content": prompt},
                    ],
                    temperature=0.0,
                )
                text = response.choices[0].message.content.strip()
                break  # Success
            except Exception as e:
                err_str = str(e)
                if ("429" in err_str or "503" in err_str or "rate_limit" in err_str.lower()) and attempt < max_retries - 1:
                    import time
                    wait_secs = 2 ** attempt
                    print(f"[LLMOrchestrator] Groq busy (attempt {attempt+1}/{max_retries}). Retrying in {wait_secs}s...")
                    time.sleep(wait_secs)
                else:
                    print(f"[LLMOrchestrator] Groq Error: {e}")
                    return {"message": f"API Error: {e}", "actions": []}
        else:
            return {"message": "Groq API unavailable after retries.", "actions": []}

        try:
            # Strip any accidental markdown fences
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
            print(f"[LLMOrchestrator] Raw Response: {text}")
            return {"message": "Failed to parse LLM response.", "actions": []}
        except Exception as e:
            print(f"[LLMOrchestrator] Error: {e}")
            return {"message": f"Error: {e}", "actions": []}


if __name__ == "__main__":
    orchestrator = LLMOrchestrator()
    plan = orchestrator.plan("Open Notepad, type Hello Ambrish, and save as my_test.txt")
    print(json.dumps(plan, indent=2))
