# Verification

> **Names.** Until 2026-10 api-to-mcp was "the forge" inside platform-mcp: `forge/platform_mcp_forge/server.py`,
> the `platform-mcp-forge` MCP server and plugin, the `/mcp-forge` skill and the `mcp-forge` agent, with the gates in
> platform-mcp's `tools/` (now `platform-mcp-hub lint|try|smoke|verify`) and one generated package per platform (now
> `platform-mcp-hub serve`). This page keeps the names and paths of the day each run was made.

The forge (`forge/platform_mcp_forge/server.py`, the `/mcp-forge` skill, the `mcp-forge` agent and the
Claude Code plugin) was audited, unit-tested and run end to end for the first time on 2026-09-27.
This page records the runs, every defect found and how it was fixed, and what remains limited.

## How the runs were done

Every run drove the forge's own MCP server **over stdio, as an MCP client does** (a small
`mcp.client.stdio` driver, forge started with `uv run --project forge platform-mcp-forge`, working
directory outside the checkout so the workspace came from `PLATFORM_MCP_ROOT`). For each API:
`catalog_search` → `ingest_openapi` (or reading the HTML docs) → `template_entry` → `save_entry` →
`lint_entry` → `generate_server` → `try_tool` (once it existed) → `test_server` → `live_verify` (real read calls through
both generated servers, results validated against the vocabulary's output schemas by
`tools/live_verify.py`, Python/TypeScript parity compared). The six APIs are public, keyless and
were not in the catalog before. The first pass used the forge as it was; defects were fixed as they
appeared and each run was repeated until it passed.

## End-to-end results

