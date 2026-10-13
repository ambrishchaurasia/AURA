"""Training examples for answering from web text, built from SQuAD 2.0 (CC BY-SA 4.0).

    python squad_answers.py 3000 answers.jsonl      (with slm_client.py copied next to this file)

Each example hides the paragraph that holds the answer among snippets from other articles, the way
search results arrive; questions SQuAD marks unanswerable teach "I could not find that". Needs the
`datasets` package and internet, so run it where train.py runs and append the output to train.jsonl.
"""
import json
import random
import sys

from datasets import load_dataset

import slm_client

count, out_path = int(sys.argv[1]), sys.argv[2]
rng = random.Random(0)
rows = load_dataset("rajpurkar/squad_v2", split="train").shuffle(seed=0)
others = [(row["title"].replace("_", " "), row["context"]) for row in rows.select(range(2000))]

with open(out_path, "w", encoding="utf-8") as out:
    for row in rows.select(range(2000, 2000 + count)):
        answers = row["answers"]
        if answers["text"]:
            start = max(0, answers["answer_start"][0] - rng.randint(40, 250))
            snippet = row["context"][start:start + 450]
            if answers["text"][0] not in snippet:
                continue
            reply = answers["text"][0].strip()
            reply = reply[0].upper() + reply[1:] + ("" if reply.endswith(".") else ".")
        else:
            snippet, reply = row["context"][:450], "I could not find that."
        lines = [f"{row['title'].replace('_', ' ')} - {snippet}"]
        lines += [f"{title} - {text[:rng.randint(150, 300)]}" for title, text in rng.sample(others, rng.randint(2, 4))]
        rng.shuffle(lines)
        question = row["question"].strip().rstrip("?").lower() if rng.random() < 0.5 else row["question"].strip()
        out.write(json.dumps({"messages": [
            {"role": "system", "content": slm_client.SYSTEM},
            {"role": "user", "content": slm_client.answer_prompt(question, "\n".join(lines))},
            {"role": "assistant", "content": json.dumps({"answer": reply})}]}) + "\n")
