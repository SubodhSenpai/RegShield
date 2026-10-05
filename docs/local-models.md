# Local and self-hosted models

RegShield's checks need no model. Models come in at two places, each local or paid:

- **Your agent.** Recorded the same way on OpenAI, Anthropic, Gemini, OpenRouter or your own GPU.
- **The LLM judge (optional).** Any OpenAI-compatible server, local ones without an API key.

Mix them freely, e.g. a paid agent judged by a free local model.

## 1. Run a model on your machine with Ollama

Install [Ollama](https://ollama.com):

| System | Install |
|---|---|
| Windows | Run the installer from [ollama.com/download](https://ollama.com/download). It runs in the background. |
| macOS | Download the app from [ollama.com/download](https://ollama.com/download), or `brew install ollama` and then `ollama serve`. |
| Linux | `curl -fsSL https://ollama.com/install.sh \| sh` (it starts as a service) |
| Docker | `docker run -d --gpus=all -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama` (leave out `--gpus=all` without an NVIDIA GPU) |

Download a model and check the server answers:

```bash
ollama pull qwen2.5:7b                  # or qwen2.5:3b for a GPU with 4 GB
ollama list                             # the models you have
curl http://localhost:11434/v1/models   # the OpenAI-compatible API RegShield uses
```

| Model size | GPU memory needed (roughly) | Good for |
|---|---|---|
| 3B (`qwen2.5:3b`, `llama3.2:3b`) | 2.5 to 3 GB | Short traces; fits a 4 GB laptop GPU |
| 7B to 8B (`qwen2.5:7b`, `llama3.1:8b`) | 5 to 6 GB | Most agents; steadier verdicts |
| 14B and up | 10 GB or more | Long traces and harder judgments |

- No GPU? Models run on the CPU, more slowly.
- For tool-calling agents, use Qwen 2.5, Llama 3.1+ or Mistral NeMo.
- Idle models unload after a few minutes (`ollama stop <model>` frees the GPU now).
- Ollama serves an OpenAI-compatible API at `/v1` and an Anthropic-compatible one.

## 2. Use it as the LLM judge

Set the server and model in `pyproject.toml` or `regshield.toml`. Local servers need no API key:

```toml
[tool.regshield]
llm_judge = true
judge_base_url = "http://localhost:11434/v1"
judge_model = "qwen2.5:7b"
judge_timeout = 120     # seconds; a local model can be slower than a hosted API
```

To try it once without the config file:

```bash
regshield eval scenarios.json --llm-judge --base-url http://localhost:11434/v1 --model qwen2.5:7b --judge-timeout 120
```

Environment variables (`REGSHIELD_JUDGE_BASE_URL`, `REGSHIELD_JUDGE_MODEL`...) override the file. `regshield config show` prints the judge in use. Step-by-step recipes: [Local models with Ollama](cookbook.md#local-models-with-ollama).

RegShield sends no key to these servers:

- this machine (`localhost`, `127.0.0.1`);
- a private network (`192.168.x.x`, `10.x.x.x`);
- names like `gpu-box.local`, or a Docker or Kubernetes service such as `http://ollama:11434/v1`.

Hosted APIs need `OPENROUTER_API_KEY` or `OPENAI_API_KEY`. If your server checks keys (vLLM `--api-key`), pass `--api-key`.

## 3. Run your agent on a local model

Point the SDK or framework at Ollama. Recording, guards and export work as with a paid API.

```python
# OpenAI SDK (the SDK wants a key; Ollama ignores it)
from openai import OpenAI
client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

# Anthropic SDK: Ollama also speaks Anthropic's API
from anthropic import Anthropic
client = Anthropic(base_url="http://localhost:11434", api_key="ollama")

# LangChain / LangGraph
from langchain_openai import ChatOpenAI
model = ChatOpenAI(model="qwen2.5:7b", base_url="http://localhost:11434/v1", api_key="ollama")

# smolagents
from smolagents import OpenAIServerModel
model = OpenAIServerModel(model_id="qwen2.5:7b", api_base="http://localhost:11434/v1", api_key="ollama")
```

The Gemini SDK only talks to Google; use another client for local models.

## 4. Models on your own servers

Any OpenAI-compatible server works. Only the address and model name change:

| Server | Start it | Base URL |
|---|---|---|
| Ollama on a GPU server | `OLLAMA_HOST=0.0.0.0 ollama serve` | `http://gpu-server:11434/v1` |
| vLLM | `vllm serve Qwen/Qwen2.5-7B-Instruct` | `http://gpu-server:8000/v1` |
| LM Studio | Developer tab, then *Start server* | `http://localhost:1234/v1` |
| llama.cpp | `llama-server -m qwen2.5-7b-instruct-q4_k_m.gguf --port 8080` | `http://localhost:8080/v1` |
| Docker Compose | a service named `ollama` | `http://ollama:11434/v1` |

Use the server's model name. Ollama has no login: keep it on a private network.

## 5. Costs with local models

- **Local models are free per token** (`price_source: "local"`).
- **GPU cost:** give the model a price per million tokens:

  ```toml
  [tool.regshield.pricing.models]
  "qwen2.5*" = { input = 0.05, output = 0.10 }
  ```

- **Names that don't look local** (`Qwen/Qwen2.5-7B-Instruct` on vLLM) may get a hosted price, or none. Check with `regshield pricing show <model>`.
- **Budgets:** `max_cost_usd` can't stop a free model; cap it with `max_tokens` or `max_llm_calls`.
- **Mixed runs** show only the paid calls' cost.
