"""Project settings for RegShield, so pytest and ``regshield eval`` in CI share them.

Settings come from, highest priority first:

1. arguments: ``evaluate_trace(..., min_tool_selection=0.9)`` or ``--min-tool-selection 0.9``
2. environment variables (judge settings only: ``JUDGE_MODEL``, ``JUDGE_TIMEOUT``,
   ``OPENROUTER_BASE_URL`` / ``OPENAI_BASE_URL``, and the API keys)
3. a config file: ``regshield.toml``, or a ``[tool.regshield]`` table in ``pyproject.toml``
4. built-in defaults

The file is found by looking in the current directory and then each parent, stopping
at the first directory that has a ``regshield.toml`` or a ``pyproject.toml``. Set
``REGSHIELD_CONFIG`` to a file path to use that file instead, or to an empty
string to ignore config files. API keys don't belong in files: keep them in
environment variables or CI secrets.

    [tool.regshield]
    min_tool_selection = 0.9
    judge_model = "gpt-4.1-mini"
    judge_timeout = 60
    min_pass_rate = 0.8

    [tool.regshield.pricing.models]
    "my-finetune*" = { input = 1.0, output = 4.0 }   # USD per 1M tokens

    [tool.regshield.pricing.tools]
    web_search = 0.005                              # USD per call
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

THRESHOLD_KEYS = ("min_tool_selection", "min_argument_correctness", "min_call_ordering",
                  "min_step_efficiency", "min_reasoning_faithfulness")
DEFAULTS: dict[str, Any] = {
    "min_tool_selection": 0.85,
    "min_argument_correctness": 0.85,
    "min_call_ordering": 1.0,
    "min_step_efficiency": 0.70,
    "min_reasoning_faithfulness": 0.85,
    "llm_judge": False,
    "judge_model": None,
    "judge_base_url": None,
    "judge_timeout": 30.0,
    "judge_on_error": "fail",
    "min_pass_rate": 1.0,
    "pricing": None,
}
_FILE_NAMES = ("regshield.toml", "pyproject.toml")
_cache: dict[tuple[str, float], dict[str, Any]] = {}
_has_table: dict[tuple[str, float], bool] = {}


def _pyproject_has_regshield(path: str) -> bool:
    """True if a pyproject.toml has a [tool.regshield] table (cached until the file changes)."""
    key = (path, os.path.getmtime(path))
    if key not in _has_table:
        try:
            _has_table[key] = "regshield" in _load_toml(path).get("tool", {})
        except (OSError, ValueError) as err:
            logger.warning("Could not read %s: %s", path, err)
            _has_table[key] = False
    return _has_table[key]


def _load_toml(path: str) -> dict[str, Any]:
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # pragma: no cover - Python 3.10
        import tomli as tomllib
    with open(path, "rb") as f:
        return tomllib.load(f)


def find_config_file(start: str | None = None) -> str | None:
    """The config file in effect for ``start`` (default: the current directory), or None."""
    explicit = os.environ.get("REGSHIELD_CONFIG")
    if explicit is not None:
        return explicit or None
    directory = os.path.abspath(start or os.getcwd())
    while True:
        for name in _FILE_NAMES:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                if name == "pyproject.toml" and not _pyproject_has_regshield(candidate):
                    return None  # the project root, without RegShield settings
                return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent


def validate_config(settings: dict[str, Any], source: str = "config") -> dict[str, Any]:
    """Check settings read from a file: known keys, sensible values."""
    from regression_shield.core.cost import validate_pricing

    unknown = sorted(set(settings) - set(DEFAULTS))
    if unknown:
        secret = [key for key in unknown if "key" in key.lower() or "token" in key.lower()]
        hint = (" Keep API keys in environment variables (OPENROUTER_API_KEY / OPENAI_API_KEY), not in files."
                if secret else "")
        raise ValueError(f"{source}: unknown setting(s) {unknown}. Valid: {', '.join(DEFAULTS)}.{hint}")
    for key in (*THRESHOLD_KEYS, "min_pass_rate"):
        value = settings.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1):
            raise ValueError(f"{source}: {key} must be a number from 0 to 1, got {value!r}")
    if "llm_judge" in settings and not isinstance(settings["llm_judge"], bool):
        raise ValueError(f"{source}: llm_judge must be true or false")
    timeout = settings.get("judge_timeout")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0):
        raise ValueError(f"{source}: judge_timeout must be a number of seconds > 0, got {timeout!r}")
    if settings.get("judge_on_error", "fail") not in ("fail", "pass"):
        raise ValueError(f"{source}: judge_on_error must be \"fail\" or \"pass\"")
    for key in ("judge_model", "judge_base_url"):
        if key in settings and not isinstance(settings[key], str):
            raise ValueError(f"{source}: {key} must be a string")
    if "pricing" in settings:
        validate_pricing(settings["pricing"])
    return settings


def load_config(path: str | None = None) -> dict[str, Any]:
    """Settings from the config file in effect (validated), or ``{}`` when there is none."""
    path = path or find_config_file()
    if not path:
        return {}
    try:
        mtime = os.path.getmtime(path)
    except OSError as err:
        raise ValueError(f"Config file {path} can't be read: {err}") from err
    cached = _cache.get((path, mtime))
    if cached is not None:
        return cached
    try:
        data = _load_toml(path)
    except ValueError as err:  # tomllib.TOMLDecodeError is a ValueError
        raise ValueError(f"Config file {path} is not valid TOML: {err}") from err
    settings = data.get("tool", {}).get("regshield", {}) if path.endswith("pyproject.toml") else data
    validate_config(settings, source=path)
    logger.debug("Loaded settings from %s: %s", path, sorted(settings))
    _cache[(path, mtime)] = settings
    return settings


def setting(name: str, explicit: Any = None, config: dict[str, Any] | None = None) -> Any:
    """``explicit`` if given, else the config file's value, else the built-in default."""
    if explicit is not None:
        return explicit
    settings = load_config() if config is None else config
    value = settings.get(name)
    return DEFAULTS[name] if value is None else value
