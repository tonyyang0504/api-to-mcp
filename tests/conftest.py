"""Shared fixtures: your own workspace (user mode) against a stand-in for platform-mcp-hub's catalog, and a
platform-mcp checkout built from the installed hub. PLATFORM_MCP_CHECKOUT=<a real checkout with runtime/typescript
built> adds the TypeScript halves and the end-to-end checkout test."""
import os
import shutil
from pathlib import Path

import pytest
from platform_mcp_hub import catalog as hub_catalog

from api_to_mcp import server as forge
from api_to_mcp import workspace

ROOT = Path(__file__).resolve().parents[1]
CHECKOUT = Path(os.environ["PLATFORM_MCP_CHECKOUT"]).resolve() if os.environ.get("PLATFORM_MCP_CHECKOUT") else None
TS_CLI = CHECKOUT / "runtime" / "typescript" / "dist" / "cli.js" if CHECKOUT else None
HAS_TS = bool(TS_CLI and TS_CLI.is_file() and shutil.which("node"))
HUB_PKG = Path(hub_catalog.__file__).resolve().parent  # the installed platform_mcp_hub package

VALID = {
    "label": "Probe Jobs", "lane": "api", "docs_url": "https://probe.example/docs", "url": "https://probe.example/", "verified_at": "2026-09-27", "version": "0.1.0",
    "adapter": {
        "base_url": "https://api.probe.example/v1", "auth": {"type": "none"}, "rate_per_second": 1,
        "tools": {
            "search": {"method": "GET", "path": "/jobs", "params": {"q": "query", "page": "page", "per_page": "limit"},
                       "result": {"items": "data", "key": "postings", "total": "meta.total", "fields": {"id": "id", "title": "title", "company": "company.name"}},
                       "docs": "https://probe.example/docs#jobs"},
            "get_posting": {"method": "GET", "path": "/jobs/{id}", "result": {"root": "data", "fields": {"id": "id", "title": "title"}}, "docs": "https://probe.example/docs#job"},
        },
        "not_offered": {"me": "no accounts", "apply": "apply on the site", "list_messages": "no messages"},
    },
}


def _mini_catalog(dest: Path) -> Path:
    """A stand-in for platform-mcp-hub's catalog: the real vocabulary and two real jobs entries."""
    src = hub_catalog.catalog_dir()
    (dest / "schema").mkdir(parents=True)
    (dest / "jobs").mkdir()
    shutil.copy(src / "schema" / "vocab.json", dest / "schema" / "vocab.json")
    shutil.copy(src / "schema" / "release.json", dest / "schema" / "release.json")
    for pid in ("reed", "remotive"):
        shutil.copy(src / "jobs" / f"{pid}.json", dest / "jobs" / f"{pid}.json")
    return dest


async def _public(host):  # the spec-URL guard resolves hosts (netguard): the *.example hosts here are public
    return ["93.184.215.14"]


@pytest.fixture
def hub(tmp_path, monkeypatch):
    cat = _mini_catalog(tmp_path / "hub_catalog")
    monkeypatch.setenv("PLATFORM_MCP_HUB_CATALOG", str(cat))
    if HAS_TS:
        monkeypatch.setenv("PLATFORM_MCP_HUB_TS_CLI", str(TS_CLI))
    else:
        monkeypatch.setenv("PLATFORM_MCP_HUB_TS_CLI", str(tmp_path / "no-typescript-runtime" / "cli.js"))
    return cat


@pytest.fixture
def ws(tmp_path, monkeypatch, hub):
    """Your own workspace (user mode), empty: entries come from the stand-in hub catalog until you save some."""
    home = tmp_path / "home"
    monkeypatch.setattr(forge, "WS", workspace.Workspace("user", home))
    monkeypatch.setattr(forge, "_resolve_host", _public)
    return home


def _synthetic_checkout(root: Path, hub: Path) -> Path:
    """Shaped like a platform-mcp checkout, built from the installed hub (no real checkout needed): catalog, runtime/python
    (a link to the installed package), a stub generator, the adapter contract, tests/."""
    shutil.copytree(hub, root / "catalog")
    (root / "runtime" / "python").mkdir(parents=True)
    (root / "runtime" / "python" / "platform_mcp_hub").symlink_to(HUB_PKG)
    (root / "generators" / "python").mkdir(parents=True)
    (root / "generators" / "python" / "gen.py").write_text("import sys\nprint('generated', sys.argv[1:])\n")
    (root / "docs").mkdir()
    (root / "docs" / "ADAPTER_CONTRACT.md").write_text("# Adapter contract\n")
    (root / "tests").mkdir()
    return root


@pytest.fixture
def checkout(tmp_path, monkeypatch, hub):
    root = _synthetic_checkout(tmp_path / "checkout", hub)
    monkeypatch.setattr(forge, "WS", workspace.Workspace("checkout", root))
    monkeypatch.setattr(forge, "_resolve_host", _public)
    return root


async def call(name: str, args: dict):
    res = await forge.server.call_tool(name, args)
    return res.is_error, res.structured_content


def _fake_runtime(root: Path, *, deps: bool = True, built: bool = False) -> Path:
    """A checkout-local runtime/typescript whose `tsc` is a stub that writes dist/cli.js (no network, no real build)."""
    rt = root / "runtime" / "typescript"
    (rt / "src").mkdir(parents=True)
    (rt / "src" / "index.ts").write_text("export {};\n")
    (rt / "package.json").write_text('{"name": "platform-mcp-hub"}')
    (rt / "package-lock.json").write_text("{}")
    if deps:
        (rt / "node_modules" / ".bin").mkdir(parents=True)
        tsc = rt / "node_modules" / ".bin" / "tsc"
        tsc.write_text("#!/bin/sh\nmkdir -p dist && echo 'export {};' > dist/cli.js\n")
        tsc.chmod(0o755)
    if built:
        (rt / "dist").mkdir()
        (rt / "dist" / "cli.js").write_text("export {};\n")
    return rt
