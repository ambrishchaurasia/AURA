import hmac
import os
import secrets
import time
from flask import Flask, request, jsonify
from flask_cors import CORS
from automation.core.llm_orchestrator import LLMOrchestrator
from automation.core.registry import registry

app = Flask(__name__)
# CORS only for the front-end origins listed in AURA_ALLOWED_ORIGINS (comma-separated).
# Default: none, so browsers only allow same-origin pages to read responses.
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("AURA_ALLOWED_ORIGINS", "").split(",") if o.strip()]
if ALLOWED_ORIGINS:
    CORS(app, origins=ALLOWED_ORIGINS)

# Shared secret every request must send in the X-AURA-Token header.
API_TOKEN = os.environ.get("AURA_API_TOKEN")
if not API_TOKEN:
    API_TOKEN = secrets.token_urlsafe(32)
    os.environ["AURA_API_TOKEN"] = API_TOKEN  # so the debug reloader's child process reuses it
    print(f"[API] AURA_API_TOKEN not set; generated one for this run: {API_TOKEN}")

@app.before_request
def require_token():
    # CORS preflights cannot carry custom headers; they execute nothing.
    if request.method == "OPTIONS":
        return None
    sent = request.headers.get("X-AURA-Token", "")
    if not hmac.compare_digest(sent.encode(), API_TOKEN.encode()):
        return jsonify({"error": "Missing or invalid X-AURA-Token"}), 401

# Initialize singletons
try:
    planner = LLMOrchestrator()
except ValueError as e:
    print(f"Failed to initialize LLM Orchestrator: {e}")
    planner = None

@app.route("/api/execute", methods=["POST"])
def execute_prompt():
    data = request.json
    if not data or "prompt" not in data:
        return jsonify({"error": "No prompt provided"}), 400

    prompt = data["prompt"]
    print(f"\n[API] Received prompt: {prompt}")

    if not planner:
        return jsonify({
            "status": "error",
            "message": "LLM Orchestrator is offline. Missing API Key?",
            "steps": []
        }), 500

    # 1. Parse actions via LLM
    actions = []
    message = ""
    if planner:
        try:
            plan_result = planner.plan(prompt)
            actions = plan_result.get("actions", [])
            message = plan_result.get("message", "")
        except Exception as e:
            print(f"[API] LLM planning error: {e}")

    # Fallback to SimplePlanner if LLM produces no actions
    if not actions:
        from automation.core.planner import SimplePlanner
        rule_planner = SimplePlanner()
        actions = rule_planner.plan(prompt)

    if not actions and not message:
        return jsonify({
            "status": "error",
            "message": "Could not understand the command.",
            "steps": []
        })

    # 2. Execute actions
    steps_results = []
    task_status = "COMPLETED"
    
    for idx, act in enumerate(actions, 1):
        agent_name = act.get("agent", "unknown")
        action_name = act.get("action")
        params = act.get("params", {})

        print(f"  [Step {idx}] {agent_name} -> {action_name} {params}")
        
        agent = registry.get_agent(agent_name)
        if agent:
            result = agent.execute(action_name, params)
        else:
            result = {
                "status": "failure",
                "action": action_name,
                "details": f"Unknown agent: {agent_name}",
                "duration_ms": 0
            }

        steps_results.append({
            "step": idx,
            "agent": agent_name,
            "action": action_name,
            "params": params,
            "status": result.get("status"),
            "details": result.get("details", ""),
            "duration_ms": result.get("duration_ms", 0)
        })

        if result.get("status") == "failure":
            task_status = "FAILED"
            break

    return jsonify({
        "status": task_status,
        "prompt": prompt,
        "steps": steps_results,
        "message": message
    })

if __name__ == "__main__":
    print("=======================================")
    print(" AURA Backend API Started on Port 5000")
    print("=======================================")
    # The Werkzeug debugger allows code execution; opt in with AURA_DEBUG=1 only.
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("AURA_DEBUG") == "1")
