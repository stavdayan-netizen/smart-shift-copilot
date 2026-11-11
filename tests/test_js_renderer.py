"""Runs the Markdown renderer's own tests (tests/js/markdown.test.js) under node.

Node is preinstalled on GitHub's runners, so CI always runs them (a missing node there is a failure).
On a machine without node they are skipped; run tests/js/run.html in a browser instead.
"""
import os
import shutil
import subprocess

import pytest

from app.config import ROOT


def test_markdown_renderer_is_safe_and_correct():
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("node is required in CI to run the renderer tests")
        pytest.skip("node is not installed; open tests/js/run.html in a browser to run the renderer tests")
    result = subprocess.run([node, "tests/js/markdown.test.js"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "markdown tests passed" in result.stdout
