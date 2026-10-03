"""Ingestion and lint regressions from the stress test (2026-10, docs/VERIFICATION.md 'Stress test 2026-10'):
input styles api-to-mcp (then "the forge") could not read (Postman, API Blueprint, RAML, WSDL, GraphQL, RSS/Atom, AsyncAPI, multi-file
specs), shapes it reported wrongly, outputs too large for an agent, and lint gaps."""
import json
import sys
from pathlib import Path

import httpx
import pytest
import respx
from platform_mcp_hub import lint as lint_mod

from api_to_mcp import server as forge


async def ingest(**kw):
    res = await forge.server.call_tool("ingest_openapi", kw)
    return res.is_error, res.structured_content


IP = "93.184.215.14"  # every test host resolves to this public address; the forge connects to it (DNS pinning, SR-19)


@pytest.fixture
def public_dns(monkeypatch):
    async def resolve(host):
        return [IP]
    monkeypatch.delenv("PLATFORM_MCP_ALLOW_PRIVATE_URLS", raising=False)
    monkeypatch.setattr(forge, "_resolve_host", resolve)


def at(url: str):
    """(pinned URL, Host header) for a respx route: the guarded fetcher connects to the vetted address."""
    u = httpx.URL(url)
    return str(u.copy_with(host=IP)), {"host": u.host}


