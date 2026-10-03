"""Generic mode (the default for your own workspace): tools straight from an API's own operations, no category
vocabulary. draft_entry turns an OpenAPI/Swagger description into such an entry; the same lint, run config, contract
test template, smoke test and live verification apply as for every entry."""
import json

import httpx
import pytest
import respx
from conftest import HAS_TS, _public, call  # noqa: F401

from api_to_mcp import server as forge

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Probe Store", "version": "1", "description": "Rate limit: 5 requests per second."},
    "servers": [{"url": "https://api.probe.example/v1"}],
    "components": {
        "securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Api-Key"}},
        "schemas": {"Item": {"type": "object", "properties": {"id": {"type": "string"}, "name": {"type": "string"}}},
                    "NewItem": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string", "description": "Display name"},
                                                                                      "tags": {"type": "array", "items": {"type": "string"}}}}},
        "parameters": {"Limit": {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20, "maximum": 100}}},
    },
    "security": [{"key": []}],
    "paths": {
        "/items": {
            "get": {"operationId": "listItems", "summary": "List items", "description": "Items, newest first.",
                    "parameters": [{"$ref": "#/components/parameters/Limit"},
                                   {"name": "fields", "in": "query", "explode": False, "description": "Fields to return.",
                                    "schema": {"type": "array", "items": {"type": "string", "enum": ["id", "name", "tags"]}}},
                                   {"name": "X-Trace", "in": "header", "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "ok"}}},
            "post": {"operationId": "createItem", "summary": "Create an item",
                     "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/NewItem"}}}},
                     "responses": {"201": {"description": "created"}}},
        },
        "/items/{item-id}": {
            "parameters": [{"name": "item-id", "in": "path", "required": True, "schema": {"type": "string"}}],
            "get": {"operationId": "getItem", "summary": "Get an item", "externalDocs": {"url": "https://docs.probe.example/items#get"},
                    "responses": {"200": {"description": "ok"}}},
            "delete": {"operationId": "deleteItem", "summary": "Delete an item", "responses": {"204": {"description": "gone"}}},
        },
        "/search": {"post": {"operationId": "searchItems", "summary": "Search items",
                             "requestBody": {"content": {"application/x-www-form-urlencoded": {"schema": {"type": "object", "properties": {"q": {"type": "string"}}}}}},
                             "responses": {"200": {"description": "ok"}}}},
        "/legacy": {"get": {"operationId": "legacy", "deprecated": True, "responses": {"200": {"description": "ok"}}}},
        "/regional": {"servers": [{"url": "https://eu.probe.example"}], "get": {"operationId": "regional", "responses": {"200": {"description": "ok"}}}},
    },
}


async def draft(**kw):
    return await call("draft_entry", {"source": json.dumps(SPEC), "id": "probe_store", **kw})


@pytest.mark.asyncio
async def test_draft_builds_tools_from_the_operations(ws):
    err, out = await draft(docs_url="https://docs.probe.example/api")
    assert not err, out
    e = out["entry"]
    assert e["category"] == "generic" and e["id"] == "probe_store" and e["label"] == "Probe Store" and e["docs_url"] == "https://docs.probe.example/api"
    a = e["adapter"]
    assert a["base_url"] == "https://api.probe.example/v1"
    assert a["auth"] == {"type": "header", "header": "X-Api-Key", "field": "api_key", "fields": [
        {"name": "api_key", "required": True, "help": "API key sent as the X-Api-Key header: key (securitySchemes.key)"}]}
    t = a["tools"]
    assert sorted(t) == ["create_item", "delete_item", "get_item", "list_items", "regional", "search_items"]  # deprecated `legacy` left out
    li = t["list_items"]
    assert li["method"] == "GET" and li["path"] == "/items" and li["title"] == "List items" and li["description"] == "List items Items, newest first."
    assert li["params"] == {"limit": "limit", "fields": "fields"}
    assert li["input"]["properties"]["limit"] == {"type": "integer", "default": 20, "maximum": 100}
    assert li["input"]["properties"]["fields"]["type"] == "string" and "Comma-separated list. Allowed: id, name, tags" in li["input"]["properties"]["fields"]["description"]
    assert "X-Trace" not in json.dumps(li["input"]) and any("header parameter 'X-Trace'" in n for n in out["notes"])
    gi = t["get_item"]
    assert gi["path"] == "/items/{item_id}" and gi["input"]["required"] == ["item_id"] and gi["docs"] == "https://docs.probe.example/items#get"
    ci = t["create_item"]
    assert ci["body"] == {"name": "name", "tags": "tags"} and ci["input"]["required"] == ["name"] and ci["input"]["properties"]["tags"]["type"] == "array"
    assert t["search_items"]["body_format"] == "form" and any("search_items" in n and "read_only" in n for n in out["notes"])
    assert t["delete_item"]["docs"] == "https://docs.probe.example/api#deleteItem"
    assert any("rate limit (5 requests per second)" in n for n in out["notes"])
    assert out["operations_total"] == 7 and out["next"].startswith("Check every tool")


