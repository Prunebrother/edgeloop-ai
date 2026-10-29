# Character and model boundaries

Evelyn, Daisy, Celeste and Nova identities, Modelfiles, lore and personalities have not been edited. The artwork manifest is unchanged; art files are excluded pending permission. Existing missing-art presentation is used, with no replacement characters or generated portraits. Older aliases and generated development model variants may not map one-to-one to these source directory names. Do not overwrite an existing alias just to match this guide.

No model weights, local Ollama manifests/blobs or private model directories are required or shipped. The definitions below reference registry tags rather than developer-specific files. Prunebrother confirmed authorship and authorized AGPL-3.0-only publication of the character definitions and lore on 2026-10-29. This confirmation does not cover artwork or model weights. Locally installing a model is a separate explicit action requiring disk/RAM/VRAM and network access.

| Suggested install alias | Base model reference | Source |
| --- | --- | --- |
| `celeste-narrative-v1:latest` | `huihui_ai/qwen3.5-abliterated:9b` | `characters/models/celeste-narrative-v1/Modelfile` |
| `celeste-narrative-v2:latest` | `huihui_ai/qwen3.5-abliterated:9b` | `characters/models/celeste-narrative-v2/Modelfile` |
| `daisy:latest` | `qwen3:8b` | `characters/models/daisy/Modelfile` |
| `daisy-lite:latest` | `huihui_ai/qwen3.5-abliterated:9b` | `characters/models/daisy-lite/Modelfile` |
| `daisy-narrative-v1:latest` | `huihui_ai/qwen3.5-abliterated:9b` | `characters/models/daisy-narrative-v1/Modelfile` |
| `evelyn:latest` | `qwen3:8b` | `characters/models/evelyn/Modelfile` |
| `evelyn-lite:latest` | `huihui_ai/qwen3.5-abliterated:9b` | `characters/models/evelyn-lite/Modelfile` |
| `evelyn-lite-candidate:latest` | `huihui_ai/qwen3.5-abliterated:9b` | `characters/models/evelyn-lite-candidate/Modelfile` |
| `evelyn-narrative-v1:latest` | `huihui_ai/qwen3.5-abliterated:9b` | `characters/models/evelyn-narrative-v1/Modelfile` |
| `mira:latest` | `unknown` | `characters/models/mira/Modelfile` |
| `nova-narrative-v1:latest` | `huihui_ai/qwen3.5-abliterated:9b` | `characters/models/nova-narrative-v1/Modelfile` |

For example, on the intended existing Ollama endpoint, after reviewing terms and checking that the alias is not already in use:

```bash
OLLAMA_HOST=127.0.0.1:11435 ollama list
OLLAMA_HOST=127.0.0.1:11435 ollama pull huihui_ai/qwen3.5-abliterated:9b
OLLAMA_HOST=127.0.0.1:11435 ollama create nova-narrative-v1 -f characters/models/nova-narrative-v1/Modelfile
```

Use the matching source path and intended alias for Evelyn, Daisy or Celeste. `qwen3:8b` definitions need that base instead. Record `ollama --version`, the installed model digest from `/api/tags` and the Modelfile hash when reporting results. Select the installed alias in Chat. Prompt compatibility, context support and performance need local verification; successful creation is not a safety test. Do not share `ollama show` output without checking it for private prompts or paths.
