"""Runs the Markdown renderer's own tests (tests/js/markdown.test.js) under node.

Node is preinstalled on GitHub's runners, so CI always runs them (a missing node there is a failure).
On a machine without node they are skipped; run tests/js/run.html in a browser instead.
"""
import os
import shutil
import subprocess

import pytest

from app.config import ROOT


import pytest as _pytest


@_pytest.mark.parametrize("script,done", [("markdown.test.js", "markdown tests passed"), ("availability.test.js", "availability tests passed")])
def test_browser_side_logic_passes_its_node_tests(script, done):
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("node is required in CI to run the browser-side tests")
        pytest.skip("node is not installed; open tests/js/run.html in a browser to run them")
    result = subprocess.run([node, f"tests/js/{script}"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert done in result.stdout
