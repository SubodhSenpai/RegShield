"""Examples in the README and the cookbook print exactly the output shown under them.

A ```python block followed directly by a ```text block is run, and its output must
match. Other code blocks (shell commands, snippets that need an LLM) are not run.
"""

import contextlib
import io
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS = [ROOT / "README.md", ROOT / "docs" / "cookbook.md"]
BODY = r"((?:(?!```).)*)"  # a fenced block's body: anything up to the next fence
EXAMPLE = re.compile(r"```python\n" + BODY + r"```\n\n```text\n" + BODY + r"```", re.S)


def examples() -> list:
    params = []
    for document in DOCUMENTS:
        if not document.exists():  # e.g. tests run from an sdist, which has no docs/
            continue
        for section in re.split(r"\n#{2,3} ", document.read_text(encoding="utf-8")):
            title = section.split("\n", 1)[0].lstrip("# ")
            params += [pytest.param(code, output, id=f"{document.name}: {title}")
                       for code, output in EXAMPLE.findall(section)]
    return params


def test_the_cookbook_is_checked():
    if not DOCUMENTS[1].exists():
        pytest.skip("docs/cookbook.md is not available")
    assert sum("cookbook.md" in p.id for p in examples()) >= 10


@pytest.mark.parametrize("code, expected", examples())
def test_example_prints_the_documented_output(code, expected):
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        exec(compile(code, "<doc example>", "exec"), {"__name__": "doc_example"})
    assert printed.getvalue() == expected
