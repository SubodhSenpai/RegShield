import os
from dotenv import load_dotenv

load_dotenv()


class EvalConfig:
    """Central configuration for the RegressionShield evaluation framework.
    
    All thresholds and credentials are configurable via environment variables,
    with sensible defaults for demo and development environments.
    """

    # --- API Endpoints & Credentials ---
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai")

    # --- Target Evaluation Model & Free Fallback Cascade ---
    # Using verified, high-performing free models for scoring and live agent actions
    JUDGE_MODEL = os.getenv("JUDGE_MODEL", "minimax/minimax-m2.7:free")

    # Ordered list of free fallback models on OpenRouter.
    # When a model encounters rate limit (HTTP 429), provider daily quotas (RPD),
    # or temporary downtime, the framework automatically cascades down this list.
    FREE_FALLBACK_MODELS = [
        "minimax/minimax-m2.7:free",
        "minimax/minimax-m3:free",
        "google/gemma-4-26b-a4b-it:free",
        "google/gemma-4-31b-it:free",
        "nvidia/nemotron-3.5-lightning:free",
        "liquid/lfm-2.5-2.6b:free",
        "inclusionai/ling-3.0-flash-fin:free",
        "dots-studio/dots-3-note-preview:free",
        "cohere/north-mini-code:free",
    ]

    @classmethod
    def get_fallback_models(cls) -> list:
        """Returns a deduplicated list of fallback models preserving priority order."""
        seen = set()
        models = []
        for m in [cls.JUDGE_MODEL] + cls.FREE_FALLBACK_MODELS:
            if m and m not in seen:
                seen.add(m)
                models.append(m)
        return models


    # --- Demo Mode ---
    # When True, uses deterministic mock scores instead of live API calls.
    # Defaults to True if no OPENROUTER_API_KEY is detected in environment.
    DEMO_MODE = os.getenv(
        "DEMO_MODE",
        "true" if not os.getenv("OPENROUTER_API_KEY") else "false"
    ).lower() in ("true", "1", "yes")


    # --- Agent Reasoning & Trajectory Thresholds ---
    MIN_TOOL_SELECTION_SCORE = float(os.getenv("MIN_TOOL_SELECTION_SCORE", "0.85"))
    MIN_ARGUMENT_CORRECTNESS_SCORE = float(os.getenv("MIN_ARGUMENT_CORRECTNESS_SCORE", "0.85"))
    MIN_ORDER_ACCURACY_SCORE = float(os.getenv("MIN_ORDER_ACCURACY_SCORE", "1.00"))
    MIN_TRAJECTORY_EFFICIENCY = float(os.getenv("MIN_TRAJECTORY_EFFICIENCY", "0.70"))
    MIN_FAITHFULNESS_SCORE = float(os.getenv("MIN_FAITHFULNESS_SCORE", "0.70"))
    MAX_ALLOWED_REDUNDANT_STEPS = int(os.getenv("MAX_ALLOWED_REDUNDANT_STEPS", "1"))

    # --- Logging ---
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