# ------------------------------------------------------------------ input styles
POSTMAN = {"info": {"_postman_id": "x", "name": "MEXC V3", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
           "variable": [{"key": "api_url", "value": "https://api.mexc.com"}],
           "item": [{"name": "Market Data", "item": [
               {"name": "Kline", "request": {"method": "GET", "header": [], "url": {"raw": "{{api_url}}/api/v3/klines?symbol=BTCUSDT&interval=1m",
                "host": ["{{api_url}}"], "path": ["api", "v3", "klines"], "query": [{"key": "symbol", "value": "BTCUSDT"}, {"key": "interval", "value": "1m", "description": "ENUM: Kline interval"}]}},
                "response": [{"code": 200, "name": "ok", "body": "[[1,\"2\",\"3\"]]"}]},
               {"name": "Order", "request": {"method": "POST", "header": [{"key": "X-MEXC-APIKEY", "value": "{{api_key}}"}],
                "url": "{{api_url}}/api/v3/order/:orderId?timestamp={{timestamp}}&signature={{signature}}"}}]}]}


@pytest.mark.asyncio
async def test_postman_collection_and_environment():
    err, out = await ingest(source=json.dumps(POSTMAN))
    assert not err and out["format"] == "postman_collection" and out["servers"] == ["https://api.mexc.com"]
    kl, order = out["operations"]
    assert kl["path"] == "/api/v3/klines" and kl["tags"] == ["Market Data"] and "interval(query, example=1m) - ENUM: Kline interval" in kl["params"]
    assert kl["response"]["shape"] == {"type": "array", "items": {"type": "array", "items": "int"}}
    assert order["path"] == "/api/v3/order/{orderId}" and order["signed_params"] == ["X-MEXC-APIKEY", "signature", "timestamp"]
    assert out["unresolved_variables"] == ["api_key", "signature", "timestamp"]
    err, env = await ingest(source=json.dumps({"name": "GLOBAL", "_postman_variable_scope": "environment", "values": [{"key": "api_url", "value": "https://api.mexc.com"}]}))
    assert not err and env["format"] == "postman_environment" and env["variables"] == {"api_url": "https://api.mexc.com"}


APIB = """FORMAT: 1A
HOST: https://coinmate.io/api

# Coinmate API

# Group Ticker

## Ticker [/ticker{?currencyPair}]

### Get ticker [GET]

+ Parameters
    + currencyPair: `BTC_EUR` (string, required) - the pair

+ Response 200 (application/json)

        {"error": false, "data": {"last": 1.5, "bid": 1.4}}
"""


@pytest.mark.asyncio
async def test_api_blueprint_text():
    err, out = await ingest(source=APIB)
    assert not err and out["format"] == "api_blueprint" and out["servers"] == ["https://coinmate.io/api"]
    op = out["operations"][0]
    assert (op["method"], op["path"], op["tags"]) == ("GET", "/ticker", ["Ticker"])
    assert op["params"] == ["currencyPair(query, string, required, example=BTC_EUR) - the pair"]
    assert op["response"]["shape"]["objects"]["data"]["keys"] == ["bid", "last"]


@pytest.mark.asyncio
@respx.mock
async def test_apiary_page_reads_the_parsed_blueprint(public_dns):
    u, h = at("https://coinmate.docs.apiary.io/")
    respx.get(u, headers=h).mock(return_value=httpx.Response(200, html="<!doctype html><html><head></head><body>app</body></html>"))
    u, h = at("https://jsapi.apiary.io/apis/coinmate/blueprint")
    respx.get(u, headers=h).mock(return_value=httpx.Response(200, json={
        "name": "CoinMate", "blueprint": "", "urls": {"production": "https://coinmate.io/api/"}, "resourceGroups": [{"name": "Ticker", "resources": [{
            "name": "Get ticker", "uriTemplate": "/ticker{?currencyPair}", "parameters": [{"key": "currencyPair", "type": "string", "required": True, "example": "BTC_EUR"}],
            "actions": [{"method": "GET", "examples": [{"responses": [{"status": "200", "headers": {"Content-Type": "application/json"}, "body": "{\"data\": {\"last\": 1}}"}]}]}]}]}]}))
    err, out = await ingest(source="https://coinmate.docs.apiary.io/")
    assert not err and out["embedded_in"] == "apiary" and out["operations"][0]["params"] == ["currencyPair(query, required, string, example=BTC_EUR)"]


RAML = """#%RAML 0.8
title: GitHub API
version: v3
baseUri: https://api.github.com
securitySchemes:
  - oauth_2_0: !include securitySchemes/oauth_2_0.raml
/search:
  /repositories:
    get:
      description: Search repositories.
      queryParameters:
        q:
          description: The search terms.
          required: true
        sort:
          enum: [stars, forks]
      responses:
        200:
          body:
            application/json:
              example: '{"total_count": 1, "items": [{"id": 1, "full_name": "a/b"}]}'
"""


@pytest.mark.asyncio
async def test_raml_with_includes():
    err, out = await ingest(source=RAML)
    assert not err and out["format"] == "raml" and out["servers"] == ["https://api.github.com"]
    op = out["operations"][0]
    assert (op["method"], op["path"]) == ("GET", "/search/repositories")
    assert op["params"][0].startswith("q(query, required)") and "enum=stars|forks" in op["params"][1]
    assert op["response"]["shape"]["lists"]["items"] == ["full_name", "id"]


WSDL = """<?xml version="1.0" encoding="utf-8"?>
<wsdl:definitions xmlns:s="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/" xmlns:tns="http://web.cbr.ru/"
  targetNamespace="http://web.cbr.ru/" xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">
 <wsdl:types><s:schema targetNamespace="http://web.cbr.ru/">
  <s:element name="GetCursDynamic"><s:complexType><s:sequence>
   <s:element minOccurs="1" maxOccurs="1" name="FromDate" type="s:dateTime"/><s:element minOccurs="0" maxOccurs="1" name="ValutaCode" type="s:string"/>
  </s:sequence></s:complexType></s:element>
  <s:element name="GetCursDynamicResponse"><s:complexType><s:sequence><s:element minOccurs="0" name="GetCursDynamicResult"><s:complexType><s:sequence><s:element ref="s:schema"/></s:sequence></s:complexType></s:element></s:sequence></s:complexType></s:element>
 </s:schema></wsdl:types>
 <wsdl:message name="GetCursDynamicSoapIn"><wsdl:part name="parameters" element="tns:GetCursDynamic"/></wsdl:message>
 <wsdl:message name="GetCursDynamicSoapOut"><wsdl:part name="parameters" element="tns:GetCursDynamicResponse"/></wsdl:message>
 <wsdl:portType name="DailyInfoSoap"><wsdl:operation name="GetCursDynamic"><wsdl:documentation>Получение динамики курсов</wsdl:documentation>
  <wsdl:input message="tns:GetCursDynamicSoapIn"/><wsdl:output message="tns:GetCursDynamicSoapOut"/></wsdl:operation></wsdl:portType>
 <wsdl:binding name="DailyInfoSoap" type="tns:DailyInfoSoap"><soap:binding transport="http://schemas.xmlsoap.org/soap/http"/>
  <wsdl:operation name="GetCursDynamic"><soap:operation soapAction="http://web.cbr.ru/GetCursDynamic" style="document"/></wsdl:operation></wsdl:binding>
 <wsdl:service name="DailyInfo"><wsdl:port name="DailyInfoSoap" binding="tns:DailyInfoSoap"><soap:address location="http://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"/></wsdl:port></wsdl:service>
</wsdl:definitions>"""


@pytest.mark.asyncio
async def test_wsdl():
    err, out = await ingest(source=WSDL)
    assert not err and out["format"] == "wsdl" and out["servers"] == ["http://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"]
    op = out["operations"][0]
    assert op["soap_action"] == "http://web.cbr.ru/GetCursDynamic" and op["params"] == ["FromDate(dateTime, required)", "ValutaCode(string)"]
    assert op["summary"] == "Получение динамики курсов" and "<a DataSet: an inline XML schema + diffgram rows>" in op["response"]["fields"]
    assert out["authoring"]["xml_root"] == "soap:Envelope"


INTROSPECTION = {"data": {"__schema": {"queryType": {"name": "Query"}, "mutationType": None, "types": [
    {"kind": "OBJECT", "name": "Query", "fields": [
        {"name": "country", "args": [{"name": "code", "type": {"kind": "NON_NULL", "ofType": {"kind": "SCALAR", "name": "ID"}}}], "type": {"kind": "OBJECT", "name": "Country"}},
        {"name": "countries", "args": [{"name": "filter", "type": {"kind": "INPUT_OBJECT", "name": "CountryFilterInput"}}],
         "type": {"kind": "NON_NULL", "ofType": {"kind": "LIST", "ofType": {"kind": "NON_NULL", "ofType": {"kind": "OBJECT", "name": "Country"}}}}}]},
    {"kind": "OBJECT", "name": "Country", "fields": [
        {"name": "code", "args": [], "type": {"kind": "NON_NULL", "ofType": {"kind": "SCALAR", "name": "ID"}}},
        {"name": "name", "args": [{"name": "lang", "type": {"kind": "SCALAR", "name": "String"}}], "type": {"kind": "NON_NULL", "ofType": {"kind": "SCALAR", "name": "String"}}}]},
    {"kind": "INPUT_OBJECT", "name": "CountryFilterInput", "inputFields": [{"name": "code", "type": {"kind": "INPUT_OBJECT", "name": "StringQueryOperatorInput"}}]},
    {"kind": "SCALAR", "name": "ID"}, {"kind": "SCALAR", "name": "String"}]}}}


@pytest.mark.asyncio
@respx.mock
async def test_graphql_introspection_live_and_saved(public_dns):
    u, h = at("https://countries.example/graphql")
    respx.get(u, headers=h).mock(return_value=httpx.Response(204))
    route = respx.post(u, headers=h).mock(return_value=httpx.Response(200, json=INTROSPECTION))
    err, out = await ingest(source="https://countries.example/graphql")
    assert not err and out["format"] == "graphql" and "__schema" in json.loads(route.calls.last.request.content)["query"]
    country = next(o for o in out["operations"] if o["path"] == "country")
    assert country["params"] == ["code(ID!, required)"] and country["response"] == {"type": "Country", "select": ["code: ID!", "name: String! (optional args: lang)"]}
    countries = next(o for o in out["operations"] if o["path"] == "countries")
    assert countries["response"]["type"] == "[Country!]!" and countries["input_types"] == {"CountryFilterInput": ["code: StringQueryOperatorInput"]}
    assert out["authoring"]["envelope"] == {"fail_if_present": ["errors.0"], "error_field": "errors.0.message"}
    err, saved = await ingest(source=json.dumps(INTROSPECTION))
    assert not err and saved["format"] == "graphql" and saved["operations_total"] == 2


@pytest.mark.asyncio
async def test_feeds_are_summarised_not_rejected():
    rss = ('\ufeff<?xml version="1.0" encoding="utf-8" ?><rss version="2.0"><channel><title>FRB</title>'
           '<item><title>A</title><link>https://x/a</link><pubDate>Wed, 30 Sep 2026 13:00:00 GMT</pubDate></item><item><title>B</title></item></channel></rss>')
    err, out = await ingest(source=rss)
    assert not err and (out["format"], out["items_path"], out["items_count"]) == ("rss2", "rss.channel.item", 2) and out["item_keys"] == ["link", "pubDate", "title"]
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:os="http://a9.com/-/spec/opensearch/1.1/"><os:totalResults>3</os:totalResults>'
            '<entry><id>1</id><link href="https://x/1" rel="alternate"/></entry></feed>')
    err, out = await ingest(source=atom)
    assert not err and out["format"] == "atom" and out["items_path"] == "feed.entry" and '"@href": "https://x/1"' in out["example_item"]


