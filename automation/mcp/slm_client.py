"""Drive the AURA MCP server with a small local model.

    python -m automation.mcp.slm_client "open notepad and type hello"

The model never writes a tool call freehand and never decides when to stop. It answers small
questions, each under a JSON schema that the model server enforces: split the request into steps,
then per step pick one action from the full list and fill in its parameter values. So any model an
OpenAI-compatible server (Ollama, LM Studio, llama.cpp) can load produces well-formed calls.
Everything else (discovery, the nested params_json string, the loop) is done here in plain code.
"""
import argparse
import asyncio
import contextlib
import functools
import json
import os
import sys
import urllib.request

URL = os.environ.get("AURA_SLM_URL", "http://127.0.0.1:11434/v1")  # Ollama's default
MODEL = os.environ.get("AURA_SLM_MODEL", "llama3.2:3b")
# Model for free-text sentences (web answers, spoken replies). A model fine-tuned for routing writes poor
# prose, so pair it with a stock one here. Default: the same model.
REPLY_MODEL = os.environ.get("AURA_REPLY_MODEL") or MODEL
ANSWER_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
                 "required": ["answer"], "additionalProperties": False}


def ask(question, schema, model=MODEL):
    """One completion constrained to `schema`; returns the parsed JSON object."""
    body = {"model": model, "temperature": 0, "messages": [{"role": "user", "content": question}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "answer", "strict": True, "schema": schema}}}
    req = urllib.request.Request(URL + "/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.loads(json.load(response)["choices"][0]["message"]["content"])


def reply(question, schema):
    return ask(question, schema, model=REPLY_MODEL)


def choose(llm, question, options):
    schema = {"type": "object", "properties": {"choice": {"type": "string", "enum": options}},
              "required": ["choice"], "additionalProperties": False}
    choice = llm(question, schema).get("choice")
    if choice not in options:  # a server that ignores response_format
        raise ValueError(f"Model answered {choice!r}, which is not one of {options}")
    return choice


def param_schema(hints):
    """JSON schema from an agent's parameter hints such as 'string', 'int 0-600', 'on|off', 'bool (optional)'."""
    props = {}
    for name, hint in hints.items():
        hint = str(hint)
        if hint.startswith("int"):
            prop = {"type": "integer"}
        elif hint.startswith("bool"):
            prop = {"type": "boolean"}
        elif "|" in hint and " " not in hint:
            prop = {"type": "string", "enum": hint.split("|")}
        else:
            prop = {"type": "string"}
        if "optional" in hint:
            prop = {"anyOf": [prop, {"type": "null"}]}
        props[name] = prop
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


# The three questions. automation/mcp/finetune builds its training data from these same functions,
# so a fine-tuned model must be retrained when their wording changes.

def split_schema(max_steps=8):
    return {"type": "object", "properties": {"steps": {"type": "array", "items": {"type": "string"},
                                                       "minItems": 1, "maxItems": max_steps}},
            "required": ["steps"], "additionalProperties": False}


def split_prompt(task):
    return ("A user gave a Windows PC assistant this request:\n" + task + "\n\n"
            "Split it into the separate actions it asks for, in order, in the user's own words. "
            "Most requests are a single action. Do not add actions the user did not ask for.")


def step_context(task, history, wanted):
    return (f"You operate a Windows PC for the user.\nFull request: {task}\n"
            "Steps already done:\n" + ("\n".join(history) or "(none)") + f"\nCurrent step: {wanted}\n\n")


def menu(catalog):
    return "\n".join(f"- {key}: {spec['description']}" for key, spec in catalog.items())


def choose_prompt(task, history, wanted, catalog):
    return step_context(task, history, wanted) + "Which ONE action performs the current step?\n" + menu(catalog)


def params_prompt(task, history, wanted, key, spec, reference=None):
    return (step_context(task, history, wanted) + f"Action: {key} ({spec['description']}).\n"
            f"Parameters: {json.dumps(spec['parameters'])}\n"
            + (f"Reference: {json.dumps(reference)}\n" if reference else "")
            + "Give the parameter values for the current step. "
              "Use an empty string or null for ones the user did not mention.")


def answer_prompt(task, text):
    return (f"The user asked: {task}\n\nText found on the web:\n{text}\n\n"
            "Answer the user in one or two short sentences using only this text. "
            "If the text does not contain the answer, say you could not find it.")


async def run(task, call_tool, llm=ask, confirm=input, max_steps=8, reply_llm=None):
    """Runs `task` one action per step; returns [{"call", "status", "details"}].

    `call_tool(name, arguments) -> str` is the only link to the MCP server.
    """
    reply_llm = reply_llm or (reply if llm is ask else llm)
    agents = json.loads(await call_tool("aura_list_agents", {}))["agents"]
    info = {a: json.loads(await call_tool("aura_get_agent_info", {"agent_name": a})) for a in agents}
    catalog = {f"{a}.{name}": spec for a in agents for name, spec in info[a]["actions"].items()}

    # ponytail: one action per step, planned up front; a step cannot be added after seeing a result.
    # Let the model add steps mid-run only if tasks that need it (read, then decide) start to matter.
    steps = llm(split_prompt(task), split_schema(max_steps))["steps"][:max_steps]
    done = []
    for wanted in steps:
        history = [f"{step['call']} -> {step['details'][:300]}" for step in done]
        key = choose(llm, choose_prompt(task, history, wanted, catalog), list(catalog))
        agent, action = key.split(".", 1)
        spec = catalog[key]
        hints = spec.get("parameters") or {}
        params = {}
        if hints:
            reference = {k: v for k, v in info[agent].items() if k not in ("application", "actions")}
            answer = llm(params_prompt(task, history, wanted, key, spec, reference), param_schema(hints))
            params = {k: v for k, v in answer.items() if k in hints and v not in ("", None)}
        call = f"{key} {json.dumps(params)}"
        if done and done[-1]["call"] == call:
            continue  # the model repeated the previous step
        if spec.get("safety", "safe") != "safe" and confirm(f"Run {call}? [y/N] ").strip().lower() != "y":
            done.append({"call": call, "status": "skipped", "details": "skipped: user declined"})
            break
        result = await call_tool("aura_execute_action", {"agent_name": agent, "action_name": action,
                                                         "params_json": json.dumps(params)})
        try:
            data = json.loads(result)
            # Some read-only actions report only structured data; keep it so the caller has something to say.
            status = data.get("status", "success")
            details = str(data.get("details") or "") or (json.dumps(data["data"])[:600] if data.get("data") else "")
            # Web text is only ever summarised here; it cannot add steps, so a hostile page cannot trigger actions.
            context = (data.get("data") or {}).get("answer_context")
            if status == "success" and context:
                details = reply_llm(answer_prompt(task, context), ANSWER_SCHEMA)["answer"]
        except (ValueError, AttributeError):  # the server's plain-text errors
            status, details = ("failure" if result.startswith("Error") else "success"), " ".join(result.split())
        done.append({"call": call, "status": status, "details": details})
        print(f"{call} -> {status}: {details[:300]}", file=sys.stderr)
        if status == "failure":
            break
    return done


@contextlib.asynccontextmanager
async def connect():
    """Starts the AURA MCP server over stdio; yields `call_tool(name, arguments) -> str`."""
    from mcp import ClientSession, StdioServerParameters, stdio_client
    server = StdioServerParameters(command=sys.executable, args=["-m", "automation.mcp"])
    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        async def call_tool(name, arguments):
            result = await session.call_tool(name, arguments)
            return "".join(getattr(block, "text", "") for block in result.content)

        yield call_tool


async def main():
    parser = argparse.ArgumentParser(description="Drive the AURA MCP server with a small local model")
    parser.add_argument("task")
    parser.add_argument("--model", default=MODEL, help=f"model name on the server at AURA_SLM_URL (default: {MODEL})")
    parser.add_argument("--max-steps", type=int, default=8)
    args = parser.parse_args()

    async with connect() as call_tool:
        done = await run(args.task, call_tool, functools.partial(ask, model=args.model), max_steps=args.max_steps)
    print("\n".join(f"{step['call']} -> {step['status']}: {step['details']}" for step in done) or "No steps taken.")


if __name__ == "__main__":
    asyncio.run(main())
