# Using the trained ARIA story adapter (Mistral 7B LoRA)

The fine-tune saves a LoRA adapter at:

```text
/kaggle/working/aria-story-mistral-7b-lora
```

## 1. Download the adapter from Kaggle

After the notebook finishes, grab the adapter from the notebook's **Output**
tab (under the version you ran). Build `adapter_model.safetensors`,
`adapter_config.json`, and the tokenizer files. You can also pull it from the
CLI once the run completes:

```bash
kaggle kernels output mariazaidi77/aria-fine-tune-mistral-story -p ./aria-story-mistral-7b-lora
```

Keep it private. Do not publish the notebook's secrets.

## 2. Load it for a quick Python test (optional)

Works best with the same 4-bit QLoRA setup used for training:

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel

base = "mistralai/Mistral-7B-Instruct-v0.2"
adapter_dir = "./aria-story-mistral-7b-lora"

qlora = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
)

tok = AutoTokenizer.from_pretrained(base)
model = AutoModelForCausalLM.from_pretrained(base, quantization_config=qlora, device_map="auto")
model = PeftModel.from_pretrained(model, adapter_dir)

context = '{ "user_goal": "explain sales by category", "kpis": [ ... ] }'
prompt = (
    "You are ARIA's Insight Agent. Write only a concise business story for a "
    "non-technical manager. Start with the headline finding, explain the leading "
    "hypothesis, mention anomalies if relevant, and stay under 250 words.\n\n"
    f"Context:\n{context}"
)

enc = tok(f"<s>[INST] {prompt} [/INST]", return_tensors="pt").to(model.device)
out = model.generate(**enc, max_new_tokens=400, do_sample=True, temperature=0.4)
print(tok.decode(out[0], skip_special_tokens=True))
```

## 3. Use it in ARIA's Insight Agent (recommended: Ollama)

ARIA's local backend talks to Ollama, so the simplest integration is to merge
the adapter into the base model, convert to GGUF, and create an Ollama model.

### a) Merge + export to GGUF

```bash
# inside Kaggle (has the GPU) or a machine with enough RAM:
python -c "
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
base = 'mistralai/Mistral-7B-Instruct-v0.2'
model = AutoModelForCausalLM.from_pretrained(base, torch_dtype='auto')
model = PeftModel.from_pretrained(model, './aria-story-mistral-7b-lora')
merged = model.merge_and_unload()
merged.save_pretrained('./aria-story-merged')
tokenizer = AutoTokenizer.from_pretrained(base)
tokenizer.save_pretrained('./aria-story-merged')
"
git clone https://github.com/ggerganov/llama.cpp.git && cd llama.cpp
# build with CMake, then:
python convert_hf_to_gguf.py ../aria-story-merged --outfile aria-story-f16.gguf
./llama-quantize aria-story-f16.gguf aria-story-q4_k_m.gguf Q4_K_M
```

### b) Create the Ollama model

```bash
ollama create aria-story -f - <<'EOF'
FROM ./aria-story-q4_k_m.gguf
TEMPLATE """<s>[INST] {{ .Prompt }} [/INST]"""
PARAMETER temperature 0.4
PARAMETER num_predict 400
EOF
# test it
ollama run aria-story "You are ARIA's Insight Agent. Write only a concise business story for a non-technical manager. ..."
```

### c) Point ARIA's Insight Agent at it

In `llm_provider.py`, change the local `story` model to the fine-tuned one
(leave `sql` / `suggest` / `semi` alone so SQL/schema behavior is unchanged):

```python
"models": {
    "sql": "sqlcoder:7b",
    "story": "aria-story",      # was: "aria-goal"
    "suggest": "aria-goal",
    "semi": "qwen3:4b",
},
```

Start ARIA, choose **Local LLM**, and the `Insight Agent` story output will come
from the Mistral 7B model fine-tuned on retail/sales storytelling only. SQL
generation and schema extraction stay untouched, per the ARIA scope.

## Security notes

- The adapter is model weights only; no Kaggle token or Groq key is in it.
- Keep `kaggle_credentials.local.sh` and `.env` local-only and never upload them.