@pytest.mark.asyncio
async def test_asyncapi_is_explained():
    err, out = await ingest(source="asyncapi: 3.1.0\ninfo:\n  title: Gemini Market Data Websocket API\nservers:\n  public:\n    host: api.gemini.com\n    protocol: wss\nchannels:\n  marketDataV1: {}\n")
    assert err and out["error"] == "not_openapi" and out["format"] == "asyncapi" and out["channels"] == ["marketDataV1"] and "HTTP" in out["message"]


# ------------------------------------------------------------------ OpenAPI details
@pytest.mark.asyncio
async def test_external_refs_in_a_multi_file_spec(tmp_path):
    (tmp_path / "parameters").mkdir()
    (tmp_path / "parameters" / "cc.yaml").write_text("components:\n  parameters:\n    Cc:\n      name: cc\n      in: query\n      schema: {type: string}\n")
    (tmp_path / "responses").mkdir()
    (tmp_path / "responses" / "product.yaml").write_text("type: object\nproperties:\n  product:\n    $ref: '#/components/schemas/P'\ncomponents:\n  schemas:\n    P:\n      type: object\n      properties: {code: {type: string}, brands: {type: string}}\n")
    (tmp_path / "api.yaml").write_text("openapi: 3.1.0\ninfo: {title: OFF, version: '2'}\npaths:\n  /api/v2/product/{code}:\n    get:\n      parameters:\n        - {name: code, in: path, required: true, schema: {type: string}}\n"
                                       "        - $ref: './parameters/cc.yaml#/components/parameters/Cc'\n      responses:\n        '200':\n          content:\n            application/json:\n              schema:\n                $ref: './responses/product.yaml'\n")
    err, out = await ingest(source=str(tmp_path / "api.yaml"))
    assert not err and out["external_refs"] == {"files_resolved": 2}
    op = out["operations"][0]
    assert op["params"] == ["code(path, required, string)", "cc(query, string)"] and op["response"]["shape"]["objects"]["product"]["keys"] == ["brands", "code"]


