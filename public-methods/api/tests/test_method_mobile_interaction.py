"""Run the dependency-free JavaScript event contracts in the existing test job."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_atlas_mobile_event_contracts():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js 18+ is required for the atlas JavaScript event contracts")
    module = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, "--test", str(module / "web/tests/mobile-interaction.contract.cjs")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
