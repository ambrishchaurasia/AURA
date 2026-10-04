import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

from automation.core.registry import registry

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
        self.system_instruction = f"""
You are the Orchestrator for AURA (Agentic UI Routing Assistant).
Your job is to translate the user's natural language request into an ordered sequence of JSON actions for desktop automation agents (Notepad and File Explorer).

Available Agents and their capabilities:
{capabilities}

CHRONOLOGICAL STEP FLOW & CONTEXT RULES:
1. Maintain chronological step ordering strictly as specified or implied by the user's prompt (e.g., clauses connected by "then", "and then", "after that", "next").
2. Context Resolution & File Naming:
   - Resolve pronouns ("it", "the file", "that document") using previously mentioned filenames.
   - If user says "text document named hello" or "file called notes", resolve the filename to include `.txt` (e.g., `"hello.txt"`, `"notes.txt"`).
   - If user asks to save to a specific directory (e.g. "save as hello.txt in downloads"), pass `"path": "Downloads"` in `save_as`.
   - If user says "go to downloads and open hello.txt", emit `explorer` -> `navigate` `{{"path": "Downloads"}}` then `explorer` -> `open_item` `{{"filename": "hello.txt"}}`.
3. Save vs Save As Rules:
   - If user is creating/saving a new file for the first time, or explicitly requests "save as <filename>", emit `notepad` -> `save_as`.
   - If user opens an ALREADY SAVED file and edits it (e.g. "open hello.txt, edit it and save it"), emit `notepad` -> `save` `{{"params": {{}}}}` (Ctrl+S save), NOT `save_as`!
4. Standard Action Parameters:
   - `notepad` agent:
     - `open`: `{{"filepath": "<optional_path_or_filename>"}}`
     - `type`: `{{"text": "<string>"}}`
     - `save_as`: `{{"filename": "<filename>", "path": "<optional_folder>"}}`
     - `save`: `{{}}`
     - `close`: `{{}}`
   - `explorer` agent:
     - `open`: `{{"path": "<optional_folder>"}}`
     - `navigate`: `{{"path": "<folder_name_or_path>"}}`
     - `open_item`: `{{"filename": "<filename_or_path>"}}`
     - `create_folder`: `{{"folder_name": "<name>", "path": "<optional_path>"}}`
     - `create_file`: `{{"file_name": "<name>", "content": "<optional_content>", "path": "<optional_path>"}}`

EXAMPLE 1:
User: "open notepad write hello world and save text document named hello in documents"
Response JSON:
{{
  "message": "Opening Notepad, typing text, and saving text document as hello.txt in Documents.",
  "actions": [
    {{ "agent": "notepad", "action": "open", "params": {{}} }},
    {{ "agent": "notepad", "action": "type", "params": {{ "text": "hello world" }} }},
    {{ "agent": "notepad", "action": "save_as", "params": {{ "filename": "hello.txt", "path": "Documents" }} }}
  ]
}}

EXAMPLE 2:
User: "open file explorer go to downloads and open hello.txt and edit it and save it"
Response JSON:
{{
  "message": "Navigating to Downloads, opening hello.txt, editing it, and saving changes.",
  "actions": [
    {{ "agent": "explorer", "action": "navigate", "params": {{ "path": "Downloads" }} }},
    {{ "agent": "explorer", "action": "open_item", "params": {{ "filename": "hello.txt" }} }},
    {{ "agent": "notepad", "action": "type", "params": {{ "text": "\\nUpdated content." }} }},
    {{ "agent": "notepad", "action": "save", "params": {{}} }}
  ]
}}

You MUST respond with a RAW JSON object containing an optional message and the steps to execute.
Do not use markdown blocks like ```json. Return ONLY the raw JSON string.

Format:
{{
  "message": "<Conversational summary>",
  "actions": [
    {{
      "agent": "<agent_name>",
      "action": "<action_name>",
      "params": {{ ... }}
    }}
  ]
}}
"""

    def plan(self, prompt: str) -> dict:
        """
        Sends the user prompt to Gemini and parses the resulting JSON.
        Returns a dictionary with 'message' and 'actions'.
        """
        models_to_try = [
            "gemini-2.5-flash",
            "gemini-3.5-flash",
            "gemini-flash-latest",
            "gemini-2.5-pro",
            "gemini-3.6-flash",
        ]
        last_error = None

        for model_name in models_to_try:
            try:
                response = self.client.models.generate_content(
                    model=model_name,
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
                if isinstance(response_data, dict) and "actions" in response_data:
                    return response_data
                    
            except Exception as e:
                last_error = e
                continue

        print(f"[LLMOrchestrator] All Gemini models failed. Last error: {last_error}")
        return {"message": "Could not parse plan via Gemini LLM.", "actions": []}

if __name__ == "__main__":
    orchestrator = LLMOrchestrator()
    plan = orchestrator.plan("save as hello.txt and then open file explorer and open it and open file explorer go to downloads and open hello.txt and edit it")
    print(json.dumps(plan, indent=2))

