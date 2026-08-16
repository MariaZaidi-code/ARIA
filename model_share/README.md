# Sharing the aria-* local LLM models

The three `aria-*` models are fine-tuned locally and are NOT on any registry, so
your mates cannot `ollama pull` them. They must be given the model files.

## For you (the sharer)

1. Run `copy_models.ps1` (PowerShell, from this folder). It copies the model
   blobs out of your Ollama store into this folder:
   - `aria-goal.gguf`          (~1 GB, full merged fine-tune)
   - `base-4b.gguf`            (~4 GB, shared base for sql + story)
   - `sql-adapter.gguf`        (LoRA, ~100 MB)
   - `story-adapter.gguf`      (LoRA, ~100 MB)
2. Zip this whole folder (the 3 `Modelfile-*` files + the 4 gguf files +
   this README) and send it (Google Drive / WeTransfer / USB).

## For your mate

1. Install Ollama from https://ollama.com and make sure it is running
   (`ollama serve`).
2. Unzip the folder. From inside it, create the models:

   ```
   ollama create aria-goal -f Modelfile-goal
   ollama create aria-sql-mistral -f Modelfile-sql
   ollama create aria-story-mistral -f Modelfile-story
   ```

   (Only `aria-goal` is needed for the schema agent; the other two are for the
   goal/insight agents.)
3. Set up the app:

   ```
   pip install -r requirements.txt
   copy .env.example .env        # local provider needs no API key
   uvicorn app:app
   ```

4. In the UI, choose the **Local** provider. The schema agent will use
   `aria-goal` for schema reasoning; generation takes ~1-3 minutes on a normal
   laptop.

## Notes

- The Modelfiles use relative `FROM ./...` paths, so they work on Windows,
  macOS, and Linux regardless of where the files are unzipped.
- The base blob is shared by `aria-sql-mistral` and `aria-story-mistral`, so it
  is only sent once.