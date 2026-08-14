#!/usr/bin/env python3
"""Fine-tune of Mistral-7B-Instruct for ARIA business storytelling (P100-compatible).

Runs on a Kaggle GPU (P100/T4). Loads `{instruction, output}` JSONL training
data, applies the Mistral chat template, and trains a fp16 LoRA adapter.

NOTE: This script deliberately does NOT use bitsandbytes 4-bit. Kaggle's free
tier often assigns a P100 (sm_60), which current PyTorch (>=2.4) and
bitsandbytes (>=0.42) no longer support. This notebook installs
torch==2.3.1+cu118 (which still supports sm_60) and trains in fp16 LoRA.

Usage (as referenced by the ARIA fine-tune notebook):
    python finetune_mistral_story_kaggle.py \
        --data /kaggle/input/aria-kaggle-finetune/aria_story_training_data.jsonl \
        --output /kaggle/working/aria-story-mistral-7b-lora \
        --epochs 3
"""

import argparse
import json
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aria-finetune")

import torch  # noqa: E402
from datasets import Dataset, load_dataset  # noqa: E402
from peft import LoraConfig, get_peft_model  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments  # noqa: E402
from trl import SFTTrainer  # noqa: E402


def load_jsonl(path: Path):
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def format_messages(row):
    return [
        {"role": "user", "content": row["instruction"].strip()},
        {"role": "assistant", "content": row["output"].strip()},
    ]


def make_model_and_tokenizer(model_id):
    tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    if not torch.cuda.is_available():
        raise SystemExit(
            "No usable CUDA GPU detected. Set an accelerator (GPU) in the "
            "notebook Settings and re-run."
        )
    capability = torch.cuda.get_device_capability(0)
    logger.info("GPU: %s (compute capability %s.%s)", torch.cuda.get_device_name(0), *capability)

    model = AutoModelForCausalLM.from_pretrained(
        model_id, device_map="auto", torch_dtype=torch.float16
    )
    model.gradient_checkpointing_enable()
    logger.info("Loaded model in fp16 (LoRA).")
    return model, tokenizer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="JSONL training data")
    parser.add_argument("--output", required=True, help="Output dir for the LoRA adapter")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--model", default="mistralai/Mistral-7B-Instruct-v0.2")
    parser.add_argument("--max-seq-len", type=int, default=1024)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    data_path = Path(args.data)
    rows = load_jsonl(data_path)
    if not rows:
        raise SystemExit(f"No training rows found in {data_path}")
    logger.info("Loaded %d training rows from %s", len(rows), data_path)

    model, tokenizer = make_model_and_tokenizer(args.model)

    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    def format_text(examples):
        texts = [
            tokenizer.apply_chat_template(
                format_messages({"instruction": i, "output": o}),
                tokenize=False, add_generation_prompt=False,
            )
            for i, o in zip(examples["instruction"], examples["output"])
        ]
        return {"text": texts}

    dataset = Dataset.from_list(rows).map(format_text, batched=True, remove_columns=["instruction", "output"])

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(out_dir),
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        fp16=True,
        logging_steps=5,
        save_strategy="epoch",
        save_total_limit=1,
        report_to="none",
        seed=args.seed,
        optim="adamw_torch",
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        tokenizer=tokenizer,
        dataset_text_field="text",
        max_seq_length=args.max_seq_len,
        packing=False,
    )

    trainer.train()

    trainer.model.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))
    logger.info("LoRA adapter saved to %s", out_dir)


if __name__ == "__main__":
    main()