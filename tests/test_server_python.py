"""The api-to-mcp MCP server (src/api_to_mcp/server.py): every tool's success path and its error handling (bad input,
invalid entries, missing files, network failures), in your own workspace (the default) against a small stand-in for
the platform-mcp-hub catalog, and in a platform-mcp checkout (contributing upstream). One test drives the server over
stdio.

PLATFORM_MCP_CHECKOUT=<a platform-mcp checkout with runtime/typescript built> also runs the checkout-mode end-to-end
test and the TypeScript halves; without it those parts are skipped and say so."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import respx
from conftest import CHECKOUT, HAS_TS, ROOT, VALID, _fake_runtime, _public, call  # noqa: F401
from platform_mcp_hub import catalog as hub_catalog

from api_to_mcp import server as forge
from api_to_mcp import workspace

# ------------------------------------------------------------------ workspace resolution

def test_workspace_resolution_order(tmp_path, monkeypatch):
    for var in (workspace.HOME_ENV, workspace.CHECKOUT_ENV, "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert workspace.resolve() == workspace.Workspace("user", (tmp_path / ".local" / "share" / "api-to-mcp").resolve())  # the default: your own directory
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert workspace.resolve().root == (tmp_path / "xdg" / "api-to-mcp").resolve()
    monkeypatch.setenv(workspace.HOME_ENV, str(tmp_path / "mine"))
    assert workspace.resolve() == workspace.Workspace("user", (tmp_path / "mine").resolve())
    monkeypatch.setenv(workspace.CHECKOUT_ENV, str(tmp_path / "co"))
    ws_ = workspace.resolve()
    assert ws_.mode == "checkout" and ws_.root == (tmp_path / "co").resolve() and not ws_.valid()  # contributing upstream wins, and doctor says it is no checkout


def test_user_workspace_needs_no_checkout(ws):
    assert forge.WS.hub_catalog() == hub_catalog.catalog_dir() and "Adapter contract" in forge.WS.contract_text()
    assert forge.WS.python() == sys.executable and "PYTHONPATH" not in forge.WS.gate_env({})


def test_checkout_workspace_uses_the_checkout(checkout):
    env = forge.WS.gate_env({"PYTHONPATH": "/x"})
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(checkout / "runtime" / "python") and env["PLATFORM_MCP_HUB_CATALOG"] == str(checkout / "catalog")
    assert forge.WS.hub_catalog() == checkout / "catalog" and forge.WS.valid()


# ------------------------------------------------------------------ catalog_search / catalog_get

@pytest.mark.asyncio
async def test_catalog_search(ws):
    err, out = await call("catalog_search", {"query": "reed"})
    assert not err and [h["id"] for h in out["hits"]] == ["reed"] and out["hits"][0]["served"] is True and out["workspace"] == str(ws)
    assert out["hits"][0]["source"] == "platform-mcp-hub"
    err, out = await call("catalog_search", {"query": "remotive.com"})  # docs/base URL hosts are searchable
    assert not err and out["total"] == 1 and out["hits"][0]["id"] == "remotive"
    err, out = await call("catalog_search", {"query": "e", "limit": 1})
    assert not err and len(out["hits"]) == 1 and out["total"] == 2  # total counts every match, hits are capped
    err, out = await call("catalog_search", {"query": "reed", "category": "sales"})
    assert not err and out["total"] == 0
    err, out = await call("catalog_search", {"query": "  "})
    assert err and out["error"] == "invalid_input"
    await call("save_entry", {"category": "jobs", "id": "reed", "entry": {"label": "My Reed"}})
    err, out = await call("catalog_search", {"query": "reed"})
    assert out["total"] == 1 and out["hits"][0]["source"] == "workspace" and out["hits"][0]["label"] == "My Reed"  # your copy shadows the hub's


@pytest.mark.asyncio
async def test_catalog_search_survives_a_broken_entry(ws):
    (ws / "catalog" / "jobs").mkdir(parents=True)
    (ws / "catalog" / "jobs" / "broken.json").write_text("{not json")
    err, out = await call("catalog_search", {"query": "broken"})
    assert not err and out["hits"][0]["id"] == "broken"


@pytest.mark.asyncio
async def test_catalog_get(ws):
    err, out = await call("catalog_get", {"category": "jobs", "id": "reed"})
    assert not err and out["entry"]["id"] == "reed" and out["source"] == "platform-mcp-hub"
    err, out = await call("catalog_get", {"category": "sales", "id": "reed"})
    assert err and out["error"] == "not_found" and out["categories"] == ["jobs"]
    for bad in ({"category": "jobs", "id": "../x"}, {"category": "schema", "id": "vocab"}, {"category": "Jobs", "id": "reed"}):
        err, out = await call("catalog_get", bad)
        assert err and out["error"] == "invalid_input", bad
    (ws / "catalog" / "jobs").mkdir(parents=True)
    (ws / "catalog" / "jobs" / "broken.json").write_text("{not json")
    err, out = await call("catalog_get", {"category": "jobs", "id": "broken"})
    assert err and out["error"] == "invalid_entry"


@pytest.mark.asyncio
async def test_workspace_tool(ws):
    await call("save_entry", {"category": "jobs", "id": "probe", "entry": VALID})
    err, out = await call("workspace", {})
    assert not err and out["mode"] == "user" and out["path"] == str(ws) and out["entries"] == ["catalog/jobs/probe.json"]


# ------------------------------------------------------------------ template_entry

@pytest.mark.asyncio
async def test_template_entry(ws):
    err, out = await call("template_entry", {"category": "jobs"})
    assert not err
    assert set(out["verbs"]) == {"me", "search", "get_posting", "apply", "list_messages"}
    assert set(out["skeleton"]["adapter"]["not_offered"]) == set(out["verbs"]) and out["skeleton"]["category"] == "jobs"
    assert out["adapter_example"]["from"].startswith("jobs/")
    assert "oauth2_refresh_token" in out["adapter_reference"]["auth.types"]  # derived from the lint, never stale
    assert "Adapter contract" in out["rules"]
    err, out = await call("template_entry", {"category": "nope"})
    assert err and out["error"] == "invalid_input" and "jobs" in out["message"]


# ------------------------------------------------------------------ ingest_openapi

OPENAPI3 = {
    "openapi": "3.0.3", "info": {"title": "Probe", "version": "1", "description": "Rate limit: 10 requests per minute."},
    "servers": [{"url": "https://api.probe.example/{ver}", "variables": {"ver": {"default": "v2"}}}, {"url": "/relative"}],
    "components": {
        "parameters": {"q": {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}},
                       "size": {"name": "size", "in": "query", "schema": {"type": "integer", "default": 20, "enum": [10, 20, 50]}}},
        "schemas": {
            "Job": {"type": "object", "properties": {"id": {"type": "string"}, "title": {"type": "string"}, "parent": {"$ref": "#/components/schemas/Job"}}},
            "Page": {"type": "object", "properties": {"data": {"type": "array", "items": {"$ref": "#/components/schemas/Job"}}, "next": {"type": "string"}}},
            "Base": {"type": "object", "properties": {"start": {"type": "string"}}},
            "Search": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "allOf": [{"$ref": "#/components/schemas/Base"}]},
            "Bars": {"type": "object", "properties": {"t": {"type": "array", "items": {"type": "integer"}}, "c": {"type": "array", "items": {"type": "string"}}}},
        },
        "securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Key"}},
    },
    "security": [{}, {"key": []}],
    "paths": {
        "/jobs": {"parameters": [{"$ref": "#/components/parameters/q"}],
                  "get": {"operationId": "listJobs", "summary": "List jobs", "description": "Rate limit: 2 requests/sec", "parameters": [{"$ref": "#/components/parameters/size"}, {"$ref": "#/components/parameters/missing"}],
                          "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Page"}, "example": {"data": [{"id": "1", "title": "Dev"}]}}}}}}},
        "/search": {"post": {"summary": "Search", "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Search"}}}},
                             "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/Job"}}}}}}}},
        "/bars": {"get": {"summary": "Bars", "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Bars"}}}}}}},
    },
}

SWAGGER2_YAML = """
swagger: "2.0"
info: {title: Probe2, version: "2"}
host: api.probe2.example
basePath: /api/v4
schemes: [https]
securityDefinitions:
  Bearer: {type: apiKey, name: Authorization, in: header}
