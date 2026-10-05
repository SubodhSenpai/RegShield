# Local and self-hosted models

RegShield works the same whether you pay for an API or run models yourself. Its checks need no model at all. Models come in at two places, and each can be local or paid, as you prefer:

- **Your agent.** RegShield records what the agent does, whichever model it calls: OpenAI, Anthropic, Gemini, OpenRouter, or a model on your own GPU.
- **The LLM judge (optional).** This is the only model call RegShield makes itself. It works with any OpenAI-compatible server, including one on your own machine, without an API key.

You can mix them. For example, run the agent on a paid API and judge it with a free local model, or develop on a local model and ship on a paid one.

## 1. Run a model on your machine with Ollama

Install [Ollama](https://ollama.com):

| System | Install |
|---|---|
| Windows | Download the installer from [ollama.com/download](https://ollama.com/download) and run it. Ollama keeps running in the background. |
| macOS | Download the app from [ollama.com/download](https://ollama.com/download), or `brew install ollama` and then `ollama serve`. |
| Linux | `curl -fsSL https://ollama.com/install.sh \| sh` (it starts as a service) |
| Docker | `docker run -d --gpus=all -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama` (leave out `--gpus=all` without an NVIDIA GPU) |

Download a model, then check that the server answers:

```bash
ollama pull qwen2.5:7b                  # or qwen2.5:3b for a GPU with 4 GB
ollama list                             # the models you have
curl http://localhost:11434/v1/models   # the OpenAI-compatible API RegShield uses
```

| Model size | GPU memory needed (roughly) | Good for |
|---|---|---|
| 3B (`qwen2.5:3b`, `llama3.2:3b`) | 2.5 to 3 GB | Simple agents and short traces; fits a 4 GB laptop GPU |
| 7B to 8B (`qwen2.5:7b`, `llama3.1:8b`) | 5 to 6 GB | Most agents, and steadier judge verdicts |
| 14B and up | 10 GB or more | Long traces and harder judgments |

Without a GPU, models run on the CPU, only more slowly. For agents that call tools, pick a model that supports tool calling, such as Qwen 2.5, Llama 3.1 or later, or Mistral NeMo. Ollama unloads an idle model after a few minutes, freeing the GPU (`ollama stop <model>` does it now).

Ollama serves two APIs on `http://localhost:11434`: an OpenAI-compatible one at `/v1`, and an Anthropic-compatible one.

## 2. Use it as the LLM judge

Put the server and model in your project's configuration (`pyproject.toml` or `regshield.toml`). A server on your own machine or network needs no API key:

```toml
[tool.regshield]
llm_judge = true
judge_base_url = "http://localhost:11434/v1"
judge_model = "qwen2.5:7b"
judge_timeout = 120     # seconds; a local model can be slower than a hosted API
```

`regshield eval` and `evaluate_trace` now ask that model to judge each trace. To try it once without the config file:

```bash
regshield eval scenarios.json --llm-judge --base-url http://localhost:11434/v1 --model qwen2.5:7b --judge-timeout 120
```

Environment variables override the file: `REGSHIELD_JUDGE_BASE_URL`, `REGSHIELD_JUDGE_MODEL`, `REGSHIELD_JUDGE_TIMEOUT` and `REGSHIELD_LLM_JUDGE` (the older `OPENAI_BASE_URL` and `JUDGE_MODEL` work too). They can live in a `.env` file your config loads with `env_file = ".env"`. `regshield config show` prints the judge RegShield would use. Step-by-step recipes for everything on this page, including CI and troubleshooting, are in the cookbook's [Local models with Ollama](cookbook.md#local-models-with-ollama).

RegShield sends no key to these servers:

- this machine (`localhost`, `127.0.0.1`);
- a private network (`192.168.x.x`, `10.x.x.x`);
- names like `gpu-box.local`, or a Docker or Kubernetes service such as `http://ollama:11434/v1`.

A hosted API still needs `OPENROUTER_API_KEY` or `OPENAI_API_KEY`. If your own server asks for a key (vLLM started with `--api-key`), pass it with `--api-key` or `OPENAI_API_KEY`.

## 3. Run your agent on a local model

Point the SDK or framework at Ollama. RegShield records the agent exactly as it would with a paid API: tool calls, token usage, guards, `instrument()` and export all work the same.

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

The Gemini SDK only talks to Google; for a local model, use one of the clients above.

## 4. Models on your own servers

Any server with an OpenAI-compatible API works the same way. Only the address and the model name change:

| Server | Start it | Base URL |
|---|---|---|
| Ollama on a GPU server | `OLLAMA_HOST=0.0.0.0 ollama serve` | `http://gpu-server:11434/v1` |
| vLLM | `vllm serve Qwen/Qwen2.5-7B-Instruct` | `http://gpu-server:8000/v1` |
| LM Studio | Developer tab, then *Start server* | `http://localhost:1234/v1` |
| llama.cpp | `llama-server -m qwen2.5-7b-instruct-q4_k_m.gguf --port 8080` | `http://localhost:8080/v1` |
| Docker Compose | a service named `ollama` | `http://ollama:11434/v1` |

Use the server's model name: `qwen2.5:7b` for Ollama, `Qwen/Qwen2.5-7B-Instruct` for vLLM. Ollama has no login, so keep it on a private network rather than exposing it to the internet.

## 5. Costs with local models

- **Local models are free per token.** Ollama-style names (`qwen2.5:7b`, `llama3.1:8b-instruct-q4_K_M`) and models served through Ollama, LM Studio, llamafile or your own vLLM cost $0 in `report.cost`, with `price_source: "local"`.
- **Estimating your GPU cost:** give the model a price per million tokens, and that price wins:

  ```toml
  [tool.regshield.pricing.models]
  "qwen2.5*" = { input = 0.05, output = 0.10 }
  ```

- **Names that don't look local,** such as `Qwen/Qwen2.5-7B-Instruct` served by vLLM, may be priced like the same model at a hosted provider, or not at all. `regshield pricing show <model>` tells you which; set your own price when it matters.
- **Budgets:** `max_cost_usd` can't stop a free model, so cap local runs with `max_tokens` or `max_llm_calls`.
- **Mixing models:** each call is priced on its own. A run that uses a local model for most steps and a paid API for some shows only the paid part.
