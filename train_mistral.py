"""
Fine-tune Mistral-7B with QLoRA + PEFT (scaffold)

This script prepares a training run using QLoRA (8-bit + LoRA) with Hugging Face
Transformers, PEFT and bitsandbytes. It's intended to be run on a GPU-equipped
machine with sufficient VRAM (>=24GB recommended for 7B with QLoRA).

DO NOT RUN on this machine unless you have the GPU available. This file is a
scaffold the user can run later.

Example usage (on GPU box):
    python train_mistral.py --dataset data/aria_retail_story_train.jsonl --output_dir outputs/mistral_ft --per_device_train_batch_size 4

Requirements (install on GPU machine):
    pip install transformers accelerate bitsandbytes peft datasets safetensors

"""
from pathlib import Path
import argparse


def main():
    parser = argparse.ArgumentParser(description="Fine-tune Mistral-7B using QLoRA + PEFT (scaffold)")
    parser.add_argument("--dataset", required=True, help="Path to JSONL dataset (instruction/response)")
    parser.add_argument("--output_dir", required=True, help="Output dir for adapters and checkpoints")
    parser.add_argument("--model_name", default="mistral-7b", help="Base model name or path")
    parser.add_argument("--per_device_train_batch_size", type=int, default=4)
    parser.add_argument("--gradient_accumulation_steps", type=int, default=8)
    parser.add_argument("--num_train_epochs", type=int, default=3)
    parser.add_argument("--learning_rate", type=float, default=2e-4)
    args = parser.parse_args()

    # Minimal scaffold showing steps. Actual training should be run interactively
    # on a GPU machine using `accelerate launch` or a training script adapted to
    # your cluster (Slurm, etc.). This script intentionally does NOT execute
    # training locally when run here.

    print("Scaffold created. On a GPU machine, run the following steps:")
    print("")
    print("1) Create a Python environment with required libs:")
    print("   pip install transformers accelerate bitsandbytes peft datasets safetensors")
    print("")
    print("2) Prepare your dataset as a JSONL with two fields: 'instruction' and 'output'.")
    print("   Example record: {\"instruction\": \"Summarize sales by month\", \"output\": \"...\"}")
    print("")
    print("3) Run training via accelerate (example):")
    print(f"   accelerate launch --config_file ~/accelerate_config.yaml train_script.py --dataset {args.dataset} --output_dir {args.output_dir} --model_name {args.model_name} --per_device_train_batch_size {args.per_device_train_batch_size} --num_train_epochs {args.num_train_epochs}")
    print("")
    print("4) Export adapter or convert to Ollama/GGUF as needed for local serving.")


if __name__ == '__main__':
    main()
