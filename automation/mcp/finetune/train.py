"""LoRA fine-tune of a small chat model on make_dataset.py output; saves a merged model.

    python train.py --base models/qwen2.5-0.5B --train data/train.jsonl --val data/val.jsonl --out out/aura-qwen-0.5B

Runs on one GPU. Needs torch, transformers and peft (not part of AURA's own requirements).
"""
import argparse
import json
import math
import random

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

parser = argparse.ArgumentParser()
parser.add_argument("--base", required=True)
parser.add_argument("--train", required=True)
parser.add_argument("--val", required=True)
parser.add_argument("--out", required=True)
parser.add_argument("--epochs", type=int, default=2)
parser.add_argument("--lr", type=float, default=2e-4)
parser.add_argument("--batch-tokens", type=int, default=8000, help="padded tokens per batch; lower it if the GPU runs out of memory")
args = parser.parse_args()

random.seed(0)
torch.manual_seed(0)
tokenizer = AutoTokenizer.from_pretrained(args.base)
model = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype=torch.bfloat16).cuda()
model = get_peft_model(model, LoraConfig(
    r=32, lora_alpha=64, lora_dropout=0.05, task_type="CAUSAL_LM",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
model.print_trainable_parameters()


def load(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        messages = json.loads(line)["messages"]
        prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
        rows.append((tokenizer(prompt, add_special_tokens=False).input_ids,
                     tokenizer(messages[-1]["content"] + "<|im_end|>", add_special_tokens=False).input_ids,
                     messages[-1]["content"]))
    return rows


def batches(rows):
    """Similar lengths together, as many as fit the token budget, in random order."""
    rows = sorted(rows, key=lambda row: len(row[0]) + len(row[1]))
    out, current = [], []
    for row in rows:
        if current and (len(current) + 1) * (len(row[0]) + len(row[1])) > args.batch_tokens:
            out.append(current)
            current = []
        current.append(row)
    out.append(current)
    random.shuffle(out)
    return out


def tensors(batch):
    width = max(len(p) + len(a) for p, a, _ in batch)
    ids = torch.full((len(batch), width), tokenizer.pad_token_id)
    labels = torch.full((len(batch), width), -100)  # the loss covers only the answer
    for i, (p, a, _) in enumerate(batch):
        ids[i, :len(p) + len(a)] = torch.tensor(p + a)
        labels[i, len(p):len(p) + len(a)] = torch.tensor(a)
    return ids.cuda(), labels.cuda(), (ids != tokenizer.pad_token_id).cuda()


train, val = load(args.train), load(args.val)
steps = args.epochs * len(batches(train))
optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=0.01)
schedule = torch.optim.lr_scheduler.LambdaLR(
    optimizer, lambda step: min(1.0, (step + 1) / 50) * 0.5 * (1 + math.cos(math.pi * step / steps)))
step = 0
model.train()
for epoch in range(args.epochs):
    for batch in batches(train):
        ids, labels, mask = tensors(batch)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            loss = model(input_ids=ids, attention_mask=mask, labels=labels).loss
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        schedule.step()
        optimizer.zero_grad()
        step += 1
        if step % 25 == 0:
            print(f"epoch {epoch} step {step}/{steps} loss {loss.item():.4f}", flush=True)

# Sanity check on generated data the model has not seen: unconstrained greedy answers, exact match.
model.eval()
right = {}
for prompt, _, expected in val[:400]:
    kind = next((name for name, key in (("split", '"steps"'), ("choose", '"choice"'), ("reply", '"reply"'), ("answer", '"answer"'))
                 if expected.startswith("{" + key)), "params")
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        out = model.generate(input_ids=torch.tensor([prompt]).cuda(), max_new_tokens=200, do_sample=False,
                             eos_token_id=tokenizer.convert_tokens_to_ids("<|im_end|>"), pad_token_id=tokenizer.pad_token_id)
    answer = tokenizer.decode(out[0, len(prompt):], skip_special_tokens=True).strip()
    hit, total = right.get(kind, (0, 0))
    right[kind] = (hit + (answer == expected), total + 1)
print("validation exact match:", {kind: f"{hit}/{total}" for kind, (hit, total) in right.items()}, flush=True)

model = model.merge_and_unload()
model.save_pretrained(args.out)
tokenizer.save_pretrained(args.out)
print("saved", args.out)
