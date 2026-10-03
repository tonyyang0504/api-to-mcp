# Tools

The api-to-mcp MCP server (`api-to-mcp mcp`), so any MCP client (Claude Code, Claude Desktop, Cursor, ...) can turn API
documentation into a standard server. The model does the reading and the evidence-only authoring (see
`skills/api-to-mcp/SKILL.md`); these tools run the deterministic steps. Every tool also exists as a CLI command
(`api-to-mcp --help`).

| tool | CLI | what it does |
|---|---|---|
| `doctor` | `api-to-mcp doctor [--fix]` | preflight: the workspace, the Python gate dependencies (platform-mcp-hub, pytest, respx, ...), uv, node >= 20 + npm, platform-mcp-hub's TypeScript runtime; exact install commands per OS; `fix: true` builds a checkout's TypeScript runtime; `mode` full / python_only / blocked |
| `workspace` | `api-to-mcp workspace` | where entries are saved (your own directory, or a platform-mcp checkout) and the entries there |
| `catalog_search` | `api-to-mcp search <text>` | existing entries by id, label, category, country, docs URL or API host: yours and those bundled with the runtime (`source` says which) |
| `catalog_get` | `api-to-mcp get <category> <id>` | one entry's JSON (a wrong category names the categories the id exists in) |
| `template_entry` | `api-to-mcp template [generic\|<category>]` | default `generic`: a skeleton, an example and the adapter contract; a category name gives its verbs with schemas and a live-verified example of the category |
| `ingest_openapi` | `api-to-mcp ingest <url\|file\|->` | OpenAPI 3.x / Swagger 2 (URL, file path or text; JSON or YAML; external `$ref` files fetched), Postman collections/environments, API Blueprint (text or Apiary), RAML, WSDL, GraphQL (introspection), RSS/Atom/XML → servers, security, operations with resolved parameters, body keys, response shapes, examples, rate limits, paging parameters; over 60 operations without `filter` → a one-line index; an HTML page → `not_openapi` + spec links; AsyncAPI → explained; over 25 MB → `too_large` |
| `draft_entry` | `api-to-mcp draft <spec> <id>` | a **generic** entry from an OpenAPI 3 / Swagger 2 description: one tool per chosen operation (`operations`, `filter`, `limit`), input schemas from the parameters and body, path placeholders, auth from the security schemes, docs links, and notes for what it could not draft; not saved |
| `read_docs` | `api-to-mcp read-docs <url>` | the readable text of one documentation page, in windows, with its links; public hosts only; `reader: true` for JS-rendered pages |
| `save_entry` | `api-to-mcp save <category> <id> <file>` | writes `catalog/<category>/<id>.json` in the workspace (vocabulary categories only; refuses `adapter: null`, id/category mismatches) |
| `lint_entry` | `api-to-mcp lint <category> <id>` | platform-mcp-hub's catalog lint for one entry, as `{errors, warnings}` |
| `generate_server` | `api-to-mcp generate <category> <id>` | your workspace: `servers/<category>/<id>/mcp.json` (client config for `platform-mcp-hub serve --entry`) and a README; a checkout: its registry metadata; both: a contract-test template (refuses entries with lint errors) |
| `try_tool` | `api-to-mcp try <category> <id> <verb> [json]` | one read call through the runtime: request sent, raw response structure, mapped result |
| `test_server` | `api-to-mcp test <category> <id>` | lint + contract tests + stdio smoke of `platform-mcp-hub serve --entry` in both runtimes (no network; a missing Python contract test fails) |
| `live_verify` | `api-to-mcp verify <category> <id>` | real read calls over stdio in both languages, validated against the vocabulary (`plan` for arguments; `record: true` writes `live_check`) |

Every failure is a tool result with `isError` and an `error` code (`invalid_input`, `not_found`, `invalid_entry`,
`not_openapi`, `too_large`, `upstream_error`, `blocked_url`, `lint_failed`, `not_generated`, `prerequisite_missing`,
...), never a protocol error.

**Prerequisites.** Python 3.10+ with api-to-mcp installed (it brings its runtime, platform-mcp-hub, and the gates' test tools);
`uv` when Claude Code starts it from the plugin; for the TypeScript half `node` >= 20 and platform-mcp-hub's TypeScript
runtime (`PLATFORM_MCP_HUB_TS_CLI`, a global npm install, or a checkout, which `test_server` and `live_verify` build
themselves when node, npm and the lockfile are present; `API_TO_MCP_AUTOBUILD=0` turns that off). Without it,
`test_server` and `live_verify` run the Python half only and return `mode: python_only` with a warning.

**Workspace.** Your own directory by default (`API_TO_MCP_HOME`, else `$XDG_DATA_HOME/api-to-mcp`, else
`~/.local/share/api-to-mcp`), or optionally a checkout of the runtime's repository (`API_TO_MCP_CHECKOUT`, or
`--checkout` on the CLI). Results name it.

**Run it.**

    api-to-mcp mcp                       # stdio (what MCP clients start)
    api-to-mcp mcp --http --port 8090    # Streamable HTTP on 127.0.0.1
    claude mcp add api-to-mcp -- api-to-mcp mcp

Plugin MCP tools are named `mcp__plugin_api-to-mcp_api-to-mcp__<tool>`; added with `claude mcp add`, they are
`mcp__api-to-mcp__<tool>`.

How it was verified end to end (real APIs, defects found and fixed, limits): [`VERIFICATION.md`](VERIFICATION.md).
