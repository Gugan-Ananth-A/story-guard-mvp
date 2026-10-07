# Story Guard

Phase 1 health report for one story. Development runs on a local model. No API key.

## Model

Ollama serves the model at `http://127.0.0.1:11434`. The narrative request sets `num_ctx` to **8192**. That is the context for this sprint. The model's native long window stays unused.

| Role | Tag | Size |
| --- | --- | --- |
| Default | `qwen3.5:4b` | about 3.4 GB |
| Fallback | `phi4-mini` | about 2.5 GB |

`phi4-mini` uses the same `num_ctx` of 8192. Pull it only when `qwen3.5:4b` will not stay resident with the editor open.

Load one model at a time. Do not load both.

```bash
ollama pull qwen3.5:4b
python scripts/ollama_smoke.py
```

The smoke script targets `qwen3.5:4b`, sends `num_ctx` 8192 on the request, and prints one JSON object.