@pytest.mark.asyncio
async def test_shapes_examples_defaults_servers_media(public_dns):
    spec = {"openapi": "3.0.0", "info": {"title": "t", "version": "1"}, "paths": {
        "/public/OHLC": {"get": {"parameters": [{"name": "x", "in": "query", "schema": {"type": "string", "default": None, "enum": [1, None]}}], "responses": {"200": {"content": {
            "text/plain": {"schema": {"type": "string"}},
            "application/json": {"schema": {"$ref": "#/components/schemas/ohlc", "example": {"error": [], "result": {"XXBTZUSD": [[1, "2"]], "last": 3}}}}}}}}},
        "/m": {"get": {"responses": {"200": {"content": {"application/json": {"schema": {"type": "object", "properties": {"market": {"type": "object", "properties": {"ticker": {"type": "string"}, "status": {"type": "string"}}}}}}}}}}}},
        "components": {"schemas": {"ohlc": {"type": "object", "properties": {"error": {"type": "array", "items": {"type": "string"}},
            "result": {"type": "object", "properties": {"last": {"type": "integer"}}, "additionalProperties": {"type": "array", "items": {"type": "array", "items": {}}}}}}}}}
    forge_src = "https://api.example.test/spec.json"
    with respx.mock:
        u, h = at(forge_src)
        respx.get(u, headers=h).mock(return_value=httpx.Response(200, json=spec))
        err, out = await ingest(source=forge_src)
    assert not err and out["servers"] == ["https://api.example.test"]  # no servers: the document's own host
    ohlc, m = out["operations"]
    assert ohlc["params"] == ["x(query, string, enum=1|null, default=null)"]
    assert ohlc["response"]["content_type"] == "application/json" and '"last": 3' in ohlc["response"]["example"]
    assert ohlc["response"]["shape"]["objects"]["result"]["other_keys"] is True
    assert m["response"]["shape"]["objects"]["market"]["keys"] == ["status", "ticker"]