definitions:
  Order:
    type: object
    required: [symbol]
    properties: {symbol: {type: string}, qty: {type: number}}
paths:
  /tickers:
    get:
      summary: Tickers
      parameters:
        - {name: symbols, in: query, type: string, required: true}
      responses:
        "200":
          description: ok
          schema: {type: array, items: {type: object, properties: {pair: {type: string}, last: {type: string}}}}
  /orders:
    post:
      summary: Place order
      parameters:
        - {name: body, in: body, schema: {$ref: "#/definitions/Order"}}
      responses: {"200": {description: ok}}
  /upload:
    post:
      summary: Upload
      consumes: [multipart/form-data]
      parameters:
        - {name: file, in: formData, type: file, required: true}
      responses: {"200": {description: ok}}
"""


@pytest.mark.asyncio
async def test_ingest_openapi3_resolves_refs_servers_bodies_and_responses(ws):
    err, out = await call("ingest_openapi", {"source": json.dumps(OPENAPI3)})
    assert not err, out
    assert out["servers"][0] == "https://api.probe.example/v2"  # server variable default substituted
    assert out["description"].startswith("Rate limit") and out["security_schemes"]["key"]["name"] == "X-Key"
    ops = {o["path"]: o for o in out["operations"]}
    jobs = ops["/jobs"]
    assert "q(query, required, string)" in jobs["params"]  # path-level $ref parameter resolved
    assert "size(query, integer, enum=10|20|50, default=20)" in jobs["params"]
    assert jobs["unresolved_refs"] == ["#/components/parameters/missing"]
    assert jobs["response"]["shape"]["lists"] == {"data": ["id", "parent", "title"]} and '"Dev"' in jobs["response"]["example"]
    assert jobs["rate_limit"] == "2 requests/sec" and jobs["paging_params"] == ["size"]
    search = ops["/search"]
    assert search["body"] == ["query", "start"] and search["body_required"] == ["query"]  # own properties + allOf merged
    assert search["response"]["shape"] == {"type": "array", "item_keys": ["id", "parent", "title"]}
    assert ops["/bars"]["response"]["shape"]["columnar"] is True
    err, out = await call("ingest_openapi", {"source": json.dumps(OPENAPI3), "filter": "search", "limit": 5})
    assert not err and [o["path"] for o in out["operations"]] == ["/search"]
    err, out = await call("ingest_openapi", {"source": json.dumps(OPENAPI3), "limit": 1})
    assert not err and out["operations_total"] == 3 and len(out["operations"]) == 1 and out["truncated"] is True


@pytest.mark.asyncio
async def test_ingest_swagger2_yaml_from_a_local_file(ws, tmp_path):
    f = tmp_path / "spec.yaml"
    f.write_text(SWAGGER2_YAML)
    err, out = await call("ingest_openapi", {"source": str(f)})
    assert not err, out
    assert out["source"] == "file" and out["spec_version"] == "2.0" and out["servers"] == ["https://api.probe2.example/api/v4"]
    ops = {o["path"]: o for o in out["operations"]}
    assert ops["/tickers"]["params"] == ["symbols(query, required, string)"]
    assert ops["/tickers"]["response"]["shape"] == {"type": "array", "item_keys": ["last", "pair"]}
    assert ops["/orders"]["body"] == ["qty", "symbol"] and ops["/orders"]["body_required"] == ["symbol"]  # Swagger 2 `in: body`
    assert ops["/upload"]["body"] == ["file"] and ops["/upload"]["body_type"] == "form"


@pytest.mark.asyncio
@respx.mock
async def test_ingest_from_a_url_resolves_relative_servers(ws):
    spec = {**OPENAPI3, "servers": [{"url": "/api/v3"}]}
    respx.get("https://93.184.215.14/spec/openapi.json", headers={"host": "docs.probe.example"}).mock(return_value=httpx.Response(200, json=spec))
    err, out = await call("ingest_openapi", {"source": "https://docs.probe.example/spec/openapi.json"})
    assert not err and out["servers"] == ["https://docs.probe.example/api/v3"] and out["source"] == "https://docs.probe.example/spec/openapi.json"


@pytest.mark.asyncio
@respx.mock
async def test_ingest_html_page_is_not_openapi_and_lists_spec_links(ws):
    html = '<!DOCTYPE html><html><head><title>API</title></head><body><a href="/files/openapi.yaml">spec</a> <script src="app.js"></script></body></html>'
    respx.get("https://93.184.215.14/api/", headers={"host": "docs.probe.example"}).mock(return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"}))
    err, out = await call("ingest_openapi", {"source": "https://docs.probe.example/api/"})
    assert err and out["error"] == "not_openapi" and out["spec_links"] == ["https://docs.probe.example/files/openapi.yaml"]


@pytest.mark.asyncio
@respx.mock
async def test_ingest_reads_the_spec_a_redoc_page_embeds(ws):
    # Bitstamp's https://www.bitstamp.net/api/ is a Redoc page with the whole spec in __redoc_state
    state = {"menu": {"activeItemIdx": -1}, "spec": {"data": {**OPENAPI3, "servers": [{"url": "https://api.probe.example"}]}}, "searchIndex": {}}
    html = f'<!DOCTYPE html><html><head></head><body><div id="redoc"></div><script>const __redoc_state = {json.dumps(state)};\nvar c = 1;</script></body></html>'
    respx.get("https://93.184.215.14/redoc/", headers={"host": "docs.probe.example"}).mock(return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"}))
    err, out = await call("ingest_openapi", {"source": "https://docs.probe.example/redoc/", "filter": "/jobs"})
    assert not err and out["embedded_in"] == "html (__redoc_state)" and out["servers"] == ["https://api.probe.example"]
    assert [o["path"] for o in out["operations"]] == ["/jobs"]
    broken = '<!DOCTYPE html><html><head></head><body><script>const __redoc_state = {"spec": {"data": ;</script></body></html>'
    respx.get("https://93.184.215.14/broken/", headers={"host": "docs.probe.example"}).mock(return_value=httpx.Response(200, text=broken, headers={"content-type": "text/html"}))
    err, out = await call("ingest_openapi", {"source": "https://docs.probe.example/broken/"})
    assert err and out["error"] == "not_openapi"


@pytest.mark.asyncio
@respx.mock
async def test_ingest_network_and_http_failures_are_upstream_errors(ws):
    respx.get("https://93.184.215.14/openapi.json", headers={"host": "down.probe.example"}).mock(side_effect=httpx.ConnectError("connection refused"))
    err, out = await call("ingest_openapi", {"source": "https://down.probe.example/openapi.json"})
    assert err and out["error"] == "upstream_error" and "connection refused" in out["message"]
    respx.get("https://93.184.215.14/openapi.json", headers={"host": "gone.probe.example"}).mock(return_value=httpx.Response(404, text="nope"))
    err, out = await call("ingest_openapi", {"source": "https://gone.probe.example/openapi.json"})
    assert err and out["error"] == "upstream_error" and out["http_status"] == 404


@pytest.mark.asyncio
async def test_ingest_bad_inputs(ws, tmp_path):
    err, out = await call("ingest_openapi", {"source": "/no/such/spec.yaml"})
    assert err and out["error"] == "not_found"
    err, out = await call("ingest_openapi", {"source": ""})
    assert err and out["error"] == "invalid_input"
    err, out = await call("ingest_openapi", {"source": '{"info": {"title": "x"}}'})
    assert err and out["error"] == "not_openapi"
    err, out = await call("ingest_openapi", {"source": "openapi: [unclosed"})
    assert err and out["error"] == "invalid_input" and "YAML" in out["message"]
    err, out = await call("ingest_openapi", {"source": "just some prose about an API"})
    assert err and out["error"] == "not_openapi"


# ------------------------------------------------------------------ save_entry

@pytest.mark.asyncio
async def test_save_entry_creates_and_merges(ws):
    err, out = await call("save_entry", {"category": "jobs", "id": "probe", "entry": VALID})
    assert not err and out == {"saved": "catalog/jobs/probe.json", "workspace": str(ws), "created": True, "served": True, "next": "lint_entry"}
    p = ws / "catalog" / "jobs" / "probe.json"
    saved = json.loads(p.read_text())
    assert saved["id"] == "probe" and saved["category"] == "jobs" and saved["adapter"]["base_url"].endswith("/v1")
    err, out = await call("save_entry", {"category": "jobs", "id": "probe", "entry": {"label": "Probe Jobs 2"}})
    saved = json.loads(p.read_text())
    assert not err and out["created"] is False and saved["label"] == "Probe Jobs 2" and "adapter" in saved  # existing fields kept
    err, out = await call("save_entry", {"category": "jobs", "id": "probe", "entry": {"adapter_status": "blocked", "reason": "docs 403"}})
    saved = json.loads(p.read_text())
    assert not err and "adapter" not in saved and saved["adapter_status"] == "blocked" and out["served"] is False
    err, out = await call("save_entry", {"category": "jobs", "id": "probe", "entry": {"adapter": VALID["adapter"]}})
    saved = json.loads(p.read_text())
    assert not err and "adapter_status" not in saved and "reason" not in saved


@pytest.mark.asyncio
async def test_save_entry_refusals(ws):
    vocab = (forge.WS.hub_catalog() / "schema" / "vocab.json").read_text()
    cases = [
        ({"category": "schema", "id": "vocab", "entry": {"x": 1}}, "invalid_input"),  # would overwrite the vocabulary
        ({"category": "sources", "id": "x1", "entry": {"x": 1}}, "invalid_input"),
        ({"category": "nope", "id": "x1", "entry": {"x": 1}}, "invalid_input"),
        ({"category": "jobs", "id": "Bad-Id", "entry": {"x": 1}}, "invalid_input"),
        ({"category": "jobs", "id": "x1", "entry": {}}, "invalid_input"),
        ({"category": "jobs", "id": "x1", "entry": {"adapter": None}}, "invalid_input"),
        ({"category": "jobs", "id": "x1", "entry": {"id": "other"}}, "invalid_input"),
        ({"category": "jobs", "id": "x1", "entry": {"category": "sales"}}, "invalid_input"),
        ({"category": "jobs", "id": "x1", "entry": {"adapter": {}, "adapter_status": "blocked"}}, "invalid_input"),
    ]
    for args, code in cases:
        err, out = await call("save_entry", args)
        assert err and out["error"] == code, args
    assert (forge.WS.hub_catalog() / "schema" / "vocab.json").read_text() == vocab and not (ws / "catalog" / "schema").exists()
    assert not (ws / "catalog" / "jobs" / "x1.json").exists()


# ------------------------------------------------------------------ lint_entry

@pytest.mark.asyncio
async def test_lint_entry(ws):
    await call("save_entry", {"category": "jobs", "id": "probe", "entry": VALID})
    err, out = await call("lint_entry", {"category": "jobs", "id": "probe"})
    assert not err and out["ok"] is True and out["errors"] == []
    bad = json.loads(json.dumps(VALID))
    bad["adapter"]["tools"]["search"]["params"]["q"] = "qeury"
    bad["adapter"]["tools"]["search"]["params"]["x"] = "@nokey"
    bad["adapter"]["tools"]["get_posting"]["path"] = "/jobs/{job}"
    bad["adapter"]["tools"]["search"]["result"]["key"] = "jobs"
    bad["adapter"]["tools"]["get_posting"]["result"]["fields"]["title"] = "arg:posting"
    bad["adapter"]["tools"]["frobnicate"] = {"path": "/x"}
    bad["verified_at"] = "27.09.2026"
    await call("save_entry", {"category": "jobs", "id": "probe", "entry": bad})
    err, out = await call("lint_entry", {"category": "jobs", "id": "probe"})
    text = " | ".join(out["errors"])
    assert err and out["ok"] is False
    for needle in ("reads argument 'qeury'", "@nokey", "{job}", "result.key must be 'postings'", "'frobnicate' is not in the jobs vocabulary", "verified_at must be YYYY-MM-DD", "echoes argument 'posting'"):
        assert needle in text, needle
    err, out = await call("lint_entry", {"category": "jobs", "id": "absent"})
    assert err and out["error"] == "not_found"
    (ws / "catalog" / "jobs" / "broken.json").write_text("{not json")
    err, out = await call("lint_entry", {"category": "jobs", "id": "broken"})
    assert err and "not valid JSON" in out["errors"][0]


# ------------------------------------------------------------------ generate_server / test_server

@pytest.mark.asyncio
async def test_generate_and_test_server_in_your_own_workspace(ws):
    err, out = await call("generate_server", {"category": "jobs", "id": "probe"})
    assert err and out["error"] == "not_found"
    await call("save_entry", {"category": "jobs", "id": "probe", "entry": VALID})
    err, out = await call("test_server", {"category": "jobs", "id": "probe"})
    assert err and out["error"] == "not_generated"
    err, out = await call("generate_server", {"category": "jobs", "id": "probe"})
    assert not err and out["ok"] is True and out["mode"] == "user", out
    assert out["files"] == ["servers/jobs/probe/README.md", "servers/jobs/probe/mcp.json"]
    cfg = json.loads((ws / "servers" / "jobs" / "probe" / "mcp.json").read_text())["mcpServers"]["probe"]
    assert cfg["command"] == sys.executable and cfg["args"] == ["-m", "platform_mcp_hub", "serve", "--entry", str(ws / "catalog" / "jobs" / "probe.json")]
    assert "platform-mcp-hub serve --entry" in out["run"]["any_machine"] and "API_TO_MCP_CHECKOUT" in out["run"]["contribute"]
    template = out["contract_test_template"]
    assert template["path"] == "tests/test_probe_python.py" and out["contract_test"]["created"] is True
    assert (ws / "tests" / "test_probe_python.py").read_text() == template["text"]
    (ws / "tests" / "test_probe_python.py").unlink()
    # no contract test: the smoke passes, the gate does not
    err, out = await call("test_server", {"category": "jobs", "id": "probe"})
    assert err and out["ok"] is False and out["missing"] == ["python contract test"]
    runs = {r["lang"]: r for r in out["smoke"]["runs"]}
    assert runs["py"]["ok"] is True and runs["py"]["tools"] == ["search", "get_posting"]
    if HAS_TS:
        assert runs["ts"]["ok"] is True and runs["ts"]["tools"] == ["search", "get_posting"]
    else:  # no TypeScript runtime: Python only, and every result says so
        assert list(runs) == ["py"] and out["mode"] == "python_only" and out["warnings"]
    # the template generate_server writes is a working test (and an existing test is never overwritten)
    (ws / template["path"]).write_text(template["text"])
    err, again = await call("generate_server", {"category": "jobs", "id": "probe"})
    assert again["contract_test"]["created"] is False
    err, out = await call("test_server", {"category": "jobs", "id": "probe"})
    assert not err and out["ok"] is True and out["python_tests"]["ok"] is True and out["missing"] == [], out
    assert out["typescript_tests"] == "not used in a user workspace"


@pytest.mark.asyncio
async def test_generate_refuses_status_only_and_lint_errors(ws):
    await call("save_entry", {"category": "jobs", "id": "blocked1", "entry": {"adapter_status": "blocked", "reason": "docs 403"}})
    err, out = await call("generate_server", {"category": "jobs", "id": "blocked1"})
    assert err and out["error"] == "invalid_input" and "no adapter" in out["message"]
    bad = json.loads(json.dumps(VALID))
    bad["adapter"]["tools"]["search"]["params"]["q"] = "qeury"
    await call("save_entry", {"category": "jobs", "id": "probe", "entry": bad})
    err, out = await call("generate_server", {"category": "jobs", "id": "probe"})
    assert err and out["error"] == "lint_failed" and not (ws / "servers" / "jobs" / "probe").exists()


@pytest.mark.asyncio
async def test_a_hub_entry_is_changed_through_a_workspace_copy(ws):
    err, out = await call("lint_entry", {"category": "jobs", "id": "reed"})
    assert err and out["error"] == "not_found" and "save_entry a copy" in out["message"]


def test_run_reports_a_missing_executable_and_timeouts(ws):
    out = forge._run(["definitely-not-a-binary-xyz", "--version"])
    assert out["ok"] is False and "cannot run" in out["stderr"]
    out = forge._run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
    assert out["ok"] is False and "timed out" in out["stderr"]


# ------------------------------------------------------------------ prerequisites: doctor, auto-build, Python-only without TypeScript

def _no_node(monkeypatch):
    real = forge._which
    monkeypatch.setattr(forge, "_which", lambda name: None if name in ("node", "npm") else real(name))


NAMES = ["workspace", "workspace writable", "python + gate dependencies", "uv", "node", "npm", "typescript runtime"]


@pytest.mark.asyncio
async def test_doctor_in_your_own_workspace(ws, monkeypatch):
    err, out = await call("doctor", {})
    assert [c["name"] for c in out["checks"]] == NAMES and out["workspace"]["mode"] == "user" and out["workspace"]["path"] == str(ws)
    ts = out["checks"][-1]
    if HAS_TS:
        assert ts["ok"] and out["mode"] == "full" and not err
    else:
        assert not ts["ok"] and "PLATFORM_MCP_HUB_TS_CLI" in ts["fix"] and out["mode"] == "python_only" and not err
    _no_node(monkeypatch)
    err, out = await call("doctor", {})
    node = next(c for c in out["checks"] if c["name"] == "node")
    assert node["ok"] is False and ("nodesource" in node["fix"] or "brew install node" in node["fix"])
    assert out["mode"] == "python_only" and not err and "Python only" in out["summary"]


@pytest.mark.asyncio
async def test_doctor_in_a_checkout(checkout, monkeypatch):
    _fake_runtime(checkout, built=True)
    err, out = await call("doctor", {})
    assert [c["name"] for c in out["checks"]] == NAMES and out["workspace"]["mode"] == "checkout"
    assert all(c["ok"] for c in out["checks"] if c["name"] != "uv") and out["mode"] == "full" and not err, out
    monkeypatch.setattr(forge, "WS", workspace.Workspace("checkout", checkout / "catalog"))  # not a checkout
    err, out = await call("doctor", {})
    assert err and out["mode"] == "blocked" and "API_TO_MCP_CHECKOUT" in out["checks"][0]["fix"]


@pytest.mark.asyncio
async def test_doctor_fix_and_test_server_build_a_missing_or_stale_runtime(checkout, monkeypatch):
    rt = _fake_runtime(checkout)
    assert forge._ts_runtime_state()["state"] == "missing"
    err, out = await call("doctor", {})
    ts = out["checks"][-1]
    assert ts["ok"] is False and ts["required"] is False and "automatically" in ts["detail"] and out["mode"] == "full"
    err, out = await call("doctor", {"fix": True})
    assert out["checks"][-1]["ok"] is True and "built now" in out["checks"][-1]["detail"] and (rt / "dist" / "cli.js").exists()
    import time
    time.sleep(0.02)
    (rt / "src" / "index.ts").write_text("export const x = 1;\n")  # newer than dist: stale
    assert forge._ts_runtime_state()["state"] == "stale"
    res = forge._ensure_ts_runtime()
    assert res["ok"] and res["built"] and forge._ts_runtime_state()["state"] == "ok"
    monkeypatch.setenv("API_TO_MCP_AUTOBUILD", "0")
    (rt / "dist" / "cli.js").unlink()
    res = forge._ensure_ts_runtime()
    assert res["ok"] is False and "disabled" in res["reason"] and "npm ci" in res["fix"]
    monkeypatch.delenv("API_TO_MCP_AUTOBUILD")
    (rt / "package-lock.json").unlink()
    res = forge._ensure_ts_runtime()
    assert res["ok"] is False and "package-lock.json" in res["reason"]  # never an unlocked install


@pytest.mark.asyncio
async def test_without_node_tests_and_live_checks_run_python_only(ws, monkeypatch):
    _no_node(monkeypatch)
    await call("save_entry", {"category": "jobs", "id": "probe", "entry": VALID})
    err, out = await call("generate_server", {"category": "jobs", "id": "probe"})
    assert not err and out["ok"] is True and (ws / "tests" / "test_probe_python.py").exists()
    err, out = await call("test_server", {"category": "jobs", "id": "probe"})
    assert not err and out["ok"] is True and out["mode"] == "python_only" and "node is not on PATH" in out["warnings"][0], out
    assert [r["lang"] for r in out["smoke"]["runs"]] == ["py"]
    err, out = await call("live_verify", {"category": "jobs", "id": "probe", "lang": "ts"})
    assert err and out["error"] == "prerequisite_missing" and "node" in out["message"]
    seen = {}

    def fake_run(argv, cwd=None, timeout=900, env=None, max_stdout=6000):
        seen["argv"] = argv
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps({"servers": [{"status": "working", "run": {"lang": "py", "calls": []}}]}))
        return {"ok": True, "stdout": "", "stderr": "", "returncode": 0}
    monkeypatch.setattr(forge, "_run", fake_run)
    err, out = await call("live_verify", {"category": "jobs", "id": "probe"})
    assert seen["argv"][seen["argv"].index("--lang") + 1] == "py" and out["mode"] == "python_only" and out["statuses"] == {"py": "working"}


# ------------------------------------------------------------------ try_tool / live_verify

@pytest.mark.asyncio
async def test_try_tool_refuses_writes_and_unmapped_verbs(ws):
    await call("save_entry", {"category": "jobs", "id": "probe", "entry": VALID})
    err, out = await call("try_tool", {"category": "jobs", "id": "probe", "verb": "apply", "arguments": {}})
    assert err and out["error"] == "invalid_input" and "does not map apply" in out["message"]
    w = json.loads(json.dumps(VALID))
    w["adapter"]["tools"]["apply"] = {"method": "POST", "path": "/jobs/{posting_id}/apply", "docs": "https://probe.example/docs#apply"}
    del w["adapter"]["not_offered"]["apply"]
    await call("save_entry", {"category": "jobs", "id": "probe", "entry": w})
    err, out = await call("try_tool", {"category": "jobs", "id": "probe", "verb": "apply", "arguments": {}})
    assert err and "write tool" in out["message"]
    err, out = await call("try_tool", {"category": "jobs", "id": "nope", "verb": "search"})
    assert err and out["error"] == "not_found"


@pytest.mark.asyncio
@respx.mock
async def test_try_tool_shows_request_raw_and_result(ws, monkeypatch):
    from platform_mcp_hub import trytool as tt
    route = respx.get("https://api.probe.example/v1/jobs").mock(return_value=httpx.Response(200, json={"items": [{"id": 1, "title": "Dev"}]}))
    monkeypatch.setattr(tt.egress_guard, "RESOLVER", _public)  # try_tool checks the entry's hosts first (platform_mcp_hub/egress.py)
    entry = {"id": "probe", "category": "jobs", **VALID}
    out = await tt.run(entry, "search", {"query": "dev"}, 4000)
    assert route.called and out["ok"] is True
    assert out["result"]["postings"] == []  # result.items says `data`, the platform answered `items`: the raw shows why
    assert out["raw_structure"] == {"items": ["list(1)", {"id": "int", "title": "str"}]}
    assert out["request"]["url"] == "https://api.probe.example/v1/jobs" and out["request"]["params"]["q"] == "dev"
    respx.get("https://api.probe.example/v1/jobs").mock(side_effect=httpx.ConnectError("boom"))
    out = await tt.run(entry, "search", {"query": "dev"}, 4000)
    assert out["ok"] is False and out["error"] == "upstream_error"


@pytest.mark.asyncio
async def test_live_verify_tool_summarises_the_report(ws, monkeypatch):
    await call("save_entry", {"category": "jobs", "id": "probe", "entry": VALID})
    seen = {}

    def fake_run(argv, cwd=None, timeout=900, env=None, max_stdout=6000):
        seen["argv"] = argv
        report = {"servers": [{"server": "jobs/probe", "status": "working", "notes": "all read tools answered",
                               "run": {"lang": "py", "tools": ["search"], "calls": [{"tool": "search", "args": {"query": "x"}, "is_error": False, "count": 3, "result": {"big": 1}}]},
                               "ts_status": "degraded", "ts_notes": "search page 2 repeats page 1",
                               "ts_run": {"lang": "ts", "tools": ["search"], "calls": []}, "parity": {"equal": True, "diffs": []}}]}
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps(report))
        return {"ok": True, "stdout": "", "stderr": "", "returncode": 0}

    monkeypatch.setattr(forge, "_ts_or_warning", lambda: (True, [], None))
    monkeypatch.setattr(forge, "_run", fake_run)
    err, out = await call("live_verify", {"category": "jobs", "id": "probe", "plan": {"args": {"search": {"query": "x"}}}})
    assert err and out["ok"] is False and out["statuses"] == {"py": "working", "ts": "degraded"}
    assert out["runs"][0]["calls"][0] == {"tool": "search", "args": {"query": "x"}, "is_error": False, "count": 3}
    argv = seen["argv"]
    assert argv[1:4] == ["-m", "platform_mcp_hub", "verify"] and argv[argv.index("--entry") + 1] == str(ws / "catalog" / "jobs" / "probe.json")
    assert argv[argv.index("--auth") + 1] == "any" and json.loads(argv[argv.index("--plan") + 1]) == {"args": {"search": {"query": "x"}}}

    def no_report(argv, cwd=None, timeout=900, env=None, max_stdout=6000):
        return {"ok": False, "stdout": "", "stderr": "SystemExit: --plan must be a JSON object", "returncode": 1}

    monkeypatch.setattr(forge, "_run", no_report)
    err, out = await call("live_verify", {"category": "jobs", "id": "probe"})
    assert err and out["error"] == "live_verify_failed" and "--plan" in out["message"]
    err, out = await call("live_verify", {"category": "jobs", "id": "probe", "lang": "go"})
    assert err and out["error"] == "invalid_input"


def test_live_verify_cli_rejects_a_bad_plan(ws):
    p_entry = ws / "catalog" / "jobs" / "probe.json"
    p_entry.parent.mkdir(parents=True)
    p_entry.write_text(json.dumps({"id": "probe", "category": "jobs", **VALID}))
    for plan, needle in (('{"argz": {}}', "keys among"), ('[1]', "keys among")):
        p = subprocess.run([sys.executable, "-m", "platform_mcp_hub", "verify", "--entry", str(p_entry), "--plan", plan, "--json", str(ws / "r.json")],
                           capture_output=True, text=True, timeout=60)
        assert p.returncode != 0 and needle in p.stderr + p.stdout
    p = subprocess.run([sys.executable, "-m", "platform_mcp_hub", "verify", "--only", "jobs/nothing", "--plan", "{}"], capture_output=True, text=True, timeout=60)
    assert p.returncode != 0 and "exactly one served entry" in p.stderr + p.stdout


# ------------------------------------------------------------------ contributing upstream: a platform-mcp checkout

@pytest.mark.asyncio
async def test_checkout_mode_saves_into_the_checkout_and_runs_its_generator(checkout):
    err, out = await call("save_entry", {"category": "jobs", "id": "probe", "entry": VALID})
    assert not err and out["saved"] == "catalog/jobs/probe.json" and (checkout / "catalog" / "jobs" / "probe.json").exists()
    err, out = await call("catalog_get", {"category": "jobs", "id": "reed"})
    assert not err and out["source"] == "workspace"  # the checkout's own catalog
    err, out = await call("generate_server", {"category": "jobs", "id": "probe"})
    assert not err and out["mode"] == "checkout" and "generated" in out["generator"]["stdout"] and "probe.json" in out["generator"]["stdout"]
    assert "ROOT / \"runtime\" / \"python\"" in out["contract_test_template"]["text"]


@pytest.mark.skipif(CHECKOUT is None, reason="PLATFORM_MCP_CHECKOUT is not set")
@pytest.mark.asyncio
async def test_checkout_mode_end_to_end_against_a_real_checkout(tmp_path, monkeypatch):
    """A copy of a real platform-mcp checkout: its generator writes the registry metadata, its runtime runs the contract
    test and both runtimes' smoke."""
    root = tmp_path / "co"
    (root / "catalog").mkdir(parents=True)
    shutil.copytree(CHECKOUT / "catalog" / "schema", root / "catalog" / "schema")
    shutil.copytree(CHECKOUT / "catalog" / "jobs", root / "catalog" / "jobs")
    shutil.copytree(CHECKOUT / "generators", root / "generators", ignore=shutil.ignore_patterns("__pycache__"))
    (root / "runtime").symlink_to(CHECKOUT / "runtime")
    (root / "docs").mkdir()
    shutil.copy(CHECKOUT / "docs" / "ADAPTER_CONTRACT.md", root / "docs" / "ADAPTER_CONTRACT.md")
    (root / "tests").mkdir()
    monkeypatch.delenv("PLATFORM_MCP_HUB_CATALOG", raising=False)
    monkeypatch.delenv("PLATFORM_MCP_HUB_TS_CLI", raising=False)
    monkeypatch.setattr(forge, "WS", workspace.Workspace("checkout", root))
    monkeypatch.setattr(forge, "_resolve_host", _public)
    err, out = await call("save_entry", {"category": "jobs", "id": "probe", "entry": VALID})
    assert not err
    err, out = await call("generate_server", {"category": "jobs", "id": "probe"})
    assert not err and out["ok"], out
    sj = json.loads((root / "servers" / "jobs" / "probe" / "server.json").read_text())
    assert sj["name"] == "io.github.tonyyang0504/probe-mcp" and [a["value"] for a in sj["packages"][0]["packageArguments"]] == ["serve", "probe"]
    (root / "tests" / "test_probe_python.py").write_text(out["contract_test_template"]["text"])
    err, out = await call("test_server", {"category": "jobs", "id": "probe"})
    assert out["python_tests"]["ok"] is True and out["missing"] == ["typescript contract test"], out
    runs = {r["lang"]: r for r in out["smoke"]["runs"]}
    assert runs["py"]["ok"] is True
    if HAS_TS:
        assert runs["ts"]["ok"] is True and runs["ts"]["tools"] == ["search", "get_posting"]


