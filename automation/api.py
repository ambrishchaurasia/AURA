import time
from flask import Flask, request, jsonify
from flask_cors import CORS
from automation.core.llm_orchestrator import LLMOrchestrator
from automation.core.registry import registry

app = Flask(__name__)
# Enable CORS so the React frontend can talk to us
CORS(app)

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
    plan_result = planner.plan(prompt)
    
    actions = plan_result.get("actions", [])
    message = plan_result.get("message", "")
    
    # We still allow execution if actions exist.
    # If no actions but we have a message, it's a conversational response!
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
    app.run(host="127.0.0.1", port=5000, debug=True)
