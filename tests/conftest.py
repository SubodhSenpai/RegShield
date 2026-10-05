"""Keep each test away from this machine's settings (environment variables, refreshed price
list) and from global export and SDK-instrumentation state left by another test."""

import os

import pytest


@pytest.fixture(scope="session")
def _empty_cache_dir(tmp_path_factory):
    return str(tmp_path_factory.mktemp("regshield-cache"))


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, _empty_cache_dir):
    for name in list(os.environ):
        if name.startswith("REGSHIELD_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("REGSHIELD_CACHE_DIR", _empty_cache_dir)
    saved = dict(os.environ)  # an env_file writes to os.environ directly
    yield
    from regression_shield import config
    from regression_shield.export import stop_exporting
    from regression_shield.instrument import uninstrument

    stop_exporting()
    uninstrument()
    os.environ.clear()
    os.environ.update(saved)
    config.env_file_variables.clear()
    config._loaded_env_files.clear()
    config._log_level_applied = False