# ------------------------------------------------------------------ the CLI and stdio, as a client calls it

def test_cli_prints_tool_results_and_exit_codes(ws, tmp_path):
    env = {**os.environ, "API_TO_MCP_HOME": str(ws)}
    entry = tmp_path / "probe.json"
    entry.write_text(json.dumps(VALID))
    run = lambda *a: subprocess.run([sys.executable, "-m", "api_to_mcp", *a], capture_output=True, text=True, timeout=120, env=env)  # noqa: E731
    out = run("save", "jobs", "probe", str(entry))
    assert out.returncode == 0 and json.loads(out.stdout)["saved"] == "catalog/jobs/probe.json"
    out = run("lint", "jobs", "probe")
    assert out.returncode == 0 and json.loads(out.stdout)["ok"] is True
    out = run("search", "probe")
    assert json.loads(out.stdout)["hits"][0]["source"] == "workspace"
    out = run("get", "jobs", "nope")
    assert out.returncode == 1 and json.loads(out.stdout)["error"] == "not_found"
    out = run("--checkout", str(tmp_path / "not-a-checkout"), "workspace")
    assert json.loads(out.stdout)["mode"] == "checkout"
    assert run("--version").stdout.strip().startswith("api-to-mcp ") and run("frobnicate").returncode == 2


