"""
Prepare fine-tuning data for Mistral-7B from existing JSONL training examples.

Input: JSONL lines with either:
 - {'instruction': ..., 'output': ...}
 - or other fields; the script will try to map to 'instruction' and 'output'.

Output: sanitized JSONL that can be used by the training pipeline.
"""
import argparse
import json
from pathlib import Path


def prepare(in_path: Path, out_path: Path, max_examples=None):
    out = out_path.open("w", encoding="utf-8")
    count = 0
    for line in in_path.open("r", encoding="utf-8"):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        # Heuristic mapping
        if "instruction" in obj and "output" in obj:
            instr = obj["instruction"]
            outp = obj["output"]
        elif "prompt" in obj and "completion" in obj:
            instr = obj["prompt"]
            outp = obj["completion"]
        else:
            # Try to synthesize from keys
            keys = list(obj.keys())
            if len(keys) >= 2:
                instr = str(obj[keys[0]])
                outp = str(obj[keys[1]])
            else:
                continue
        item = {"instruction": instr, "output": outp}
        out.write(json.dumps(item, ensure_ascii=False) + "\n")
        count += 1
        if max_examples and count >= max_examples:
            break
    out.close()
    print(f"Wrote {count} examples to {out_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="infile", required=True)
    parser.add_argument("--out", dest="outfile", required=True)
    parser.add_argument("--max", dest="max_examples", type=int, default=None)
    args = parser.parse_args()
    prepare(Path(args.infile), Path(args.outfile), args.max_examples)
