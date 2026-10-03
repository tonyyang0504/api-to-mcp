"""Where api-to-mcp reads and writes entries.

user mode (the default)
    A directory of your own: ``$API_TO_MCP_HOME``, else ``$XDG_DATA_HOME/api-to-mcp``, else
    ``~/.local/share/api-to-mcp``. Entries go to ``<home>/catalog/<category>/<id>.json``, run configs to
    ``<home>/servers/<category>/<id>/``, optional contract tests to ``<home>/tests/``. The vocabularies, the
    lint and the runtime come from the installed ``platform-mcp-hub`` package; entries run with
    ``platform-mcp-hub serve --entry <file>``. No checkout needed.

checkout mode (contributing upstream)
    ``$API_TO_MCP_CHECKOUT`` names a platform-mcp checkout. Entries go to its ``catalog/``, registry metadata
    is generated with its ``generators/``, its contract tests run with its runtime, and the TypeScript half is
    built from its ``runtime/typescript``. Open a pull request with the result.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

HOME_ENV = "API_TO_MCP_HOME"
CHECKOUT_ENV = "API_TO_MCP_CHECKOUT"


def is_checkout(p: Path) -> bool:
    """A platform-mcp checkout: the catalog, the hub's Python runtime and the registry-metadata generator."""
    return (p / "catalog" / "schema" / "vocab.json").is_file() and (p / "runtime" / "python" / "platform_mcp_hub").is_dir() \
        and (p / "generators" / "python" / "gen.py").is_file()


def default_home() -> Path:
    env = os.environ.get(HOME_ENV)
    if env:
        return Path(env).expanduser().resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return (base / "api-to-mcp").resolve()


@dataclass(frozen=True)
class Workspace:
    mode: str  # "user" | "checkout"
    root: Path

    @property
    def catalog(self) -> Path:
        return self.root / "catalog"

    @property
    def tests(self) -> Path:
        return self.root / "tests"

    @property
    def servers(self) -> Path:
        return self.root / "servers"

    @property
    def is_checkout(self) -> bool:
        return self.mode == "checkout"

    def valid(self) -> bool:
        return is_checkout(self.root) if self.is_checkout else True

    def hub_catalog(self) -> Path:
        """The catalog that supplies vocabularies and the existing entries: the checkout's, or the installed hub's."""
        if self.is_checkout:
            return self.catalog
        from platform_mcp_hub import catalog
        return catalog.catalog_dir()

    def vocab(self) -> dict:
        return json.loads((self.hub_catalog() / "schema" / "vocab.json").read_text(encoding="utf-8"))

    def contract_text(self) -> str:
        if self.is_checkout:
            p = self.root / "docs" / "ADAPTER_CONTRACT.md"
            return p.read_text(encoding="utf-8") if p.is_file() else ""
        from platform_mcp_hub import catalog
        return catalog.contract_text()

    def python(self) -> str:
        """The interpreter that runs the gates: a checkout's own .venv when it has one, else this one."""
        venv = self.root / ".venv" / "bin" / "python"
        return str(venv) if self.is_checkout and venv.exists() else sys.executable

    def gate_env(self, base: dict) -> dict:
        """Environment for `python -m platform_mcp_hub ...`: in checkout mode the checkout's runtime and catalog."""
        env = dict(base)
        if self.is_checkout:
            rt = str(self.root / "runtime" / "python")
            env["PYTHONPATH"] = os.pathsep.join([rt] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p and p != rt])
            env["PLATFORM_MCP_HUB_CATALOG"] = str(self.catalog)
        return env

    def ts_runtime_dir(self) -> Path | None:
        return self.root / "runtime" / "typescript" if self.is_checkout else None

    def describe(self) -> dict:
        return {"mode": self.mode, "path": str(self.root),
                "how": (f"a platform-mcp checkout ({CHECKOUT_ENV}); entries saved here can be contributed upstream" if self.is_checkout else
                        f"your own entries ({HOME_ENV} to move it; {CHECKOUT_ENV}=<platform-mcp checkout> to contribute upstream)")}


def resolve() -> Workspace:
    env = os.environ.get(CHECKOUT_ENV)
    if env:
        return Workspace("checkout", Path(env).expanduser().resolve())
    return Workspace("user", default_home())