@pytest.mark.asyncio
async def test_draft_selects_operations_filters_and_limits(ws):
    err, out = await draft(operations=["getItem", "POST /items", "nope"])
    assert not err and sorted(out["entry"]["adapter"]["tools"]) == ["create_item", "get_item"]
    assert any("not found in the spec: ['nope']" in n for n in out["notes"])
    err, out = await draft(filter="search")
    assert list(out["entry"]["adapter"]["tools"]) == ["search_items"]
    err, out = await draft(limit=2)
    assert len(out["entry"]["adapter"]["tools"]) == 2 and any("drafted the first 2 (GET first)" in n for n in out["notes"])
    assert all(t["method"] == "GET" for t in out["entry"]["adapter"]["tools"].values())
    err, out = await draft(operations=["regional"])
    assert out["entry"]["adapter"]["base_url"] == "https://api.probe.example/v1"  # the spec's own server still comes first
    spec = {**SPEC, "servers": []}
    err, out = await call("draft_entry", {"source": json.dumps(spec), "id": "probe_store", "operations": ["regional"]})
    assert out["entry"]["adapter"]["base_url"] == "https://eu.probe.example"  # the operation's own server


@pytest.mark.asyncio
async def test_draft_auth_variants(ws):
    def with_scheme(scheme, security):
        return {**SPEC, "components": {**SPEC["components"], "securitySchemes": {"s": scheme}}, "security": security}
    cases = [
        ({"type": "apiKey", "in": "query", "name": "apikey"}, [{}, {"s": []}], {"type": "none", "params": {"apikey": "api_key"}}),
        ({"type": "http", "scheme": "basic"}, [{"s": []}], {"type": "basic", "username_field": "username", "password_field": "password"}),
        ({"type": "http", "scheme": "bearer"}, [{"s": []}], {"type": "bearer", "field": "token"}),
        ({"type": "oauth2", "flows": {}}, [{"s": []}], {"type": "bearer", "field": "token"}),
        ({"type": "http", "scheme": "bearer"}, [{}], {"type": "none"}),
    ]
    for scheme, security, want in cases:
        err, out = await call("draft_entry", {"source": json.dumps(with_scheme(scheme, security)), "id": "probe_store"})
        auth = out["entry"]["adapter"]["auth"]
        assert {k: v for k, v in auth.items() if k != "fields"} == want, (scheme, auth)


