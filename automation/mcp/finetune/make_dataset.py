"""Builds fine-tuning data for the three questions slm_client asks (split, choose, parameters).

    python -m automation.mcp.finetune.make_dataset train.jsonl val.jsonl

Prompts come from slm_client's own prompt functions and the live agent capabilities, so the model
is trained on exactly what it will be asked. Commands used by slm_eval are left out.
"""
import json
import random
import re
import sys

from automation.core.registry import registry
from automation.mcp import slm_client, slm_eval
from automation.mcp.finetune.commands import COMMANDS, JOINERS, PREFIXES, SLOTS, SUFFIXES

SYSTEM = "You are AURA, a Windows PC assistant."
# Sequences people actually say in one breath; the rest of the multi-step data is random pairs.
CHAINS = [["notepad.open", "notepad.type"], ["notepad.open", "notepad.type", "notepad.save_as"], ["notepad.type", "notepad.save"],
          ["explorer.open", "explorer.create_folder"], ["explorer.navigate", "explorer.create_file"], ["notepad.save", "notepad.close"],
          ["settings.set_bluetooth", "settings.set_wifi"], ["settings.set_volume", "settings.set_brightness"],
          ["settings.set_theme", "settings.change_brightness"], ["browser.open_url", "settings.change_volume"],
          ["notepad.select_all", "notepad.copy"], ["explorer.select_all", "explorer.copy"], ["settings.set_mute", "notepad.open"]]


def catalog_and_info():
    info = {name: agent.get_capabilities() for name, agent in registry.get_all_agents().items()}
    return {f"{a}.{name}": spec for a in info for name, spec in info[a]["actions"].items()}, info


def phrase(key, spec, rng):
    """One way to ask for `key`: (text, the full parameter answer the model must give)."""
    template, params = rng.choice(COMMANDS[key])
    filled = {}

    def fill(match):
        filled.setdefault(match.group(1), rng.choice(SLOTS[match.group(1)]))
        return str(filled[match.group(1)])

    text = re.sub(r"\{(\w+)\}", fill, template)
    answer = {}
    for name, hint in (spec.get("parameters") or {}).items():
        value = params.get(name)
        if isinstance(value, str) and re.fullmatch(r"\{\w+\}", value):
            value = filled[value[1:-1]]
        if value is None:
            if "optional" not in str(hint) and str(hint).startswith(("int", "bool")):
                raise ValueError(f"{key}: template {template!r} must give {name}")
            value = None if "optional" in str(hint) else ""
        elif str(hint).startswith("int"):
            value = int(value)
        elif not str(hint).startswith("bool"):
            value = str(value)
        answer[name] = value
    unknown = set(params) - set(answer)
    if unknown:
        raise ValueError(f"{key}: template {template!r} uses unknown parameters {unknown}")
    return rng.choice(PREFIXES) + text + rng.choice(SUFFIXES), answer


def examples(keys, catalog, info, rng):
    """All training examples for one request made of the actions `keys`."""
    pieces, answers = zip(*(phrase(key, catalog[key], rng) for key in keys))
    pieces = list(pieces)
    if rng.random() < 0.5:  # typed in lower case, or written the way Whisper writes speech
        pieces[0] = pieces[0][0].upper() + pieces[0][1:]
    joined = pieces[0]
    for piece in pieces[1:]:
        joiner = rng.choice(JOINERS)
        joined += joiner + (piece[0].upper() + piece[1:] if joiner.startswith(".") else piece)
    task = joined + rng.choice(["", "", ".", "?" if len(keys) == 1 and keys[0].endswith(("answer_question", "get_battery")) else "."])
    yield slm_client.split_prompt(task), {"steps": pieces}
    history = []
    for key, wanted, answer in zip(keys, pieces, answers):
        agent = key.split(".")[0]
        spec = catalog[key]
        yield slm_client.choose_prompt(task, history, wanted, catalog), {"choice": key}
        if answer:
            reference = {k: v for k, v in info[agent].items() if k not in ("application", "actions")}
            yield slm_client.params_prompt(task, history, wanted, key, spec, reference), answer
        sent = {k: v for k, v in answer.items() if v not in ("", None)}
        history = history + [f"{key} {json.dumps(sent)} -> {rng.choice(['Done', 'ok', '', 'success'])}"]


def build(seed, singles, multis):
    rng = random.Random(seed)
    catalog, info = catalog_and_info()
    missing, extra = set(catalog) - set(COMMANDS), set(COMMANDS) - set(catalog)
    if missing or extra:
        raise SystemExit(f"commands.py is out of date. No phrasings for: {sorted(missing)}. Unknown actions: {sorted(extra)}")
    held_out = {re.sub(r"\W+", " ", task).strip().lower() for task, _ in slm_eval.TASKS}
    keys = list(catalog)
    requests = [[keys[i % len(keys)]] for i in range(singles)]  # every action equally often
    requests += [rng.choice(CHAINS) if rng.random() < 0.4 else rng.sample(keys, rng.choice([2, 2, 2, 3])) for _ in range(multis)]
    rows = []
    for request in requests:
        for prompt, answer in examples(request, catalog, info, rng):
            said = prompt.split("\n")[1] if prompt.startswith("A user gave") else ""
            if re.sub(r"\W+", " ", said).strip().lower() in held_out:
                break
            rows.append({"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt},
                                      {"role": "assistant", "content": json.dumps(answer)}]})
    rng.shuffle(rows)
    return rows


if __name__ == "__main__":
    for path, seed, singles, multis in ((sys.argv[1], 0, 3000, 1500), (sys.argv[2], 1, 150, 75)):
        rows = build(seed, singles, multis)
        with open(path, "w", encoding="utf-8") as out:
            out.writelines(json.dumps(row) + "\n" for row in rows)
        print(f"{path}: {len(rows)} examples")
