"""The example generic entries (examples/generic/): each passes the lint and starts over stdio with exactly its tools,
in Python and (with PLATFORM_MCP_CHECKOUT) TypeScript. No network."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import HAS_TS, TS_CLI

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "examples" / "generic").glob("*.json"))


def test_there_are_examples():
    assert len(EXAMPLES) >= 6


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_example_lints_and_smokes(path, monkeypatch):
    lint = subprocess.run([sys.executable, "-m", "platform_mcp_hub", "lint", "--json", str(path)], capture_output=True, text=True, timeout=120)
    assert lint.returncode == 0, lint.stdout + lint.stderr
    env = {"PATH": "/usr/bin:/bin:" + str(Path(sys.executable).parent)}
    import os
    env["PATH"] = os.environ.get("PATH", env["PATH"])
    if HAS_TS:
        env["PLATFORM_MCP_HUB_TS_CLI"] = str(TS_CLI)
    smoke = subprocess.run([sys.executable, "-m", "platform_mcp_hub", "smoke", "--json", *([] if HAS_TS else ["--lang", "py"]), str(path)],
                           capture_output=True, text=True, timeout=300, env=env)
    rep = json.loads(smoke.stdout)
    assert rep["ok"], rep
    tools = sorted(json.loads(path.read_text())["adapter"]["tools"])
    assert all(sorted(r["tools"]) == tools for r in rep["runs"])
