# api-to-mcp

Turn an API's documentation into a working MCP server. Give it a docs URL, an OpenAPI/Swagger file, a Postman
collection, RAML, WSDL, a GraphQL endpoint, an HTML reference page or pasted text; the model reads it and writes an
**evidence-only entry** (every tool cites the documented endpoint), and api-to-mcp runs the deterministic steps: lint,
run config, contract tests, a stdio smoke test in Python and TypeScript, and a live verification against the real API.

The result is not generated code. It is one JSON entry describing the API, which the runtime serves as an MCP server:
`api-to-mcp serve <category> <id>` (or `platform-mcp-hub serve --entry my_entry.json`). By default the entry is
**generic**: its tools are the API's own operations (from an OpenAPI/Swagger description, `draft_entry` writes them),
and the answer is passed through, with optional field selection. Any HTTP API qualifies.

## Three ways to use it

- **Claude Code plugin** (skill `/api-to-mcp`, the `api-to-mcp` agent and the MCP server together):
  ```bash
  claude plugin marketplace add tonyyang0504/api-to-mcp
  claude plugin install api-to-mcp@api-to-mcp
  ```
  Then: `/api-to-mcp https://developer.example.com/openapi.json`, or ask the `api-to-mcp` agent. Needs `uv` on PATH.
- **Any MCP client**: `api-to-mcp mcp` (stdio) or `api-to-mcp mcp --http --port 8090`. Tools: `doctor`, `workspace`,
  `catalog_search`, `catalog_get`, `template_entry`, `ingest_openapi`, `read_docs`, `draft_entry`, `save_entry`, `lint_entry`,
  `generate_server`, `try_tool`, `test_server`, `live_verify` ([docs/TOOLS.md](docs/TOOLS.md)).
- **CLI**: every tool is a command: `api-to-mcp ingest <url>`, `api-to-mcp save jobs my_board entry.json`,
  `api-to-mcp test jobs my_board`, `api-to-mcp serve jobs my_board`, ... (`api-to-mcp --help`).

## Install

```bash
uvx --from api-to-mcp-forge api-to-mcp doctor      # or: pip install api-to-mcp-forge / uv tool install api-to-mcp-forge
```

The PyPI package is `api-to-mcp-forge` (PyPI treats `api-to-mcp` as a duplicate of an older, unrelated `apitomcp`); the
command is `api-to-mcp`. It brings `platform-mcp-hub` (the runtime) with it; for the TypeScript half of the gates also
`npm install -g platform-mcp-hub`.

## Quick start (from source)

```bash
git clone https://github.com/tonyyang0504/api-to-mcp && cd api-to-mcp
uv venv -p 3.12
uv pip install -e .
.venv/bin/api-to-mcp doctor                        # prerequisites and where entries will be saved
.venv/bin/api-to-mcp ingest https://raw.githubusercontent.com/PokeAPI/pokeapi/master/openapi.yml --filter pokemon
.venv/bin/api-to-mcp draft https://raw.githubusercontent.com/PokeAPI/pokeapi/master/openapi.yml pokeapi \
    --operations pokemon_list,pokemon_retrieve > draft.json        # tools straight from the API's operations
# review the draft (the skill/agent does this), then:
.venv/bin/api-to-mcp save generic pokeapi draft.json && .venv/bin/api-to-mcp lint generic pokeapi
.venv/bin/api-to-mcp generate generic pokeapi      # run config + a starting contract test (tests/test_pokeapi_python.py)
.venv/bin/api-to-mcp test generic pokeapi          # lint + contract test + stdio smoke (both runtimes)
.venv/bin/api-to-mcp verify generic pokeapi --plan '{"args": {"pokemon_retrieve": {"id": "pikachu"}, "pokemon_list": {"limit": 5}}}'
claude mcp add pokeapi -- "$PWD/.venv/bin/api-to-mcp" serve generic pokeapi
```


## Where entries go

- **Your own workspace (default)**: `API_TO_MCP_HOME`, else `$XDG_DATA_HOME/api-to-mcp`, else
  `~/.local/share/api-to-mcp`. Nothing else is needed: the vocabularies, the lint and the runtime are installed with
  api-to-mcp. `generate_server` writes an MCP client config (`servers/<category>/<id>/mcp.json`).
- **Optional: a runtime checkout.** `API_TO_MCP_CHECKOUT=<checkout of the runtime's repository>` (or `--checkout <dir>`)
  saves entries into that checkout's catalog, writes its registry metadata and runs its contract tests, for contributing
  an entry upstream.

## What it will not do

Documentation is treated as untrusted data: api-to-mcp fetches only public hosts (every redirect re-checked, connections
pinned to the vetted address, downloads capped at 25 MB), reads local specs only from spec files outside hidden
directories, and never follows instructions found in a document. The agent has no shell and no free web fetch. Live
verification calls read tools only. See [SECURITY.md](SECURITY.md).

## Limits (honest list)

- **The model does the judgement.** Entry quality depends on the model reading the docs carefully; the gates catch
  structural mistakes (unknown arguments, wrong result paths, schema violations), not every misreading.
- **What the runtime can express.** REST/JSON, form and XML bodies, SOAP, GraphQL over POST, RSS/Atom, CSV; auth by
  header, query, basic, bearer, session login, OAuth2 client credentials and refresh tokens, HMAC and OAuth 1.0a
  signing. No OAuth authorization-code flow in the server (you obtain the refresh token once), no WebSockets
  (AsyncAPI is explained, not served), no file streaming beyond the documented upload verbs.
- **Generic answers are the API's own.** A generic tool returns what the API returns (narrowed by root and selected
  fields, long lists cut at `max_items`); it does not normalise records across APIs. The optional category mode does,
  for the categories its vocabularies cover.
- **Drafts need review.** `draft_entry` reads OpenAPI 3 and Swagger 2 only; it cannot know which POSTs merely read, which
  parameters the live API ignores, or which of hundreds of operations you need. Other formats are written by hand.
- **Live checks need access.** Keyless APIs are verified live; others need your credentials, and write tools are never
  called live.
- **TypeScript half.** Without node and platform-mcp-hub's TypeScript runtime the gates run Python only, and say so.

## Built on

The runtime that serves entries, validates them and runs the checks is the `platform-mcp-hub` library
([platform-mcp](https://github.com/tonyyang0504/platform-mcp)), installed as an ordinary dependency.

How api-to-mcp was verified end to end, the defects found and the limits: [docs/VERIFICATION.md](docs/VERIFICATION.md).

## Contributing and licence

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md) (DCO sign-off) and the
[Code of Conduct](CODE_OF_CONDUCT.md). Changes: [CHANGELOG.md](CHANGELOG.md). Licence: Apache-2.0 (`LICENSE`, `NOTICE`).