@pytest.mark.asyncio
@respx.mock
async def test_draft_refuses_what_it_cannot_read(ws, monkeypatch):
    err, out = await call("draft_entry", {"source": json.dumps({"info": {"_postman_id": "x"}, "item": []}), "id": "probe_store"})
    assert err and out["error"] == "not_openapi" and "template_entry('generic')" in out["message"]
    html = '<!doctype html><html><head></head><body><a href="/openapi.yaml">spec</a></body></html>'
    respx.get("https://93.184.215.14/docs", headers={"host": "docs.probe.example"}).mock(return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"}))
    err, out = await call("draft_entry", {"source": "https://docs.probe.example/docs", "id": "probe_store"})
    assert err and out["error"] == "not_openapi" and out["spec_links"] == ["https://docs.probe.example/openapi.yaml"]

    async def private(host):
        return ["10.0.0.7"]
    monkeypatch.delenv("PLATFORM_MCP_ALLOW_PRIVATE_URLS", raising=False)
    monkeypatch.setattr(forge, "_resolve_host", private)
    err, out = await call("draft_entry", {"source": "https://intranet.probe.example/openapi.json", "id": "probe_store"})
    assert err and out["error"] == "blocked_url"
    for bad in ({"source": "x", "id": "Bad Id"}, {"source": "", "id": "probe_store"}, {"source": "x", "id": "probe_store", "docs_url": "http://plain"}):
        err, out = await call("draft_entry", bad)
        assert err and out["error"] == "invalid_input", bad


@pytest.mark.asyncio
async def test_template_defaults_to_generic(ws):
    err, out = await call("template_entry", {})
    assert not err and out["category"] == "generic" and out["verbs"] is None
    assert out["skeleton"]["category"] == "generic" and "select_fields" in json.dumps(out["adapter_reference"])
    assert "Generic entries" in out["rules"]
    err, out = await call("template_entry", {"category": "jobs"})
    assert not err and "search" in out["verbs"]  # the category vocabulary stays available for contributing


@pytest.mark.asyncio
async def test_a_drafted_entry_passes_every_gate_in_your_own_workspace(ws):
    err, out = await draft(operations=["listItems", "getItem", "createItem"], docs_url="https://docs.probe.example/api")
    entry = out["entry"]
    err, saved = await call("save_entry", {"category": "generic", "id": "probe_store", "entry": entry})
    assert not err and saved["saved"] == "catalog/generic/probe_store.json"
    err, lint = await call("lint_entry", {"category": "generic", "id": "probe_store"})
    assert not err and lint["errors"] == [], lint
    err, gen = await call("generate_server", {"category": "generic", "id": "probe_store"})
    assert not err and gen["mode"] == "user" and gen["files"] == ["servers/generic/probe_store/README.md", "servers/generic/probe_store/mcp.json"]
    assert gen["contract_test"] == {"path": "tests/test_probe_store_python.py", "created": True, "next": gen["contract_test"]["next"]}
    err, test = await call("test_server", {"category": "generic", "id": "probe_store"})
    assert not err and test["ok"] is True and test["python_tests"]["ok"] is True, test
    runs = {r["lang"]: r for r in test["smoke"]["runs"]}
    assert runs["py"]["ok"] and sorted(runs["py"]["tools"]) == ["create_item", "get_item", "list_items"]
    if HAS_TS:
        assert runs["ts"]["ok"] and runs["ts"]["tools"] == runs["py"]["tools"]
    err, w = await call("try_tool", {"category": "generic", "id": "probe_store", "verb": "create_item", "arguments": {"name": "x"}})
    assert err and "write tool" in w["message"]  # writes are never called by the authoring tools


@pytest.mark.asyncio
@respx.mock
async def test_try_tool_on_a_generic_entry_shows_the_passed_through_answer(ws, monkeypatch):
    from platform_mcp_hub import trytool as tt
    err, out = await draft(operations=["listItems"])
    entry = {**out["entry"], "adapter": {**out["entry"]["adapter"], "auth": {"type": "none"}}}
    route = respx.get("https://api.probe.example/v1/items").mock(return_value=httpx.Response(200, json=[{"id": "1", "name": "a", "tags": ["t"]}]))
    monkeypatch.setattr(tt.egress_guard, "RESOLVER", _public)
    res = await tt.run(entry, "list_items", {"limit": 5, "select_fields": ["id"]}, 4000)
    assert route.called and res["ok"] and res["result"] == {"data": [{"id": "1"}]} and res["request"]["params"] == {"limit": 5}
