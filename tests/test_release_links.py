"""Install instructions point at the GitHub release of the version being built.

RegShield isn't on PyPI yet, so the docs install the wheel attached to a GitHub
release. A version bump must update those links, or the docs would keep
installing the old release. Delete test_nothing_installs_from_pypi once the
package is published there.
"""

import re
from pathlib import Path

import pytest

import regression_shield

ROOT = Path(__file__).resolve().parent.parent
VERSION = regression_shield.__version__

RELEASE_FILE = re.compile(r"releases/download/v([\w.]+)/regression_shield-([\w.]+?)(?:-py3-none-any\.whl|\.tar\.gz)")
GIT_TAG = re.compile(r"github\.com/SubodhSenpai/RegShield(?:\.git)?@v([\w.]+)")
# `pip install regression-shield` or `pip install "regression-shield[extra]"`, but not `... @ <url>`
PYPI_INSTALL = re.compile(r"pip install \"?regression-shield(?:\[[\w,]+\])?\"?(?!\s*@)(?=\s|$)")


def documents() -> list[tuple[str, str]]:
    paths = [ROOT / "README.md", *(ROOT / "docs").glob("*.md"), *(ROOT / "examples").glob("*"),
             *(ROOT / "website" / "app").rglob("*.js"), *(ROOT / "website" / "lib").glob("*.js")]
    return [(path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8"))
            for path in paths if path.is_file() and path.suffix in (".md", ".py", ".js")]


def test_install_links_name_this_version():
    links = [(name, set(match)) for name, text in documents()
             for match in [*RELEASE_FILE.findall(text), *((tag,) for tag in GIT_TAG.findall(text))]]
    if not links:
        pytest.skip("the docs aren't in this checkout (an sdist)")
    stale = [(name, versions) for name, versions in links if versions != {VERSION}]
    assert not stale, f"install links name another release than {VERSION}: {stale}"


def test_nothing_installs_from_pypi():
    found = [name for name, text in documents() if PYPI_INSTALL.search(text)]
    assert not found, f"RegShield isn't on PyPI yet, so these installs fail: {found}"


@pytest.mark.parametrize("command, from_pypi", [
    ("pip install regression-shield\n", True),
    ('pip install "regression-shield[langgraph]" langchain', True),
    ('pip install "regression-shield[langgraph] @ https://github.com/x.whl"', False),
    ("pip install https://github.com/SubodhSenpai/RegShield/releases/download/v1/regression_shield-1-py3-none-any.whl", False),
    ('pip install ".[all]"', False),
])
def test_the_pypi_pattern(command, from_pypi):
    assert bool(PYPI_INSTALL.search(command)) is from_pypi
