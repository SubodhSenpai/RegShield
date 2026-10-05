"""Project settings for RegShield, in one place.

Every setting can live in a config file (``regshield.toml``, or a ``[tool.regshield]``
table in ``pyproject.toml``), and every one can be overridden by an environment
variable named ``REGSHIELD_<SETTING>`` (``REGSHIELD_JUDGE_MODEL``,
``REGSHIELD_MIN_TOOL_SELECTION``...). Highest priority first:

1. arguments: ``evaluate_trace(..., min_tool_selection=0.9)`` or ``--min-tool-selection 0.9``
2. environment variables, including those in the ``env_file`` the config names
3. the config file
4. built-in defaults

The file is found by looking in the current directory and then each parent, stopping
at the first directory that has a ``regshield.toml`` or a ``pyproject.toml``. Set
``REGSHIELD_CONFIG`` to a file path to use that file instead, or to an empty
string to ignore config files.

API keys don't belong in the config file, which you commit. Keep them in the
environment, or in a ``.env`` file you don't commit, named by ``env_file = ".env"``.
``regshield config init`` writes a file with every setting; ``regshield config show``
lists the settings in effect and where each one comes from.

    [tool.regshield]
    env_file = ".env"
    min_tool_selection = 0.9
    judge_model = "qwen2.5:7b"
    judge_base_url = "http://localhost:11434/v1"

    [tool.regshield.pricing.models]
    "my-finetune*" = { input = 1.0, output = 4.0 }   # USD per 1M tokens
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

THRESHOLD_KEYS = ("min_tool_selection", "min_argument_correctness", "min_call_ordering",
                  "min_step_efficiency", "min_reasoning_faithfulness")

# name: (default, type, what it does)
SETTINGS: dict[str, tuple[Any, type, str]] = {
    "min_tool_selection": (0.85, float, "minimum tool selection score (F1)"),
    "min_argument_correctness": (0.85, float, "minimum argument correctness"),
    "min_call_ordering": (1.0, float, "minimum call ordering score"),
    "min_step_efficiency": (0.70, float, "minimum step efficiency"),
    "min_reasoning_faithfulness": (0.85, float, "minimum reasoning faithfulness"),
    "min_pass_rate": (1.0, float, "share of repeated runs that must pass"),
    "llm_judge": (False, bool, "have an LLM judge every trace"),
    "judge_model": (None, str, "the judge's model"),
    "judge_base_url": (None, str, "the judge's OpenAI-compatible endpoint (default: OpenRouter)"),
    "judge_timeout": (30.0, float, "seconds to wait for each verdict"),
    "judge_on_error": ("fail", str, "when the judge can't answer: fail or pass"),
    "pricing": (None, dict, "your prices: [pricing.models] (USD per 1M tokens) and [pricing.tools] (USD per call)"),
    "price_list": (None, str, "a list prices file to use instead of the bundled one"),
    "log_level": (None, str, "print logs at this level: debug, info or warning"),
    "env_file": (None, str, "a .env file whose variables (API keys...) are loaded"),
    "export_otlp_endpoint": (None, str, "export_traces(): an OpenTelemetry OTLP/HTTP collector"),
    "export_jsonl_path": (None, str, "export_traces(): a JSON-lines file"),
    "export_http_url": (None, str, "export_traces(): a URL that receives JSON events"),
    "export_service_name": ("regshield-agent", str, "export_traces(): the OpenTelemetry service name"),
    "export_sample_rate": (1.0, float, "export_traces(): share of healthy runs exported"),
    "export_keep_errors": (True, bool, "export_traces(): always export runs where something went wrong"),
    "export_max_runs_per_minute": (None, int, "export_traces(): cap on exported runs"),
    "export_capture_content": (False, bool, "export_traces(): include prompts, arguments and results"),
}
DEFAULTS: dict[str, Any] = {name: spec[0] for name, spec in SETTINGS.items()}

# Older environment variable names that still work
ENV_ALIASES = {"judge_model": ("JUDGE_MODEL",), "judge_timeout": ("JUDGE_TIMEOUT",),
               "log_level": ("REGSHIELD_LOG",)}
# Paths in the config file are relative to the file itself
_PATH_KEYS = ("price_list", "env_file", "export_jsonl_path")
_LOG_LEVELS = ("debug", "info", "warning", "error", "critical")
_FILE_NAMES = ("regshield.toml", "pyproject.toml")
_cache: dict[tuple[str, float], dict[str, Any]] = {}
_has_table: dict[tuple[str, float], bool] = {}
_loaded_env_files: dict[str, float] = {}  # env file -> mtime it was loaded at
env_file_variables: dict[str, str] = {}   # variable -> the env file that set it
_log_level_applied = False


def env_names(name: str) -> tuple[str, ...]:
    """The environment variables that set ``name``, most specific first."""
    return tuple(dict.fromkeys((f"REGSHIELD_{name.upper()}", *ENV_ALIASES.get(name, ()))))


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


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_config(settings: dict[str, Any], source: str = "config") -> dict[str, Any]:
    """Check settings read from a file or the environment: known names, sensible values."""
    from regression_shield.core.cost import validate_pricing

    unknown = sorted(set(settings) - set(SETTINGS))
    if unknown:
        secret = [key for key in unknown if any(word in key.lower() for word in ("key", "token", "secret", "header"))]
        hint = (" Keep API keys in environment variables or an env_file (OPENROUTER_API_KEY / OPENAI_API_KEY; "
                "export headers in REGSHIELD_EXPORT_HTTP_HEADERS), not in this file." if secret else "")
        raise ValueError(f"{source}: unknown setting(s) {unknown}. Valid: {', '.join(SETTINGS)}.{hint}")
    for key in (*THRESHOLD_KEYS, "min_pass_rate", "export_sample_rate"):
        value = settings.get(key)
        if value is not None and (not _is_number(value) or not 0 <= value <= 1):
            raise ValueError(f"{source}: {key} must be a number from 0 to 1, got {value!r}")
    for key in ("llm_judge", "export_keep_errors", "export_capture_content"):
        if key in settings and not isinstance(settings[key], bool):
            raise ValueError(f"{source}: {key} must be true or false")
    timeout = settings.get("judge_timeout")
    if timeout is not None and (not _is_number(timeout) or timeout <= 0):
        raise ValueError(f"{source}: judge_timeout must be a number of seconds > 0, got {timeout!r}")
    if settings.get("judge_on_error", "fail") not in ("fail", "pass"):
        raise ValueError(f"{source}: judge_on_error must be \"fail\" or \"pass\"")
    runs = settings.get("export_max_runs_per_minute")
    if runs is not None and (not isinstance(runs, int) or isinstance(runs, bool) or runs < 0):
        raise ValueError(f"{source}: export_max_runs_per_minute must be a whole number >= 0, got {runs!r}")
    for key in ("judge_model", "judge_base_url", "price_list", "env_file", "export_otlp_endpoint",
                "export_jsonl_path", "export_http_url", "export_service_name", "log_level"):
        if key in settings and not isinstance(settings[key], str):
            raise ValueError(f"{source}: {key} must be a string")
    if "log_level" in settings and settings["log_level"].lower() not in _LOG_LEVELS:
        raise ValueError(f"{source}: log_level must be one of {', '.join(_LOG_LEVELS)}")
    if "pricing" in settings:
        validate_pricing(settings["pricing"])
    return settings


def load_env_file(path: str) -> dict[str, str]:
    """Load ``KEY=value`` lines from a .env file into the environment. A variable already set
    in the environment keeps its value. A missing file is skipped (in CI the keys usually
    come from the environment). Returns the variables it set."""
    if not os.path.exists(path):
        logger.debug("env_file %s doesn't exist; skipped", path)
        return {}
    try:
        mtime = os.path.getmtime(path)
    except OSError as err:
        raise ValueError(f"env_file {path} can't be read: {err}") from err
    if _loaded_env_files.get(path) == mtime:
        return {}
    loaded: dict[str, str] = {}
    with open(path, encoding="utf-8-sig") as f:
        for number, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            name, separator, value = line.partition("=")
            name = name.strip()
            if not separator or not name.replace("_", "").isalnum():
                raise ValueError(f"{path}, line {number}: expected NAME=value")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].rstrip()  # a comment after an unquoted value
            # The real environment wins; a value this file set earlier follows the file
            if value and (name not in os.environ or env_file_variables.get(name) == path):
                os.environ[name] = value
                env_file_variables[name] = path
                loaded[name] = value
    _loaded_env_files[path] = mtime
    logger.debug("Loaded %d variable(s) from %s", len(loaded), path)
    return loaded


def load_config(path: str | None = None) -> dict[str, Any]:
    """Settings from the config file in effect (validated, paths made absolute), or ``{}``.
    Also loads the env_file it names (or ``REGSHIELD_ENV_FILE``)."""
    named_env_file = os.environ.get("REGSHIELD_ENV_FILE")
    if named_env_file:
        load_env_file(os.path.abspath(named_env_file))
    path = path or find_config_file()
    if not path:
        return {}
    try:
        mtime = os.path.getmtime(path)
    except OSError as err:
        raise ValueError(f"Config file {path} can't be read: {err}") from err
    cached = _cache.get((path, mtime))
    if cached is None:
        try:
            data = _load_toml(path)
        except ValueError as err:  # tomllib.TOMLDecodeError is a ValueError
            raise ValueError(f"Config file {path} is not valid TOML: {err}") from err
        settings = dict(data.get("tool", {}).get("regshield", {}) if path.endswith("pyproject.toml") else data)
        validate_config(settings, source=path)
        directory = os.path.dirname(os.path.abspath(path))
        for key in _PATH_KEYS:
            if settings.get(key):
                settings[key] = os.path.normpath(os.path.join(directory, os.path.expanduser(settings[key])))
        logger.debug("Loaded settings from %s: %s", path, sorted(settings))
        _cache[(path, mtime)] = cached = settings
    if cached.get("env_file"):
        load_env_file(cached["env_file"])
    return cached


def env_setting(name: str) -> Any:
    """The value of setting ``name`` from its environment variable, or None when unset."""
    found = env_source(name)
    return None if found is None else found[0]


def env_source(name: str) -> tuple[Any, str] | None:
    """``(value, variable)`` when an environment variable sets ``name``."""
    for variable in env_names(name):
        raw = os.environ.get(variable)
        if raw is not None and raw.strip():
            return _parse_env(name, raw.strip(), variable), variable
    return None


def _parse_env(name: str, raw: str, variable: str) -> Any:
    kind = SETTINGS[name][1]
    if kind is dict:
        raise ValueError(f"{variable}: {name} can only be set in the config file")
    value: Any = raw
    if kind is bool:
        if raw.lower() not in ("1", "0", "true", "false", "yes", "no", "on", "off"):
            raise ValueError(f"{variable}={raw!r}: use true or false")
        value = raw.lower() in ("1", "true", "yes", "on")
    elif kind in (int, float):
        try:
            value = kind(raw)
        except ValueError as err:
            raise ValueError(f"{variable}={raw!r}: must be a {'whole ' if kind is int else ''}number") from err
    elif name == "log_level" and raw.lower() not in _LOG_LEVELS:
        value = "debug"  # REGSHIELD_LOG=1 or =true has always meant debug
    validate_config({name: value}, source=variable)
    return value


def setting(name: str, explicit: Any = None, config: dict[str, Any] | None = None) -> Any:
    """``explicit`` if given, else the environment variable, else the config file's value,
    else the built-in default."""
    if explicit is not None:
        return explicit
    settings = load_config() if config is None else config  # also loads the env_file
    value = env_setting(name)
    if value is not None:
        return value
    value = settings.get(name)
    return DEFAULTS[name] if value is None else value


def setting_source(name: str, config: dict[str, Any] | None = None, config_path: str | None = None) -> tuple[Any, str]:
    """``(value, where it comes from)`` for ``regshield config show``."""
    settings = load_config() if config is None else config
    found = env_source(name)
    if found is not None:
        variable = found[1]
        origin = f" (from {os.path.basename(env_file_variables[variable])})" if variable in env_file_variables else ""
        return found[0], f"{variable}{origin}"
    if settings.get(name) is not None:
        return settings[name], os.path.basename(config_path) if config_path else "config file"
    return DEFAULTS[name], "default"


def apply_log_level(config: dict[str, Any] | None = None) -> None:
    """Turn on logs once, at the configured ``log_level`` (if any)."""
    global _log_level_applied
    if _log_level_applied:
        return
    _log_level_applied = True
    level = setting("log_level", None, config)
    if level:
        from regression_shield.log import enable_logging

        enable_logging(level)


CONFIG_TEMPLATE = '''\
# RegShield settings. Every setting is optional: uncomment the ones you need.
# Each can also come from an environment variable named REGSHIELD_<SETTING>
# (REGSHIELD_JUDGE_MODEL, REGSHIELD_MIN_TOOL_SELECTION...). Highest priority first:
# arguments and CLI flags, environment variables (and env_file), this file, defaults.
# In pyproject.toml, put the same lines under [tool.regshield].
# `regshield config show` lists the settings in effect and where each comes from.

# -- Secrets ---------------------------------------------------------------------
# API keys never go in this file. Keep them in the environment, or in a .env file
# you don't commit (see .env.example), and load it from here:
# env_file = ".env"

# -- Thresholds: a trace fails below these ------------------------------------
# min_tool_selection = 0.85
# min_argument_correctness = 0.85
# min_call_ordering = 1.0
# min_step_efficiency = 0.70
# min_reasoning_faithfulness = 0.85
# min_pass_rate = 1.0               # share of repeated runs ("traces") that must pass

# -- LLM judge -------------------------------------------------------------------
# llm_judge = false
# judge_base_url = "http://localhost:11434/v1"   # your own server (Ollama...) needs no key;
#                                                # default: OpenRouter, with OPENROUTER_API_KEY
# judge_model = "qwen2.5:7b"
# judge_timeout = 30                # seconds per verdict; give local models more
# judge_on_error = "fail"           # "pass" to ignore a judge that can't answer

# -- Cost ------------------------------------------------------------------------
# price_list = "prices.json"        # from `regshield pricing refresh --output prices.json`

# -- Export: rs.export_traces() with no arguments uses these -------------------
# export_otlp_endpoint = "http://localhost:4318"   # OpenTelemetry collector
# export_jsonl_path = "runs.jsonl"
# export_http_url = "https://monitoring.example.com/regshield"
# export_service_name = "regshield-agent"
# export_sample_rate = 1.0          # share of healthy runs exported
# export_keep_errors = true         # always export runs where something went wrong
# export_max_runs_per_minute = 600
# export_capture_content = false    # include prompts, arguments and results

# -- Logs ------------------------------------------------------------------------
# log_level = "info"                # debug, info or warning

# -- Your prices: keep these tables last ------------------------------------------
# [pricing.models]                  # USD per 1M tokens; * patterns allowed
# "my-finetune*" = { input = 1.0, output = 4.0 }
# "qwen2.5*" = { input = 0.05, output = 0.10 }   # to count what your own GPU costs
# [pricing.tools]                   # USD per call
# web_search = 0.005
'''

ENV_TEMPLATE = '''\
# RegShield secrets and per-machine settings. Copy this file to .env, fill it in,
# keep .env out of git, and add env_file = ".env" to regshield.toml.
# Variables already set in the environment win over this file.

# Keys for a hosted LLM judge (a judge on your own server needs none)
OPENROUTER_API_KEY=
OPENAI_API_KEY=

# Credentials for exporting runs, if your collector needs them
# OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer <token>
# REGSHIELD_EXPORT_HTTP_HEADERS=Authorization=Bearer <token>

# Any setting can be overridden here too, for this machine only:
# REGSHIELD_LLM_JUDGE=true
# REGSHIELD_JUDGE_BASE_URL=http://localhost:11434/v1
# REGSHIELD_JUDGE_MODEL=qwen2.5:7b
'''