@pytest.mark.asyncio
async def test_large_unfiltered_spec_is_an_index_and_keys_keep_identity():
    props = {f"k{i:03d}_url": {"type": "string"} for i in range(80)} | {"name": {"type": "string"}, "html_url": {"type": "string"}, "id": {"type": "integer"}}
    paths = {f"/r{i}": {"get": {"tags": ["repos" if i % 2 else "orgs"], "summary": f"op {i}", "responses": {"200": {"content": {"application/json": {"schema": {"type": "array", "items": {"type": "object", "properties": props}}}}}}}} for i in range(70)}
    err, out = await ingest(source=json.dumps({"openapi": "3.0.0", "info": {"title": "big", "version": "1"}, "paths": paths}))
    assert not err and out["index_only"] is True and out["tags"] == {"repos": 35, "orgs": 35} and out["operations"][0] == "GET /r0 - op 0"
    err, one = await ingest(source=json.dumps({"openapi": "3.0.0", "info": {"title": "big", "version": "1"}, "paths": paths}), filter="/r1\"")
    keys = one["operations"][0]["response"]["shape"]["item_keys"]
    assert keys[:3] == ["id", "name", "html_url"] and keys[-1] == "... +23 more keys" and len(keys) == 61


@pytest.mark.asyncio
async def test_oversized_specs_are_refused_while_downloading(tmp_path, monkeypatch, public_dns):
    monkeypatch.setattr(forge, "MAX_SPEC_BYTES", 1000)
    big = tmp_path / "big.json"  # a local file over the cap
    big.write_text(json.dumps({"openapi": "3.0.0", "pad": "x" * 2000}))
    err, out = await ingest(source=str(big))
    assert err and out["error"] == "too_large" and out["size_bytes"] > 1000
    with respx.mock:
        u, h = at("https://specs.example/huge.yaml")
        route = respx.get(u, headers=h).mock(return_value=httpx.Response(200, headers={"content-encoding": "identity"}, content=b"x" * 5000))
        err, out = await ingest(source="https://specs.example/huge.yaml")
    assert err and out["error"] == "too_large" and "larger than" in out["message"] and route.called


@pytest.mark.asyncio
async def test_spec_links_skip_assets():
    html = ('<!doctype html><html><head><link href="/valet/static/swagger/favicon.ico" rel="icon"><script src="/static/swagger/swagger-ui.js"></script>'
            '</head><body><a href="https://docs.kraken.com/openapi/spot-rest.yaml">spec</a></body></html>')
    err, out = await ingest(source=html)
    assert err and out["error"] == "not_openapi" and out["spec_links"] == ["https://docs.kraken.com/openapi/spot-rest.yaml"]


