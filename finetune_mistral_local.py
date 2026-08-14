#!/usr/bin/env python3
"""Local preparation script for fine-tuning Mistral-7B for ARIA storytelling.

This script performs lightweight dataset validation + tokenization and writes
an Arrow-format dataset ready for training on a GPU machine. It does NOT start
training here; instead it prints a recommended `accelerate launch` command you
can run on a high-GPU machine with the required libraries installed.

Usage (local dev / prepare):
    python finetune_mistral_local.py --data data/aria_retail_story_train.jsonl --output ./aria_story_ft

On a GPU machine, run (example):
    accelerate launch --config_file my_accelerate_config.yaml train_mistral.py \
        --dataset ./aria_story_ft --model mistralai/Mistral-7B-Instruct-v0.2 --output ./aria-story-mistral-7b-lora

The training script `train_mistral.py` is intentionally left out of this
repository (it's GPU-specific). This helper prepares the data so training can
be executed later on a proper GPU instance.
"""

import argparse
import json
import os
from pathlib import Path

from datasets import Dataset

SYSTEM_PROMPT = (
    "You are ARIA's Insight Agent. Write only a concise business story for a "
    "non-technical manager. Start with the headline finding, explain the leading "
    "hypothesis, mention anomalies if relevant, and stay under 250 words."
)


def load_jsonl(path: Path):
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def format_example(example: dict) -> dict:
    instruction = example.get("instruction", "").strip()
    output = example.get("output", "").strip()
    text = (
        f"<s>[INST] {SYSTEM_PROMPT}\n\n{instruction} [/INST]\n" f"{output}</s>"
    )
    return {"text": text}


def main():
    parser = argparse.ArgumentParser(description="Prepare fine-tune dataset for Mistral-7B (local)")
    parser.add_argument("--data", required=True, help="JSONL with instruction/output rows")
    parser.add_argument("--output", required=True, help="Output directory for prepared dataset")
    args = parser.parse_args()

    data_path = Path(args.data)
    out_dir = Path(args.output)
    if not data_path.exists():
        raise SystemExit(f"Data file not found: {data_path}")

    rows = load_jsonl(data_path)
    if not rows:
        raise SystemExit("No rows found in the input JSONL. Provide a valid dataset.")

    print(f"Loaded {len(rows)} examples from {data_path}")
    formatted = [format_example(r) for r in rows]

    dataset = Dataset.from_list(formatted)

    out_dir.mkdir(parents=True, exist_ok=True)
    arrow_path = out_dir / "aria_story.arrow"
    dataset.save_to_disk(str(out_dir))
    print(f"Saved prepared dataset to: {out_dir}")

    print("\nNext step: transfer this folder to your GPU machine and run training with a script that:")
    print(" - loads the Arrow dataset (datasets.load_from_disk), tokenizes using the model tokenizer")
    print(" - configures QLoRA/bitsandbytes/PEFT or an equivalent setup")
    print(" - runs training with `accelerate launch` or equivalent on the GPU machine")

    print("\nExample training command (run on the GPU machine):")
    print("accelerate launch --config_file my_accelerate_config.yaml train_mistral.py \\")
    print("  --dataset ./aria_story_ft --model mistralai/Mistral-7B-Instruct-v0.2 --output ./aria-story-mistral-7b-lora")


if __name__ == "__main__":
    main()
