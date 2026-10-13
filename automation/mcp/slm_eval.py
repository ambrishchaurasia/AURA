"""Measure which local models can drive AURA.

    python -m automation.mcp.slm_eval [model ...]

Runs fixed commands through slm_client.run() with the real agent capabilities but a fake executor,
so nothing happens on the desktop. Per model it prints:
  right - the expected calls were made first, in order
  clean - and the model stopped there instead of doing extra steps
"""
import asyncio
import functools
import json
import sys
import time

from automation.core.registry import registry
from automation.mcp import slm_client

MODELS = ["gemma3:270m", "qwen2.5:0.5b", "qwen2.5:1.5b", "llama3.2:3b"]

# (command, [(agent, action or alternatives, params that must be present)])
TASKS = [
    ("turn bluetooth off", [("settings", "set_bluetooth", {"state": "off"})]),
    ("turn on wifi", [("settings", "set_wifi", {"state": "on"})]),
    ("set the volume to 30", [("settings", "set_volume", {"level": 30})]),
    ("mute the sound", [("settings", "set_mute", {"state": "on"})]),
    ("set brightness to 70 percent", [("settings", "set_brightness", {"level": 70})]),
    ("switch to dark mode", [("settings", "set_theme", {"mode": "dark"})]),
    ("turn on airplane mode", [("settings", "set_airplane_mode", {"state": "on"})]),
    ("how much battery is left", [("settings", "get_battery", {})]),
    ("how much free disk space do I have", [("settings", "storage_status", {})]),
    ("check for windows updates", [("settings", "check_updates", {})]),
    ("my internet is not working, find out why", [("settings", "diagnose_network", {})]),
    ("open notepad", [("notepad", "open", {})]),
    ("open the downloads folder", [("explorer", ("open", "navigate"), {"path": "downloads"})]),
    ("create a folder called reports", [("explorer", "create_folder", {"folder_name": "reports"})]),
    ("search the web for banana bread recipes", [("browser", "search", {"query": "banana bread"})]),
    ("open youtube.com", [("browser", "open_url", {"url": "youtube"})]),
    ("make it a bit quieter", [("settings", "change_volume", {"direction": "down"})]),
    ("crank the volume up", [("settings", "change_volume", {"direction": "up"})]),
    ("the music on spotify is way too loud", [("settings", "change_app_volume", {"app": "spotify", "direction": "down"})]),
    ("brave is too quiet, bring it up", [("settings", "change_app_volume", {"app": "brave", "direction": "up"})]),
    ("dim my display a little", [("settings", "change_brightness", {"direction": "down"})]),
    ("who is the ceo of microsoft", [("browser", "answer_question", {"question": "ceo"})]),
    ("what's the tallest building in the world", [("browser", "answer_question", {"question": "tallest"})]),
    ("look up cheap gaming mice on google", [("browser", "search", {"query": "gaming mice"})]),
    ("bring up github", [("browser", "open_url", {"url": "github"})]),
    ("is my laptop plugged in and charging", [("settings", "get_battery", {})]),
    ("connect me to the JioFiber network", [("settings", "connect_wifi", {"name": "jiofiber"})]),
    ("which wifi networks are around", [("settings", "list_wifi_networks", {})]),
    ("unmute the computer", [("settings", "set_mute", {"state": "off"})]),
    ("send sound to my headphones", [("settings", "set_audio_device", {"name": "headphones"})]),
    ("silence discord", [("settings", "set_app_mute", {"app": "discord", "state": "on"})]),
    ("go back to the light look", [("settings", "set_theme", {"mode": "light"})]),
    ("go to night light settings", [("settings", "navigate", {"page": "night light"})]),
    ("what version of windows do i have", [("settings", "system_info", {})]),
    ("type meeting moved to friday", [("notepad", "type", {"text": "meeting moved to friday"})]),
    ("save this as groceries.txt", [("notepad", "save_as", {"filename": "groceries"})]),
    ("i'm done with notepad, close it", [("notepad", "close", {})]),
    ("find my resume in my files", [("explorer", "search", {"query": "resume"})]),
    ("make a folder named taxes in documents", [("explorer", "create_folder", {"folder_name": "taxes", "path": "documents"})]),
    ("what lectures do i have today", [("browser", "get_timetable", {})]),
    ("open notepad, type shopping list and save it as list.txt",
     [("notepad", "open", {}), ("notepad", "type", {"text": "shopping list"}), ("notepad", "save_as", {"filename": "list"})]),
    ("turn on dark mode and lower the brightness",
     [("settings", "set_theme", {"mode": "dark"}), ("settings", "change_brightness", {"direction": "down"})]),
    ("mute spotify then open youtube.com",
     [("settings", "set_app_mute", {"app": "spotify", "state": "on"}), ("browser", "open_url", {"url": "youtube"})]),
    ("switch wifi off and bluetooth on",
     [("settings", "set_wifi", {"state": "off"}), ("settings", "set_bluetooth", {"state": "on"})]),
    ("go to documents and create a folder called drafts",
     [("explorer", ("navigate", "open"), {"path": "documents"}), ("explorer", "create_folder", {"folder_name": "drafts"})]),
    ("open notepad and type hello world", [("notepad", "open", {}), ("notepad", "type", {"text": "hello world"})]),
    ("turn off bluetooth and set the volume to 50",
     [("settings", "set_bluetooth", {"state": "off"}), ("settings", "set_volume", {"level": 50})]),
]


def matches(call, expected):
    agent, action, params = expected
    actions = (action,) if isinstance(action, str) else action
    return (call[0] == agent and call[1] in actions
            and all(str(value).lower() in str(call[2].get(key, "")).lower() for key, value in params.items()))


async def attempt(task, llm):
    calls = []

    async def call_tool(name, arguments):
        if name == "aura_list_agents":
            return json.dumps({"agents": list(registry.get_all_agents())})
        if name == "aura_get_agent_info":
            return json.dumps(registry.get_agent(arguments["agent_name"]).get_capabilities())
        calls.append((arguments["agent_name"], arguments["action_name"], json.loads(arguments["params_json"])))
        return json.dumps({"status": "success", "action": arguments["action_name"]})

    try:
        await slm_client.run(task, call_tool, llm, confirm=lambda prompt: "y")
    except Exception as error:  # a model or server failure counts as a wrong answer
        print(f"    error: {error}", file=sys.stderr)
    return calls


def main():
    for model in sys.argv[1:] or MODELS:
        right = clean = asked = 0
        seconds = 0.0

        def llm(question, schema):
            nonlocal asked, seconds
            start = time.perf_counter()
            try:
                return slm_client.ask(question, schema, model=model)
            finally:
                asked += 1
                seconds += time.perf_counter() - start

        for task, expected in TASKS:
            calls = asyncio.run(attempt(task, llm))
            ok = len(calls) >= len(expected) and all(map(matches, calls, expected))
            right += ok
            clean += ok and len(calls) == len(expected)
            print(f"  {'ok  ' if ok else 'FAIL'} {task!r} -> {[f'{a}.{n} {json.dumps(p)}' for a, n, p in calls]}",
                  file=sys.stderr)
        print(f"{model:16} right {right}/{len(TASKS)}  clean {clean}/{len(TASKS)}  {seconds / max(asked, 1):.2f}s per question")


if __name__ == "__main__":
    main()
