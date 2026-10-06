"""
AURA CLI — Command-line entry point for testing automation.

Demonstrates the NotepadAgent working end-to-end:
1. Find or open Notepad
2. Resolve the text editor
3. Type text at current caret position
4. Verify text was entered

Usage:
    python -m automation.main                          # Default demo
    python -m automation.main "Hello World"            # Type custom text
    python -m automation.main --action open            # Just open Notepad
    python -m automation.main --action type "My text"  # Type text
    python -m automation.main --action verify "text"   # Verify text exists
    python -m automation.main --inspect                # Inspect Notepad UI tree
"""

from __future__ import annotations
import sys
import uuid

from automation.agents import get_agent
from automation.core.logger import TaskLog


def run_task(goal: str, text: str = "Hello World"):
    """Run a simple Notepad automation task."""
    task_id = str(uuid.uuid4())[:8]
    log = TaskLog(task_id, goal)

    agent = get_agent("notepad")

    print(f"\n{'='*50}")
    print(f"  AURA — Task Execution")
    print(f"  Goal: {goal}")
    print(f"  Agent: {agent.app_name}")
    print(f"{'='*50}")

    # Step 1: Open Notepad
    log.start_step("open", application="notepad")
    result = agent.execute("open")
    if result["status"] == "success":
        log.complete_step(details=result["details"])
    else:
        log.fail_step(result["details"])
        log.finish("failed")
        return log

    # Step 2: Verify window exists
    log.start_step("verify_window", application="notepad", target="Notepad window")
    v = agent.verify({"window_exists": True})
    if v["verified"]:
        log.complete_step(details="Window verified", verification=v)
    else:
        log.fail_step("Window not found after open", details=str(v))
        log.finish("failed")
        return log

    # Step 3: Type text
    log.start_step("type", application="notepad", target="Text editor")
    result = agent.execute("type", {"text": text})
    if result["status"] == "success":
        log.complete_step(details=result["details"])
    else:
        log.fail_step(result["details"])
        log.finish("failed")
        return log

    # Step 4: Verify text was entered
    log.start_step("verify_text", application="notepad", target="Text content")
    v = agent.verify({"text_contains": text})
    if v["verified"]:
        log.complete_step(details="Text verified", verification=v)
    else:
        log.fail_step("Text verification failed", details=str(v))
        log.finish("failed")
        return log

    log.finish("completed")
    return log


def inspect_notepad():
    """Inspect the Notepad UI tree (debug utility)."""
    from automation.core.window_manager import find_window_simple

    window = find_window_simple("Notepad")
    if window is None:
        print("Notepad is not running. Please open Notepad first.")
        return

    print(f"\nFound window: {window.window_text()}\n")

    def _inspect(element, depth=0, max_depth=5):
        indent = "  " * depth
        try:
            info = element.element_info
            print(
                f"{indent}- name={info.name!r}, "
                f"type={info.control_type!r}, "
                f"auto_id={info.automation_id!r}, "
                f"class={info.class_name!r}"
            )
        except Exception as e:
            print(f"{indent}- Error: {e}")

        if depth >= max_depth:
            return

        try:
            children = element.children()
        except Exception:
            children = []

        for child in children:
            _inspect(child, depth + 1, max_depth)

    _inspect(window)


from automation.core.llm_orchestrator import LLMOrchestrator
from automation.core.planner import SimplePlanner
from automation.core.registry import registry

def execute_prompt(prompt: str):
    """Execute a natural language prompt using LLMOrchestrator or SimplePlanner fallback."""
    plan = []
    try:
        planner = LLMOrchestrator()
        plan_result = planner.plan(prompt)
        plan = plan_result.get("actions", [])
        if plan_result.get("message") and plan:
            print(f"\n[AURA Assistant]: {plan_result['message']}")
    except Exception as e:
        print(f"[CLI] LLM Orchestrator error ({e})")
        plan = []
    
    if not plan:
        print("[CLI] Using SimplePlanner fallback...")
        planner = SimplePlanner()
        plan = planner.plan(prompt)
    
    if not plan:
        print("Could not understand any actionable steps from the prompt.")
        return
        
    task_id = str(uuid.uuid4())[:8]
    log = TaskLog(task_id, prompt)
    
    print(f"\n{'='*50}")
    print(f"  AURA — Task Execution")
    print(f"  Prompt: {prompt}")
    print(f"{'='*50}")
    
    for i, step in enumerate(plan):
        action = step.get("action")
        params = step.get("params", {})
        agent_name = step.get("agent", "notepad")
        
        agent = registry.get_agent(agent_name)
        if not agent:
            try:
                agent = get_agent(agent_name)
            except Exception:
                print(f"  [FAIL] Error: Unknown agent '{agent_name}'")
                log.finish("failed")
                return log

        print(f"\n[Step {i+1}] [{agent.app_name}] Executing: {action} {params}")
        log.start_step(action, application=agent_name)
        
        result = agent.execute(action, params)
        if result["status"] == "success":
            log.complete_step(details=result["details"])
            print(f"  [OK] Success: {result['details']}")
        else:
            log.fail_step(result["details"])
            print(f"  [FAIL] Error: {result['details']}")
            log.finish("failed")
            return log
            
    log.finish("completed")
    print(f"\nTask completed successfully!")
    return log

def main():
    args = sys.argv[1:]

    if not args:
        # Ask for a prompt interactively
        print("\nWelcome to AURA (Agentic UI Routing Assistant)")
        print("Type a command for Notepad (e.g., 'Open Notepad, type Hello World, and save it as test.txt')")
        prompt = input("\nAURA> ")
        if prompt.strip():
            execute_prompt(prompt)
        return

    if args[0] == "--inspect":
        inspect_notepad()
        return

    # If prompt passed as args
    prompt = " ".join(args)
    execute_prompt(prompt)

if __name__ == "__main__":
    main()