| API | input shape | category / verbs served | live result (residential egress, both languages) |
|---|---|---|---|
| [Frankfurter](https://frankfurter.dev/) | OpenAPI **3.1 JSON URL** (`https://api.frankfurter.dev/v2/openapi.json`) | market_data: `search_symbols`, `get_series` | working, parity equal |
| [Mercado Bitcoin](https://api.mercadobitcoin.net/api/v4/docs) | **Swagger 2 YAML URL** (`/api/v4/docs/swagger.yaml`) | trading: `list_markets`, `get_ticker`, `get_candles` | working, page 2 advances, parity equal |
| [NHTSA vPIC](https://vpic.nhtsa.dot.gov/api/) | **HTML-only docs** | automotive: `decode_vin` | working, parity equal |
| [OpenFIGI](https://www.openfigi.com/api/documentation) | **local spec file** (the JSON from `https://api.openfigi.com/schema`, ingested by path) | market_data: `search_symbols` (**cursor pagination**) | working, page 2 advances by cursor, parity equal |
| [Codeforces](https://codeforces.com/apiHelp) | **HTML-only docs** (403 to curl; read through r.jina.ai) | competitions: `discover`, `get_competition`, `standings` (**pagination**, status envelope) | working, page 2 advances, parity equal |
| [ECB Data Portal](https://data.ecb.europa.eu/help/api/data) | HTML docs, **XML (SDMX-ML) responses** | market_data: `get_series` | working, parity equal |

All six are kept in the catalog with a `live_check` block (`working`, 2026-09-27), contract tests in
both languages (`tests/test_<id>_python.py`, `tests/<id>.typescript.test.mjs`) and a plan in
`tools/live_verify.py` so repository-wide reruns exercise them.

### Frankfurter (OpenAPI 3.1 JSON URL)
- **Forge got wrong:** `ingest_openapi` listed `GET /rates` with `params: []` — every parameter is a
  `$ref` (`#/components/parameters/from` …) and was silently dropped; no response shape was
  reported, so where the records live (a top-level array) had to be guessed.
- **After the fix:** parameters come back resolved (`from(query, string, date)`,
  `group(query, string, enum=week|month)`, `base(… default=EUR)`), the 200 response is
  `{type: array, item_keys: [base, date, providers, quote, rate]}` with the documented example.
- **Authoring decisions:** the API has no free-text search, so `search_symbols` is an exact ISO-code
  lookup (`GET /currency/{code}`) and says so; `get_series` maps `series_id` → `quotes`, the base
  currency is a config field. No manual fixes after generation.

### Mercado Bitcoin (Swagger 2 YAML URL)
- **Forge got wrong:** `ingest_openapi` failed outright: "YAML spec: install PyYAML" (not a
  dependency). The per-endpoint rate limits ("1 requests/sec") and the global limit (500/min) and
  error format sit in descriptions the summary dropped.
- **Runtime gaps found:** `/symbols` and `/candles` answer **parallel arrays**
  (`{"t": [...], "o": [...], ...}`), which no result option could read; `/symbols` returns all 1,365
  instruments with no paging and in a **different order on every request** — the first live run had
  Python and TypeScript return different "page 1"s (parity failed).
- **Fixed:** PyYAML is a forge dependency; ingest reports `columnar: true` and `rate_limit`; new
  `result.columnar`, `result.slice` and `result.sort` in both runtimes. Live: working, stable pages.

### NHTSA vPIC (HTML-only docs)
- **Forge got wrong:** `ingest_openapi` on the docs page answered "YAML spec: install PyYAML" — it
  tried to parse HTML as YAML — instead of saying it is an HTML page.
- **Runtime gap:** an undecodable VIN is HTTP 200 with an empty record and the reason in
  `Results[0].ErrorText`; `envelope.fail_when` could not index arrays and `error_field` was
  top-level only, so the bad-id probe "returned a record".
- **live_verify gap:** `decode_vin` echoes `vin`, not `id`, and was flagged "returned a different
  item than requested".
- **Fixed:** HTML → `not_openapi` (+ spec links on the page); `fail_when`/`error_field` take dotted
  paths through arrays (`{"Results.0.Make": ""}`, `Results.0.ErrorText`); live_verify compares the
  verb's own key field.

### OpenFIGI (local spec file, cursor pagination)
- **Forge got wrong:** servers came back as `https://api.openfigi.com/{basePath}` (server variable
  not substituted); the `/search` body was reported only as `#/components/schemas/SearchRequest`,
  and once resolved it still lacked `query` and `start` (the schema's own properties sit next to an
  `allOf`, and only the `allOf` part was read).
- **The spec is wrong:** it types the `/v3/search` 200 response as an array; the live API answers
  `{data: [...], next: "<cursor>"}`. Mapped to the live shape; the discrepancy is in the entry's
  `terms_note`. The skill now says the live API is the final evidence and `try_tool` shows the
  real response.
- **Runtime issue:** the tool returned `next_cursor` **and** `next_page: 2`, but it pages only by
  cursor — `page=2` returns page 1 again. Cursor-only tools (19 in the catalog) no longer offer
  `next_page`.
- **Authoring:** 5 searches per minute without a key → `rate_per_second: 0.08`; the optional key is
  `auth: none` + `extra_headers {X-OPENFIGI-APIKEY: api_key}` with `required: false`.

### Codeforces (HTML-only docs, envelope, pagination)
- **Docs:** `https://codeforces.com/apiHelp` answered 403 to curl with a browser User-Agent (the
  forge's own fetch got 200); read through `https://r.jina.ai/…`. The **current** docs forbid `from`/`count` on anonymous
  `contest.standings` calls for regular contests ("exactly one query parameter: contestId") — a
  mapping from memory would have used them and failed (`status: FAILED`).
- **Runtime gaps:** the lists come whole (≈2,000 contests; standings of a large round are ≈14 MB) →
  `result.slice`; start times are epoch seconds and contest URLs are not in the records → `iso:` and
  `fmt:` result fields; "Call limit exceeded" in a 200 `FAILED` envelope was an `upstream_error`
  although CONTRIBUTING promised 'rate limit' wording maps to `rate_limited` — both 'rate limit'
  (with a space) and 'call limit' now do.
- **Live:** working; 1 call per 2 s as documented.

### ECB Data Portal (XML)
- **First live run returned 0 points, silently.** The runtime sends `Accept: application/json`, and
  the SDMX service content-negotiates: it answered SDMX-JSON (observations keyed by index), not the
  SDMX-ML the mapping targeted; its `format=genericdata` parameter does not override the header.
  `try_tool` (added for exactly this) shows the request headers and the raw structure.
- **Fixed in the entry:** `adapter.headers {"Accept": "application/vnd.sdmx.genericdata+xml;version=2.1"}`;
  the skill and CONTRIBUTING describe the pitfall. Live: working, XML parsed identically in both runtimes.

## Headless agent run (plugin on a cloud host)

Setup (a Linux cloud host, Claude Code 2.1.283): a throwaway `CLAUDE_CONFIG_DIR` under `/tmp` holding only the
credentials of one Claude account, the plugin loaded with `--plugin-dir`, the agent run with
`claude -p … --agent platform-mcp-forge:mcp-forge --allowedTools <explicit list>` (never
`--dangerously-skip-permissions`), `--output-format stream-json` to record every tool call. The throwaway directory
was deleted afterwards.

**Plugin loading.** The init event listed the plugin (`platform-mcp-forge@inline`, 0.2.0), the
`platform-mcp-forge:mcp-forge` skill and agent, and the MCP server
`plugin:platform-mcp-forge:platform-mcp-forge` started from `.mcp.json` (`pending` while uv installed
the forge's environment on first start, `connected` afterwards). The tools resolved as
`mcp__plugin_platform-mcp-forge_platform-mcp-forge__<tool>` and a headless call of `catalog_search`
returned the workspace. With the original `.mcp.json`, the same file also produced a failed
project-scoped server whenever Claude Code ran inside the checkout (defect 16); with the launcher both
scopes connect. When both are present (Claude Code run inside a checkout that is also the plugin), the
project-scoped server shadows the plugin's (same name) and the agent uses `mcp__platform-mcp-forge__*`,
which its tools list also names.

| run | target | setup | result |
|---|---|---|---|
| 1 | Bitstamp, https://www.bitstamp.net/api/ | plugin dir = workspace, plugin tools | **not finished (2 findings).** Lint-clean and generated; `get_ticker` degraded in both languages because the ticker response does not repeat the pair and no result option could fill the required `symbol` → runtime `arg:` added. Write/Edit on `tests/` and `tools/live_verify.py` were refused as "sensitive file": Claude Code protects a loaded plugin's own files → skill updated, later runs load the plugin from a separate copy. The agent reported both honestly and did not work around the refusal. 30 turns, 177 s. |
| 2 | Bitstamp (same URL) | plugin from a separate copy, Claude Code run in a fresh checkout | **complete.** `ingest_openapi` read the spec embedded in the Redoc page (94 operations); `list_markets` (`slice` + `sort`), `get_ticker` (`arg:symbol`), `get_candles` (`map:` interval → step seconds, `iso:` times); signed account/order verbs under `not_offered`; both contract tests written; `test_server` ok; `live_verify` working in both languages with parity, recorded with egress "datacenter"; plan added to `PLANS`; spec-vs-live differences written into `terms_note`. 34 turns, 200 s. The entry is kept (`catalog/trading/bitstamp.json`). |
| 3 | Luno, https://www.luno.com/en/developers/api | plugin tools only, Claude Code run outside the checkout, workspace given by `PLATFORM_MCP_WORKSPACE` (+ `--add-dir`) | **complete.** Plugin server `plugin:platform-mcp-forge:platform-mcp-forge` used for every forge call; spec read from the Redoc page (41 operations); `list_markets` (`slice` + `sort`: live order is unstable), `get_ticker`; `get_candles` under `not_offered` after the live API answered 401 without a key; both contract tests; `test_server` ok; `live_verify` working in both languages with parity and recorded (dev egress); plan added. 30 turns, 178 s. The entry is kept (`catalog/trading/luno.json`). |

All three runs used only the forge tools, Read/Write/Edit/Glob/Grep/Skill/WebFetch and a few
read-only Bash patterns (`ls`, `cat`, `grep`, `curl -s`, `node --test`); every other Bash command was
denied by the permission system, as intended. Both kept entries were re-verified live from a residential connection
as well (working, parity equal).

## Tests added

- `tests/test_forge_python.py` (23 tests): every forge tool's success path and its errors — bad
  input, invalid and unreadable entries, missing files, network and HTTP failures (respx), refused
  writes, stale packages, missing executables and timeouts — against an isolated copy of the
  workspace, plus workspace resolution, the lint's new checks, `live_verify --plan` validation and
  one session over stdio as a client.
- `tests/test_result_transforms_python.py` and `tests/result_transforms.typescript.test.mjs` (6 + 6):
  the runtime additions, same specs and expectations in both languages.
- Contract tests in both languages for the eight new entries (`test_<id>_python.py`,
  `<id>.typescript.test.mjs`; the Bitstamp and Luno ones were written by the agent).
- CI: pyyaml/pyjwt installed, the TypeScript runtime built before the Python tests, the forge wheel
  built and smoked over stdio next to reed and the directory server.

## Defects found and fixed

Each has a regression test (file in brackets).

**Forge server** (`tests/test_forge_python.py`)
1. `ingest_openapi` could not read YAML (PyYAML missing) — now a dependency.
2. `$ref` parameters were dropped; path-level and operation parameters were not merged.
3. Request bodies were a bare `$ref`; `allOf` next to own properties lost the own properties; Swagger 2 `in: body` / `formData` were ignored.
4. Server variables were not substituted; relative server URLs (`/api/v3`) were not resolved against the spec URL; Swagger 2 without `host` gave no server.
5. No response shapes, examples, rate limits, `info.description` or paging hints — the author could not see where records live.
6. HTML pages were parsed as YAML ("install PyYAML"); Redoc pages that embed the whole spec (Bitstamp) were not read.
7. A missing local file was treated as spec text; network failures were `invalid_input` and HTTP errors lost their status.
8. `save_entry` accepted category `schema` (it could overwrite `catalog/schema/vocab.json`) and `sources`, unknown categories, `adapter: null` (which crashed the lint), and ids/categories disagreeing with the arguments; switching served ↔ status-only left stale `adapter_status`/`reason`.
9. `lint_entry`, `generate_server`, `test_server` on a missing entry returned Python tracebacks as results; `_run` raised on a missing executable (node) and had no timeout handling.
10. `test_server` passed with no tests at all ("no python contract test yet") and never started the generated servers — it now requires the Python contract test and smokes both builds over stdio (`tools/smoke_entry.py`).
11. `catalog_search` reported the capped hit count as `total`, did not search docs/API hosts, and crashed on an unreadable entry; `catalog_get` did not say where an id does exist.
12. `template_entry` listed stale auth types/expressions and always showed `jobs/reed`; it now derives them from the lint, adds a skeleton and a live-verified example of the same category.
13. No way to see a real response through the runtime (`try_tool`, `tools/try_tool.py`) or to verify live (`live_verify`, `tools/live_verify.py --plan`).
14. The forge wrote into `PLATFORM_MCP_ROOT`, i.e. the plugin directory (a marketplace install's cache); the workspace is now `PLATFORM_MCP_WORKSPACE`, else the checkout Claude Code runs in, else the plugin directory, and every result names it.
15. As a plugin (no `.venv`), the gates ran in the forge's environment without pytest, respx, jsonschema or pyjwt; they are forge dependencies now (verified on dev: `test_server` and `live_verify` ran from the plugin's uv environment).
16. `.mcp.json` failed as a project-scoped server whenever Claude Code ran inside the checkout (`${CLAUDE_PLUGIN_ROOT}` unset); `${CLAUDE_PLUGIN_ROOT:-.}` breaks plugin loading. A `sh` launcher reads `$CLAUDE_PLUGIN_ROOT` from the environment and falls back to the working directory; verified `connected` in both scopes on dev. It names the missing dependency when uv is absent.
17. The agent's `tools` list named `mcp__platform-mcp-forge__*`, which do not exist for a plugin-provided server (`mcp__plugin_platform-mcp-forge_platform-mcp-forge__*`); both forms are listed now.

**Lint** (`tests/test_forge_python.py`)
18. Crashed on invalid JSON and `adapter: null`.
19. Did not check that expressions read real inputs (a typo silently sends nothing), that `@fields` are declared, that path placeholders resolve, that a list result uses the vocabulary's list key, that `arg:` names an input, `verified_at` format, or verbs both mapped and not offered. `--json` output for the forge.

**live_verify** (`tests/test_forge_python.py`)
20. Detail verbs keyed by another field (`decode_vin` → `vin`) were reported as returning a different item.
21. `--record` wrote only the Python status; a TypeScript failure or a parity difference now goes into the notes.

**Runtime, both languages** (`tests/test_result_transforms_python.py`, `tests/result_transforms.typescript.test.mjs`, the six contract tests)
22. `result.columnar` (parallel arrays), `result.slice` + `result.sort` (whole collections, unstable order), `fmt:`/`iso:`/`arg:` result fields.
23. `envelope.fail_when` / `error_field` through arrays.
24. 'rate limit' / 'call limit' messages in 200 envelopes → `rate_limited`.
25. Cursor-only tools advertised a `next_page` that returns page 1 again.

**Skill and agent prompts.** Rewritten from what the runs showed would mislead an agent: the
non-OpenAPI path (spec links, r.jina.ai for 403/JS pages, reading the current docs), the live API as
final evidence (OpenFIGI), content negotiation (ECB), the result options for each response shape,
not faking a `query` the API lacks, rate limits from the docs, `try_tool` before tests, plans in
`live_verify`, the workspace rule, the plugin tool names, and that loading the plugin from the
checkout being edited makes Claude Code refuse Write/Edit on it as "sensitive".

## Second pass: the limits fixed (2026-09-27)

The first pass ended with the limits listed at the end of this section. Each one was fixed in both
runtimes (or, where it could not be, the reason is given), with regression tests in both languages.

| limit (first pass) | fix | regression tests |
|---|---|---|
| **Error kinds.** 400/422 answers to bad input were `upstream_error`; only 404 mapped, to `invalid_input` | `classify` in `errors.py` / `errors.ts` (one table, both runtimes): 400/422 with validation wording → `invalid_input` (a 422 always), with 'not found' wording on a GET → `not_found`, with credential wording → `auth_error`, with rate-limit wording → `rate_limited`, otherwise `upstream_error`; 401/403 → `auth_error`; 404/410 on a GET → `not_found` (on a write `invalid_input`, as before); an empty record on a GET → `not_found`; 409 → `conflict`; 429 → `rate_limited`; 5xx → `upstream_error`. New kinds `not_found` and `conflict`. Per-entry overrides: `adapter.error_kinds [{status, match, kind}]` (first match wins; `status: 200` reclassifies envelope failures), checked by the lint. Messages keep the platform's text, scrubbed of every secret | `test_runtime_limits_python.py` / `runtime_limits.typescript.test.mjs`: the 17-row table, a tool call with a secret echoed in a 400 body, overrides for HTTP and envelope failures, empty record → `not_found`; Frankfurter 422, Codeforces 400 'not found' and 400 'extra parameters', Bitvavo 400 contract tests |
| **Local paging downloads everything** (Codeforces standings ≈14 MB per page) | *Server-side paging where the vendor has it:* Codeforces does not — re-checked live, `from`/`count` on an anonymous `contest.standings` call answers 400 "available only via anonymous GET requests with no extra parameters". *Otherwise a short-lived bounded cache:* tools with `result.slice`/`result.trim` reuse a successful response for 60 s (`PLATFORM_MCP_CACHE_TTL`; any read tool may set `cache_ttl`, e.g. Codeforces `get_competition`, which reads the same `contest.standings` answer as `standings`). It stores the response **text** (memory bounded by bytes held): 64 MB in total (`PLATFORM_MCP_CACHE_MAX_MB`), 16 entries (`PLATFORM_MCP_CACHE_MAX_ENTRIES`), LRU eviction, a body larger than the cap is never stored, failures are never stored, `…_MAX_MB=0` turns it off; keyed by method, path, query and body per server process. *Stream parsing:* not done — neither runtime has an incremental JSON parser without a new native dependency, `total`/`sort`/`filter` need every row anyway, and re-parsing cached text is cheap (below); when no `sort`/`require`/`filter` is set only the requested page's rows are mapped. *Filters:* `result.filter` applies `query`/`kind`/`status` locally on sliced feeds (Codeforces `discover`, Mercado Bitcoin `list_markets`), so the first pass's "filters are not applied to sliced feeds" is gone too. Tradeoff (CONTRIBUTING): a page may be up to one TTL stale | runtime tests: one download for three pages, TTL expiry, byte/entry caps and LRU eviction, oversized bodies skipped, failures and server-paged tools never cached, env switches, filters, page-only mapping; Codeforces, Mercado Bitcoin, Frankfurter and Bitvavo contract tests assert a single request for several pages |
| **Fixed page sizes** (OpenFIGI answers 100 per page whatever `limit` says) | `result.trim: true` (with `next_cursor`): the tool returns `limit` rows and its own cursor `pmc1.<base64url [upstream cursor, offset]>` (identical bytes in both runtimes) that walks the rest of the upstream page before handing back the platform's cursor; a foreign cursor is passed through, a malformed `pmc1.` one is `invalid_input`. With the cache, walking one upstream page costs one request (OpenFIGI allows 5 per minute without a key) | OpenFIGI contract tests (both languages): 40/40/20 windows over one 100-row page from one request, then the platform cursor; a window cursor inside a later page resends that page's cursor; a forged cursor |
| **Exact lookups** (Frankfurter `search_symbols` = exact code; ECB `get_series` without `start` = whole history) | Frankfurter now reads `GET /currencies` (in the spec) and filters code and name locally: `dollar` finds 23 currencies, paged. ECB: **left by design** — the vocabulary's `get_series` has no limit input, so an omitted `start` asks for the whole series (daily EUR/USD: 767 KB, ≈7,000 points, 1.6 s); a silent default window would return less than was asked. The tool note says so | Frankfurter contract tests (both languages) |
| **Plugin prerequisites** (uv, node, a built TypeScript runtime) | New forge tool `doctor`: workspace, Python gate dependencies, uv, node ≥ 20, npm, the runtime build (missing / no node_modules / stale when a `src/*.ts` is newer than `dist`), each failure with the exact install command for the OS; `fix: true` builds the runtime. `test_server` and `live_verify` build a missing or stale runtime themselves when it is safe (node and npm present, `package-lock.json` present — `npm ci` installs only locked versions, directory writable, `PLATFORM_MCP_FORGE_AUTOBUILD` not 0; one build at a time under a lock). Without node: `generate_server` generates the Python package only, `test_server` runs the Python tests and the Python smoke, `live_verify` runs Python (and refuses `lang: ts` with `prerequisite_missing`), each with `mode: python_only` and a warning that the entry is not publishable yet. The `.mcp.json` launcher names the uv install command. Skill, agent (`doctor` in its tool list and as step 0), forge README and the forge's instructions updated | `test_forge_python.py`: doctor with and without node and outside a checkout, `fix` building a missing runtime and rebuilding a stale one (stub `tsc`, no network), autobuild disabled, no unlocked install, Python-only generate/test/live_verify, the stdio tool list |

**Measured on the 14 MB case** (Codeforces round 2000, 17,530 standings rows, residential egress): `get_competition`
downloads it once (5.4 s Python, 1.1 s TypeScript on a warmer connection); the following
`standings` pages 1, 2 and 3 answer in 0.06 s (Python) / 0.03 s (TypeScript) each from the cache
instead of one 14 MB download each (≈10 s by curl). Peak RSS 199 MB (Python) / 262 MB (Node).

### End-to-end reruns (second pass)

Driven the same way as the first pass: the forge's own MCP server over stdio
(`uv run --quiet --project forge platform-mcp-forge`, working directory outside the checkout,
`PLATFORM_MCP_WORKSPACE` = the checkout), calling `doctor` → `catalog_search` → `ingest_openapi` →
`template_entry` → `catalog_get`/entry → `save_entry` → `lint_entry` → `generate_server` → `try_tool`
→ `test_server` → `live_verify(record: true)`. All recorded `working` with Python/TypeScript parity.

| API | new behaviour exercised | result |
|---|---|---|
| Frankfurter (first pass) | `search_symbols` over `/currencies` + `filter` + slice + cache (page 2 in 4 ms); unknown currency → 422 → `invalid_input` | working, parity equal, 13 forge calls |
| OpenFIGI (first pass) | `trim`: `limit` 5/10 honoured, `pmc1.` cursor, page 2 from the cached upstream page (6 ms, no second search) | working, parity equal |
| Codeforces (first pass) | `discover` status/query filters; `get_competition` + `standings` share one download; unknown contest → 400 → `not_found`; `from`/`count` re-checked live (still refused) | working, parity equal |
| **Bitvavo** (new, keyless; HTML docs, JS-rendered, read through r.jina.ai) | `ingest_openapi` → `not_openapi` (no spec links); `list_markets` = `/v2/markets` whole list with `slice` + `sort` + `filter` + cache; `get_ticker` (`num:` parses the live `"7.479E+4"`); `get_candles` positional rows; unknown market → 400 errorCode 205 → `invalid_input`; account/order verbs `not_offered` (HMAC-signed) | working, parity equal, entry kept (`catalog/trading/bitvavo.json`) |

Also re-verified live with `tools/live_verify.py` (residential egress): Mercado Bitcoin (its `list_markets` now
filters by `query`; plan changed to `brl` so page 2 is exercised; recorded), NHTSA vPIC, ECB,
Bitstamp and Luno — all `working` with parity. Without node (forge started with `PATH=/usr/bin:/bin`
and an empty HOME over stdio): `doctor` → `mode: python_only` with the install commands,
`generate_server` and `test_server` on Bitvavo → ok, Python only, with the warning; `live_verify
lang: ts` → `prerequisite_missing`.

**Tests added in the second pass:** `tests/test_runtime_limits_python.py` (26) and
`tests/runtime_limits.typescript.test.mjs` (10); 3 forge tests in `tests/test_forge_python.py`;
contract tests for Bitvavo (5 + 3) and new cases for Frankfurter, OpenFIGI, Codeforces and Mercado
Bitcoin (7 Python, 7 TypeScript). Totals: Python 1,819 → 1,859, TypeScript 996 → 1,015. 62 existing Python and 16 TypeScript contract tests changed
their expected kind (404 on a GET → `not_found`, 400/422 validation → `invalid_input`, 409 →
`conflict`, a 400 "bad API key" → `auth_error`); each change was reviewed against its mocked body.

## Remaining limits

- **ECB `get_series` without `start`** returns the whole series (by design, see above).
- **Error wording is heuristic.** 400 bodies are classified by wording; a vendor whose 400 means
  something else needs an `error_kinds` rule (the default for an unrecognised 400 stays
  `upstream_error`).
- **Cache staleness and scope.** A locally paged collection can be up to 60 s old; the cache is per
  server process and in memory only. Large JSON is parsed whole (no streaming).
- **Plugin first start** installs the forge's dependencies with uv (tens of seconds; Claude Code
  shows the server as pending meanwhile); uv itself must be installed (the launcher names the
  command). `npm ci` for the auto-build needs network access to the npm registry.
- **Live checks are point-in-time**, and only one egress is recorded per entry.
- **Spec-driven authoring is still model work:** the forge summarises and verifies; it does not
  choose mappings. An agent can still pick a wrong endpoint that happens to validate.

<details><summary>Limits as listed after the first pass</summary>

- Error kinds: 400/422 answers to bad input were `upstream_error`; only 404 mapped to `invalid_input`.
- Local paging downloaded everything on every call; `query`/`status` filters were not applied to sliced feeds.
- Fixed page sizes: OpenFIGI always returned 100 results per page whatever `limit` said.
- Exact lookups: Frankfurter's `search_symbols`; ECB's `get_series` without `start`.
- Plugin prerequisites: `uv` and `node` on PATH, and the TypeScript runtime built by hand.
- Live checks are point-in-time; spec-driven authoring is model work.

</details>

## Gates

GitHub Actions was not available for the repository at the time, so every step of `.github/workflows/ci.yml`
was run by hand on a fresh clone from GitHub on a Linux cloud host (Python 3.12.3, Node 22, a new venv, a
throwaway `/tmp/forgetest-ci-*` directory, deleted afterwards).

| step | first run (7ff81d11) | after the fix (4f1e50b6) |
|---|---|---|
| Python deps (now incl. pyyaml, pyjwt) | pass | pass |
| Catalog lint | pass — 3,476 entries, 427 served, 0 errors | pass — same |
| Regenerate servers + directory snapshot (`gen_all`, `build_directory`) | pass | pass |
| Generated packages committed (`git diff --exit-code -- servers catalog`) | pass | pass |
| Build TypeScript runtime | pass | pass (now before the Python tests) |
| Python tests | **1 failed**, 1,818 passed | pass — 1,819 passed |
| Build TypeScript directory server | pass | pass |
| TypeScript tests | pass — 996 | pass — 996 |
| Installed-package smoke over stdio (runtime, reed, directory **and forge** wheels) | pass | pass |

**Second pass (f3dda617).** Same procedure on dev (fresh clone from GitHub, Python 3.12.3, Node
22.23.2, new venv, throwaway directory deleted afterwards): Python deps pass; catalog lint pass —
3,477 entries, 428 served, 0 errors; `gen_all` + directory snapshot pass; generated packages
committed pass (no diff); TypeScript runtime build pass; Python tests pass — 1,859 passed; directory
server build pass; TypeScript tests pass; installed-package smoke over stdio pass (the forge wheel
lists `doctor`); `build_directory` pass. The same clone re-ran `tools/live_verify.py` on Frankfurter,
OpenFIGI, Codeforces, Bitvavo and Mercado Bitcoin from the datacenter egress: all `working`, pagination
advancing, parity equal. On a workstation: lint 0 errors, pytest 1,859 passed, node 1,015 passed,
`gen_all` clean.

The one failure of the first pass was real: CI ran the Python tests before building `runtime/typescript/dist`, and the
forge's `test_server` smokes the TypeScript build too. CI now builds the runtime first and the test
asserts the explicit "build runtime/typescript first" answer when it is absent. The same fresh clone
also re-ran `tools/live_verify.py` on the eight new entries from the datacenter egress: all
`working` with Python/TypeScript parity. On a workstation: lint 0 errors, pytest 1,819 passed, node 996
passed, `gen_all` clean.

## Stress test 2026-10

On 2026-10-01 the forge was run against 32 real public APIs that were not in the catalog, chosen to
be awkward: every machine-readable format we could find in the wild (OpenAPI 3.0/3.1 JSON and YAML,
Swagger 2, a 13 MB and a 44 MB spec, a multi-file spec, Postman, API Blueprint on Apiary, RAML,
WSDL/SOAP, GraphQL, RSS 2.0, Atom), HTML-only docs, CSV and pipe-separated text, cursor, offset, page,
keyset and Link-header paging, documented rate limits, documentation in Korean, Japanese, German,
Czech, Polish, Portuguese, Russian and Ukrainian, and APIs whose docs disagree with what they do.

**Method.** As in the earlier passes: the forge's own MCP server over stdio (`uv run --project forge
platform-mcp-forge`, started from a directory outside the checkout with `PLATFORM_MCP_WORKSPACE` set),
calling `doctor` → `catalog_search` → `template_entry` → `ingest_openapi` → `save_entry` → `lint_entry`
→ `generate_server` → `try_tool` → `test_server` → `live_verify` (both languages, then `record: true`
via `tools/live_verify.py` for the batch). The forge and runtimes were used as found; each defect was
fixed when it blocked an API (both runtimes, with a regression test) and the API was rerun. All live
checks: residential egress.

### Result

- **Served: 28 of 28 APIs reached `working` in both languages with Python/TypeScript parity** after the
  fixes (100 %). 27 are kept in the catalog with a `live_check` block and a `live_verify` plan;
  `countries_graphql` was removed afterwards (a community demo service; GraphQL support stays covered
  by tests). Four more were ingest-only (no fitting category or no keyless endpoints): all summarised,
  except Microsoft Graph, which is refused cleanly as `too_large` by design.
- **First pass, estimated:** with the forge and runtimes as found, 19 of 28 could have been served
  working with parity at all (68 %); 9 were blocked by runtime gaps or parity defects (Kraken, Gemini,
  dYdX, Bank of Canada, CNB, SNB, CTFtime, CoinPaprika, Prozorro), and 6 needed the docs read by hand
  because `ingest_openapi` could not read the format (MEXC, Coinmate, CBR, the Fed feed, arXiv,
  GraphQL).
- **Defects fixed: 41** (21 forge, 4 lint, 15 runtime, 1 live_verify), listed below; 6 existing
  contract tests had pinned wrong answers and were corrected.

### Per API

| # | API | input style | what the forge or runtime got wrong | entry needed | status | parity |
|---|---|---|---|---|---|---|
| 1 | Kraken (spot) | HTML docs → spec link → OpenAPI 3.0 YAML | schema-level `example` not shown; nested `result` map keyed by pair not shown; `try_tool` report cut at 6,000 chars (`try_tool_failed`); `try_tool` ignored `error_kinds`; no path for "the only key" (`XXBTZUSD` for `XBTUSD`), no failing on a non-empty `error` list, OHLC ignores the page size | `result.*`, `fail_if_present`, `cap: tail` (new) | working | equal |
| 2 | Gemini | HTML docs (only an AsyncAPI document for WebSocket) | a list of strings dropped (no scalar rows); the lint accepted integer `result.fields` sources and the runtime crashed with a traceback; 400 "is not a valid symbol" → `upstream_error` | `scalar_rows`, `volume.*`, `cap: head` | working | equal |
| 3 | KuCoin | HTML docs | `fail_when` with `null` matched absent paths in Python only (every list call failed in Python, none in TypeScript); messages `None`/`True` vs `null`/`true`. Unknown symbol = `200000` with every field null (silent) | `fail_when {data.last: null}` + `error_kinds` | working | equal |
| 4 | Upbit | HTML docs (Korean/English) | — (no null literal for `result.fields`: a field the API lacks is omitted) | `map:` in `path_params` | working | equal |
| 5 | bitFlyer | HTML docs (Japanese) | — | — | working | equal |
| 6 | Coinbase Exchange | HTML docs | the only "spec link" on the page belongs to another product | `cap: head`, `arg:symbol` | working | equal |
| 7 | Kalshi | OpenAPI 3.0 YAML (82 ops) | nested record keys (`market.*`) not shown; YAML `null` defaults printed as Python `None`. Spec vs live: `status` enum lacks the `active` the API returns | fixed filters; `query` not mapped (no search); candles not offered (needs a window) | working | equal |
| 8 | dYdX v4 indexer | HTML docs (`/v4/swagger.json` 404) | needed `markets.*` (a map keyed by ticker) | — | working | equal |
| 9 | MEXC | Postman collection v2.1 + environment | Postman rejected as `not_openapi`; plain-string request URLs lost their query; header `{{variables}}` not reported. Collection hides that the hour interval is `60m` (`1h` → 400) | `map:` 1h=60m | working | equal |
| 10 | Coinmate | API Blueprint on Apiary (a JS page) | Apiary page → `not_openapi` with no links | `{error: true}` envelope | working | equal |
| 11 | CoinPaprika | HTML docs | documented `/v1/search` answers 301: Python (httpx, no redirects) returned an **empty success**, TypeScript (fetch) followed it; non-JSON 200 bodies were empty successes | — | working | equal |
| 12 | US Treasury Fiscal Data | HTML docs | one combined `filter` parameter could not carry optional conditions (`fmt:` dropped the whole value). Found here: **path arguments were not encoded** (`BTC-USD/../../accounts` reached another endpoint; `?`/`#` injected queries) | `fmt` `[?...]` groups (new) | working | equal |
| 13 | World Bank Indicators | HTML docs | no way to split a two-part series id; 200 error arrays need an indexed `fail_if_present`; the API ignores `Accept` (XML unless `format=json`) | `part:` (new) | working | equal |
| 14 | Bank of Canada Valet | OpenAPI 3 YAML in English and French behind Swagger UI | link finder offered `favicon.ico`, missed the JS-built spec URL; values keyed by the requested series needed `{arg}` in a path | `{series_id}.v` (new) | working | equal |
| 15 | CNB (Czech National Bank) | HTML docs (Czech), pipe-separated `text/plain` | CSV only for `text/csv`; no `DD.MM.YYYY` or decimal commas; an undocumented Python-only `_force_csv`; TypeScript CSV gave `""` for missing cells where Python gives `None`. Live: `rok=1900` silently answers the current year | `csv`, `isodate:`, `num_comma:` (new) | working | equal |
| 16 | Banco Central do Brasil SGS | HTML docs (Portuguese) | an unknown code is a 200 HTML page that `error_kinds` could not reclassify; 406 for a missing window. Docs omit the 10-year window rule | `datefmt:`/`isodate:` dd/mm/aaaa | working | equal |
| 17 | Bank of Russia DailyInfo | **SOAP/WSDL** (Russian, 282 ops) | WSDL rejected as "plain text"; the lint refused `path: ""`; windows-1251 XML failed to parse in Python and was mojibake in TypeScript. WSDL says `FromDate` minOccurs=1, but omitting it answers an empty DataSet | SOAP envelope via XML body keys + `SOAPAction` | working | equal |
| 18 | Swiss National Bank | HTML help; CSV with BOM, preamble, `;`, long format | no CSV options; `result.filter` refused on a verb that does not page | `csv.skip_lines`, filters with `part:` | working | equal |
| 19 | Narodowy Bank Polski | HTML docs (Polish) | Python error messages kept the BOM, TypeScript's did not; a computed placeholder failed as "missing argument 'window'". Docs say 93 days, the API enforces 367 | window in `path_params` | working | equal |
| 20 | Federal Reserve press releases | **RSS 2.0** (UTF-8 BOM) | feed rejected as "neither valid JSON nor valid YAML" (`invalid_input`); BOM defeated sniffing; RFC 822 dates; no `since` | `isodate` `%a`/`%b`, filter `gte` (new) | working | equal |
| 21 | arXiv q-fin | **Atom 1.0** + OpenSearch | totals were XML strings (ignored → `next_page` past the end); errors are a 200 feed with one "Error" entry | `fail_when` + `error_kinds` | working | equal |
| 22 | GitHub (public) | **OpenAPI 3.0 JSON, 13 MB, 1,231 ops** (+ RAML 0.8) | unfiltered answer 217 KB (≈55k tokens); record keys cut alphabetically at 40 (hid `html_url`, `name`); 403 "API rate limit exceeded" → `auth_error` | collection mapped into the path | working | equal |
| 23 | GitLab.com | OpenAPI 2.0 YAML, 2.4 MB, partial | response headers never reached the adapter: keyset paging (next page only in `Link`) impossible; 12.5 s pure-Python YAML. Spec omits `pagination=keyset` | `next_cursor: "link:id_after"` (new) | working | equal |
| 24 | Countries (trevorblades) | **GraphQL** (introspection) | endpoint reported as "plain text"; a null record on a POST read was `invalid_input` (reads judged by HTTP method) | POST `path ""`, `variables.*`, `fail_if_present` | working (removed later) | equal |
| 25 | CTFtime | HTML docs | results keyed by event id needed `{arg}` in `items`; 300 chars of HTML in error messages; site blocks curl's default UA | `{competition_id}.scores` (new) | working | equal |
| 26 | Jolpica F1 (Ergast) | Markdown docs on GitHub | (string totals, HTML 404 — fixed above) | ids `season/round` | working | equal |
| 27 | OpenLigaDB | OpenAPI 3.0.4 JSON (German) | no servers reported (spec default `/`); `text/plain` chosen over `application/json` | — | working | equal |
| 28 | Prozorro | HTML docs (Ukrainian/English) | parity could not tell a moving feed from a runtime difference. Live: `opt_fields=title,value` silently dropped; pages return limit+1 rows | opaque `offset` cursor, `cap: head` | working | equal (`volatile`) |
| 29 | Open Food Facts | multi-file OpenAPI 3.1 (83 files) | external `$ref`s unresolved: 3 of 11 parameters shown, shapes "not resolved" | — | ingest only | — |
| 30 | Stripe | OpenAPI 3.0 JSON, 8.3 MB | unfiltered answer ≈200 detailed operations | — | ingest only (0.7 s) | — |
| 31 | Microsoft Graph v1.0 | OpenAPI YAML, 44 MB | downloaded all 44 MB, then `invalid_input`; gzip `Content-Length` mistaken for the size | — | refused: `too_large` | — |
| 32 | GitHub (raml-apis) | RAML 0.8 | rejected as not OpenAPI | — | ingest only | — |

### Defects fixed

**Forge** (`tests/test_forge_stress_python.py`): 1 `try_tool` reports cut at 6,000 characters (any
large answer → `try_tool_failed`); 2 `try_tool` ignored `error_kinds`; 3 schema-level `example`s not
shown; 4 nested records, maps keyed by id and `additionalProperties` beside properties not shown;
5 YAML `null` defaults/enums printed as `None`; 6 favicons, scripts and images offered as spec links;
7 Postman collections and environments not read; 8 plain-string Postman URLs lost their query and
header variables were not reported; 9 API Blueprint (text and Apiary pages) not read; 10 RAML not
read; 11 WSDL rejected as plain text; 12 GraphQL endpoints rejected (introspection now); 13 RSS/Atom/XML
rejected as `invalid_input`, and a BOM defeated sniffing; 14 AsyncAPI unexplained; 15 external `$ref`
files never fetched (parameters silently dropped); 16 a large unfiltered spec answered 217 KB (now a
one-line index with tag counts); 17 record keys cut alphabetically at 40; 18 oversized specs downloaded
whole then `invalid_input` (now streamed, `too_large`; gzip length not taken as size); 19 pure-Python
YAML (12.5 s → 2.6 s with libyaml); 20 OpenAPI 3 without `servers` gave none; 21 `text/plain` chosen
over JSON media.

**Lint** (`tests/test_forge_stress_python.py`): 22 unknown tool/result/envelope keys accepted
silently; 23 non-string `result.fields` sources accepted (runtime traceback); 24 `path: ""` refused;
25 filters refused on verbs that do not page.

**Runtime, both languages** (`tests/fixtures/forge_stress_cases.json`, run by
`tests/test_forge_stress_runtime_python.py` and `tests/forge_stress_runtime.typescript.test.mjs`,
plus the contract tests): 26 **path arguments not encoded** (`../` reached other endpoints with the
user's credentials, `?`/`#` injected queries) — found here independently of the security review, which
fixed it the same way in parallel (SR-03); its implementation is the one kept after the rebase;
27 redirects: Python returned an empty success where TypeScript followed (parity); the security review
then stopped TypeScript following any redirect (SR-04), which left both runtimes answering a 3xx as an
empty success — redirects are now followed within the same origin only, in both, and a cross-origin or
unfollowable 3xx is an error; 28 HTML and other
non-JSON 200 bodies were empty successes (HTML even parsed as XML); 29 `offset`/`next_page` used the
uncapped limit (rows skipped); 30 digit-string totals ignored (every XML API advertised a next page past
the end — Falabella's test pinned this); 31 `fail_when null` parity and message rendering; 32 charsets:
windows-1251 XML broken in Python, mojibake in TypeScript; 33 Python error messages used the undecoded
body; 34 CSV missing cells `""` vs `None`, a Python-only `_force_csv`; 35 403 with rate-limit wording
was `auth_error` (Contracts Finder's tests pinned this); 36 reads judged by HTTP method: empty records
and 404s on POST reads were `invalid_input` (EU Funding's test pinned this); 37 response headers never
reached the adapter; 38 "not a valid" not validation wording; 39 HTML error pages copied as markup into
messages; 40 throttle notices served as 200 pages (now `rate_limited`, the news-collector test pinned the
silent empty answer).

**live_verify**: 41 parity failed on feeds that change between the two runs (plan key `volatile`).

New adapter options that unblocked APIs (CONTRIBUTING "Additions 2026-10-01"): `*` and `{arg}` in
result paths, `fail_if_present`, `cap`, `scalar_rows`, `link:`/`header:` cursors and totals, `fmt`
`[?...]` groups, `part:`, `isodate:`, `num_comma:`, tool `csv`, filter `gte`/`lte`.

**Rebase onto the security review (2026-10-01, SR-01 … SR-20).** This work was rebased onto main after
the security review landed. Every network path the stress test added to the forge — Apiary blueprints,
GraphQL introspection, external `$ref` files — goes through the review's guarded fetcher (public addresses
only, pinned connections, re-checked redirects, size cap); local `$ref` files obey the review's
local-file rules, whose allowed suffixes now include `.raml`, `.apib`, `.wsdl` and `.xml`; an oversized
spec is reported as `too_large` instead of `invalid_input` (the review's test was updated).

### Gaps left (documented, not implemented)

- **Swagger UI pages that build the spec URL in JavaScript** (Bank of Canada) are not followed; the
  skill tells the agent to read `swagger-initializer.js`.
- **RAML `!include`, resource types and traits; API Blueprint MSON attributes; WSDL `xsd:import`; GraphQL
  SDL text** (only introspection) are not expanded.
- **AsyncAPI / WebSocket** feeds cannot be served (HTTP request/response runtimes).
- **Unmappable vocabulary inputs are accepted and ignored** (Kalshi and Prozorro cannot search, so
  `query` does nothing); the tool note says so, but `live_verify` cannot detect it.
- **No computed time windows** (a candle request that needs `start = now − limit × interval`), no
  request defaults (`a|b` fallbacks), no `null` literal and no row-number field (OpenLigaDB tables have
  no rank) in `result.fields`.
- **Live checks are point-in-time from one residential egress**; GitHub's unauthenticated limits (10
  searches per minute, 60 calls per hour) make repeated reruns from one IP fail as `rate_limited`.

## Generic mode (2026-10-01)

**Why.** In the stress test above, four of 32 APIs stopped at "ingest only": no category vocabulary fitted them (Open
Food Facts, Stripe, Microsoft Graph) or they duplicated a served platform (GitHub's RAML description). Generic mode
removes the category requirement: the tools are the API's own operations (`"category": "generic"`: name, the
documented description, an input JSON Schema from the parameters and body, the HTTP mapping, the docs link), and the
answer is passed through as `{data}` with optional `result.root`, `result.select`, `max_items` and a per-call
`select_fields`. The runtime support is in platform-mcp-hub (both languages, the same shared test fixtures); the lint,
the run config, the contract-test template, the stdio smoke and live verification work unchanged. It is the default
for your own workspace; the category vocabularies stay for contributing to a shared catalog.

**Method.** api-to-mcp's CLI (`api-to-mcp draft|save|lint|generate|try|test|verify`), your own workspace (no
checkout), the TypeScript half through `PLATFORM_MCP_HUB_TS_CLI`. `draft_entry` wrote the tools from the OpenAPI
descriptions; the review a model would do was done by hand (operations chosen, names shortened, unused parameters
dropped, `result.root` for list answers, the documented rate limit); other formats were written by hand from
`ingest_openapi` or `read_docs`. Live checks: residential egress. The entries are in `examples/generic/` (lint and
smoke tested in CI).

| API | documentation | how the entry was made | tools | test_server (lint, contract test, smoke py+ts) | live_verify | parity |
|---|---|---|---|---|---|---|
| Open Food Facts | multi-file OpenAPI 3.1 (83 files) | `draft_entry` (4 operations), staging server swapped for production, User-Agent contact as config | 4 | ok | 3 tools `working` in both; `search_products` answered intermittent 503 "Page temporarily unavailable" from Open Food Facts (Python and TypeScript each passed and failed on different runs; `try_tool` passes) | equal on every call that both got an answer to |
| Stripe | OpenAPI 3.0 JSON, 8.3 MB, 612 operations | `draft_entry` (5 operations), bearer secret key | 5 (1 write, never called) | ok | `needs_credentials`: clean `auth_error` naming `PLATFORM_MCP_STRIPE_SECRET_KEY`; with a dummy key every read reached its documented path and answered 401 → `auth_error` in both runtimes | equal |
| Microsoft Graph | OpenAPI YAML, 44 MB (refused: `too_large`) | written by hand from the HTML reference (`read_docs`): `/me`, `/users`, `/users/{id}`, `/me/messages`, OData `$top`/`$select`/`$filter` | 4 | ok | `needs_credentials`, clean; with a dummy token every read answered 401 `InvalidAuthenticationToken` → `auth_error` in both runtimes | equal |
| GitHub | RAML 0.8 (`raml-apis/GitHub`) | `ingest_openapi` read the RAML; tools written by hand; optional token as an extra header | 4 | ok | `working` in both | equal |
| Open-Meteo | OpenAPI 3.1 (per-operation servers, `explode: false` arrays) | `draft_entry` (per-operation server found; comma-separated list parameters drafted as strings) | 1 | ok | `working` in both | equal |
| PokéAPI | OpenAPI 3.1, 102 operations | `draft_entry` (4 operations chosen), a local-only parameter dropped | 4 | ok | `working` in both | equal |
| Open Library | HTML docs | written by hand (search, works, authors) | 3 | ok | `working` in both | equal |

Stripe and Microsoft Graph were not exercised with real accounts: no credentials were used. The two credential-free
runs prove the server starts, lists its tools, refuses cleanly without credentials and sends each documented request
(the 401s came from the vendors' own authentication on the documented paths).

**Defects found and fixed while doing this** (each with a test in `tests/test_generic_python.py` or platform-mcp's
`tests/test_generic_python.py` / `generic.typescript.test.mjs`):

1. Operation- and path-level `servers` were ignored (Open-Meteo declares its host per path): the draft used the spec's
   download host. Now the operation's own servers are used, and a spec fetched from a code host never becomes the base URL.
2. `explode: false` / `csv` array parameters would be sent as repeated keys (both runtimes repeat list parameters): the
   draft now takes a comma-separated string and lists the allowed values in the description.
3. The contract-test template filled required arguments from the category vocabulary, so generic templates called
   tools with no arguments; it now uses the tool's own input schema.
4. The TypeScript runtime omitted `platform_mcp/verified_at` (and the docs link) from a tool's `_meta` when the entry
   had none, where Python sent `null`: both send `null` now (the CLI parity test compares every tool's `_meta`).
5. On Python 3.10 the session-cookie replay followed the cookie jar's order instead of the `Set-Cookie` order
   (TypeScript's): both use header order now.