def test_run_keeps_whole_json_reports():
    out = forge._run([sys.executable, "-c", "print('x' * 9000)"], max_stdout=None)
    assert len(out["stdout"].strip()) == 9000
    assert len(forge._run([sys.executable, "-c", "print('x' * 9000)"])["stdout"]) == 6000


def test_try_tool_structure_collapses_maps_keyed_by_id():
    from platform_mcp_hub import trytool as try_tool
    s = try_tool.structure({"result": {f"P{i}": {"altname": "x", "base": "y"} for i in range(600)}})
    assert s == {"result": {"_keys": "600 keys, e.g. P0, P1, P2, P3, P4", "_value": {"altname": "str", "base": "str"}}}


# ------------------------------------------------------------------ lint
def _entry(tool: dict, envelope=None, category="trading", verb="get_ticker") -> Path:
    import tempfile
    d = Path(tempfile.mkdtemp()) / category
    d.mkdir()
    e = {"id": "x_stress", "category": category, "label": "x", "docs_url": "https://x/docs", "verified_at": "2026-10-01", "version": "0.1.0",
         "adapter": {"base_url": "https://x", "auth": {"type": "none"}, "tools": {verb: {"docs": "https://x/d", **tool}}, **({"envelope": envelope} if envelope else {})}}
    p = d / "x_stress.json"
    p.write_text(json.dumps(e))
    return p


def test_lint_catches_what_the_runtimes_would_ignore_or_crash_on():
    errs, _ = lint_mod.lint(_entry({"method": "GET", "path": "/t", "result": {"root": "r", "fields": {"symbol": "s", "last": 1}}, "itme": 1}))
    assert any("result.fields.last must be a non-empty string" in e for e in errs) and any("unknown key 'itme'" in e for e in errs)
    errs, _ = lint_mod.lint(_entry({"method": "GET", "path": "/t", "result": {"items": "$", "key": "candles", "cap": "middle", "slices": True, "fields": {"time": "0"}}}, verb="get_candles"))
    assert any("result.cap must be head or tail" in e for e in errs) and any("unknown result key 'slices'" in e for e in errs)
    errs, _ = lint_mod.lint(_entry({"method": "GET", "path": "/t", "result": {"root": "r", "fields": {"symbol": "s"}}}, envelope={"fail_if_present": "error", "ok_feild": "x"}))
    assert any("fail_if_present must be a non-empty list" in e for e in errs) and any("unknown key 'ok_feild'" in e for e in errs)
    errs, _ = lint_mod.lint(_entry({"method": "GET", "path": "t", "csv": {"delimiter": ";;"}, "result": {"root": "{nope}", "fields": {"symbol": "num:{symbol}.v|{other}"}}}))
    assert any("path required" in e for e in errs) and any("csv must be" in e for e in errs)
    assert any("result.root names argument {nope}" in e for e in errs) and any("names argument {other}" in e for e in errs)


def test_lint_accepts_the_new_options():
    errs, _ = lint_mod.lint(_entry({"method": "POST", "path": "", "csv": {"delimiter": "|", "skip_lines": 1},
                                    "params": {"w": "part:0:series_id", "f": "fmt:a:{series_id}[?,b:{date:start}]"},
                                    "result": {"items": "rows", "key": "points", "cap": "tail", "filter": [{"arg": "series_id", "fields": ["raw.D0"], "match": "equals", "value": "part:1:series_id"}],
                                               "fields": {"time": "isodate:%d.%m.%Y:Datum", "value": "num_comma:{series_id}"}}}, category="market_data", verb="get_series"),
                             )
    assert errs == []
    errs, _ = lint_mod.lint(_entry({"method": "GET", "path": "/n", "result": {"items": "$", "key": "articles", "filter": [{"arg": "since", "fields": ["published_at"], "match": "gte"}],
                                    "fields": {"id": "i", "title": "t"}}}, category="market_data", verb="get_news"))
    assert any("result.filter on a paged verb needs result.slice" in e for e in errs)  # get_news pages: a server-paged list would lose rows
