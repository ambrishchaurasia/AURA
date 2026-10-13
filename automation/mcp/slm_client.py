"""Drive the AURA MCP server with a small local model.

    python -m automation.mcp.slm_client "open notepad and type hello"

The model never writes a tool call freehand and never decides when to stop. It answers small
questions, each under a JSON schema that the model server enforces: split the request into steps,
then per step pick one action from the full list and fill in its parameter values. So any model
produces well-formed calls. Everything else (discovery, the nested params_json string, the loop)
is done here in plain code.

By default AURA runs the model itself with the bundled llama.cpp server (started hidden on first
use, stopped when AURA exits). Set AURA_SLM_URL to use an OpenAI-compatible server you run
yourself instead (Ollama, LM Studio).
"""
import argparse
import asyncio
import atexit
import contextlib
import functools
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request

URL = os.environ.get("AURA_SLM_URL")  # e.g. http://127.0.0.1:11434/v1 for Ollama; unset: the bundled llama.cpp
MODEL = os.environ.get("AURA_SLM_MODEL", "aura-qwen-0.5b")  # fine-tuned for AURA; install.bat downloads it
# Model for free-text sentences (web answers, spoken replies). Default: the same model.
REPLY_MODEL = os.environ.get("AURA_REPLY_MODEL") or MODEL
DATA = pathlib.Path(os.environ.get("AURA_DATA_DIR") or pathlib.Path(os.environ.get("LOCALAPPDATA", ".")) / "AURA")
SYSTEM = "You are AURA, a Windows PC assistant."  # the fine-tuned models were trained with this system prompt
ANSWER_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
                 "required": ["answer"], "additionalProperties": False}

_servers = {}  # model name -> base URL of the llama.cpp server AURA started for it


def model_file(model):
    """The GGUF for `model`: a path, or the start of a file name in AURA's models folder (aura-qwen-0.5b -> aura-qwen-0.5B-q8_0.gguf)."""
    if pathlib.Path(model).is_file():
        return pathlib.Path(model)
    found = sorted(path for path in (DATA / "models").glob("*.gguf") if path.name.lower().startswith(model.lower()))
    if not found:
        raise FileNotFoundError(f"No model file for '{model}' in {DATA / 'models'}. Run install.bat, or set AURA_SLM_URL to your own server.")
    return found[0]


def server_url(model=MODEL):
    """Base URL to ask `model` at. Starts AURA's own llama.cpp server for it the first time."""
    if URL:
        return URL
    if model not in _servers:
        exe = DATA / "llama.cpp" / "llama-server.exe"
        if not exe.is_file():
            raise FileNotFoundError(f"{exe} is missing. Run install.bat, or set AURA_SLM_URL to your own server.")
        with socket.socket() as probe:  # any free port, so two AURA processes do not collide
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        log = open(DATA / "llama-server.log", "w")
        server = subprocess.Popen(
            [str(exe), "-m", str(model_file(model)), "--host", "127.0.0.1", "--port", str(port),
             "-ngl", "99", "-c", "8192", "-np", "1"],
            stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        atexit.register(server.terminate)
        _kill_with_parent(server)
        deadline = time.monotonic() + 120
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).close()
                break
            except OSError:
                if server.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(f"The model server did not start; see {DATA / 'llama-server.log'}") from None
                time.sleep(0.3)
        _servers[model] = f"http://127.0.0.1:{port}/v1"
    return _servers[model]


def _kill_with_parent(process):
    """Ties `process` to this one, so it cannot outlive AURA even if AURA is killed."""
    try:
        import win32api
        import win32con
        import win32job
        job = win32job.CreateJobObject(None, "")
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, process.pid)
        win32job.AssignProcessToJobObject(job, handle)
        process._aura_job = job  # the job closes, and kills the server, when this process ends
    except Exception as error:  # still stopped by atexit on a normal exit
        print(f"Could not tie the model server to AURA: {error!r}", file=sys.stderr)


def ask(question, schema, model=MODEL):
    """One completion constrained to `schema`; returns the parsed JSON object."""
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "answer", "strict": True, "schema": schema}}}
    req = urllib.request.Request(server_url(model) + "/chat/completions", json.dumps(body).encode(),
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


REPLY_SCHEMA = {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"],
                "additionalProperties": False}


def reply_prompt(request, call, details):
    """Asks for an agent's terse result ("volume: 30, muted: False") as something to say aloud."""
    return (f'The user said to their PC assistant: "{request}"\nThe PC did: {call}\nResult: {details[:600]}\n\n'
            "Tell the user the result in one short, friendly spoken sentence. Plain words, no technical terms, "
            "no field names. Keep every number exactly as given and add nothing that is not in the result.")


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
