"""Model settings shared by the examples: any OpenAI-compatible chat endpoint.

Defaults to a local Ollama model (`ollama pull qwen2.5:3b`). To use another
provider, set EXAMPLES_BASE_URL, EXAMPLES_MODEL and EXAMPLES_API_KEY, e.g.
EXAMPLES_BASE_URL=https://api.openai.com/v1 EXAMPLES_MODEL=gpt-4o-mini.
"""

import os

BASE_URL = os.environ.get("EXAMPLES_BASE_URL", "http://127.0.0.1:11434/v1")
MODEL = os.environ.get("EXAMPLES_MODEL", "qwen2.5:3b")
API_KEY = os.environ.get("EXAMPLES_API_KEY", "ollama")  # Ollama ignores the key


def chat_model():
    """A LangChain chat model."""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=MODEL, base_url=BASE_URL, api_key=API_KEY, temperature=0)


def smolagents_model():
    """A smolagents model."""
    from smolagents import OpenAIServerModel

    return OpenAIServerModel(model_id=MODEL, api_base=BASE_URL, api_key=API_KEY, temperature=0)


def openai_client():
    """A plain OpenAI SDK client, for agents without a framework."""
    from openai import OpenAI

    return OpenAI(base_url=BASE_URL, api_key=API_KEY)