@pytest.mark.asyncio
async def test_server_over_stdio(ws):
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "/tmp"), "API_TO_MCP_HOME": str(ws),
           "PLATFORM_MCP_HUB_CATALOG": os.environ["PLATFORM_MCP_HUB_CATALOG"]}
    params = StdioServerParameters(command=sys.executable, args=["-m", "api_to_mcp", "mcp"], env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            assert init.server_info.name == "api-to-mcp"
            tools = {t.name: t for t in (await s.list_tools()).tools}
            assert sorted(tools) == sorted(["doctor", "workspace", "catalog_search", "catalog_get", "template_entry", "ingest_openapi", "read_docs", "draft_entry",
                                            "save_entry", "lint_entry", "generate_server", "try_tool", "test_server", "live_verify"])
            assert tools["save_entry"].annotations.read_only_hint is False and tools["catalog_get"].annotations.read_only_hint is True
            res = await s.call_tool("catalog_search", {"query": "reed"})
            assert res.is_error is False and res.structured_content["workspace"] == str(ws)
            res = await s.call_tool("catalog_get", {"category": "jobs"})  # missing argument: an isError result, not a crash
            assert res.is_error is True
            res = await s.call_tool("save_entry", {"category": "schema", "id": "vocab", "entry": {"x": 1}})
            assert res.is_error is True and res.structured_content["error"] == "invalid_input"
