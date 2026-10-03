"""api-to-mcp command line: the same tools the MCP server offers, for a terminal or a script. Every command prints the
tool's JSON result and exits 1 when the result is an error.

    api-to-mcp mcp [--http [--port N]]                  run the MCP server (stdio by default; the Claude Code plugin uses this)
    api-to-mcp doctor [--fix]                            prerequisites, workspace, install commands
    api-to-mcp workspace                                 where entries are saved
    api-to-mcp search <text> [--category C]              existing entries (yours and platform-mcp-hub's)
    api-to-mcp get <category> <id>                       one entry's JSON
    api-to-mcp template [generic | <category>]           skeleton, example and adapter contract (default generic)
    api-to-mcp ingest <url | file | -> [--filter F]       summarise an OpenAPI/Swagger/Postman/RAML/WSDL/GraphQL/... description
    api-to-mcp read-docs <url> [--offset N] [--reader]   readable text of a documentation page
    api-to-mcp draft <spec url|file> <id> [--operations a,b] [--filter F] [--limit N] [--docs-url URL]
                                                         draft a generic entry from an OpenAPI/Swagger description
    api-to-mcp save <category> <id> <entry.json | ->     save an entry into the workspace
    api-to-mcp lint <category> <id>
    api-to-mcp generate <category> <id>                  run config (or a checkout's registry metadata) + contract test template
    api-to-mcp try <category> <id> <verb> ['<json args>']
    api-to-mcp test <category> <id>                      lint + contract tests + stdio smoke of both runtimes
    api-to-mcp verify <category> <id> [--lang py|ts|both] [--plan '<json>'] [--record]
    api-to-mcp serve <category> <id> [--http ...]        start the entry (platform-mcp-hub serve --entry <file>)
    api-to-mcp call <tool> '<json arguments>'            any tool by name

Global options (before the command): --home DIR (your workspace; API_TO_MCP_HOME) or --checkout DIR (a platform-mcp
checkout, to contribute an entry upstream; API_TO_MCP_CHECKOUT).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from . import __version__


def _pop_flag(argv: list[str], flag: str) -> bool:
    if flag in argv:
        argv.remove(flag)
        return True
    return False


def _pop_value(argv: list[str], flag: str) -> str | None:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 >= len(argv):
            raise SystemExit(f"api-to-mcp: {flag} needs a value")
        v = argv[i + 1]
        del argv[i:i + 2]
        return v
    return None


def _json_arg(text: str) -> object:
    if text == "-":
        text = sys.stdin.read()
    elif os.path.isfile(text):
        with open(text, encoding="utf-8") as f:
            text = f.read()
    try:
        return json.loads(text)
    except ValueError as exc:
        raise SystemExit(f"api-to-mcp: not JSON: {exc}")


def _call(tool: str, args: dict) -> int:
    from . import server
    res = asyncio.run(server.server.call_tool(tool, args))
    payload = res.structured_content if res.structured_content is not None else {"text": res.content[0].text if res.content else ""}
    print(json.dumps(payload, indent=1, ensure_ascii=False, default=str))
    return 1 if res.is_error else 0


def _need(argv: list[str], n: int, usage: str) -> list[str]:
    if len(argv) < n:
        raise SystemExit(f"usage: api-to-mcp {usage}")
    return argv


def main(argv: list[str] | None = None) -> int:
    import logging
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request on stderr is noise in a terminal
    argv = list(sys.argv[1:] if argv is None else argv)
    home, checkout = _pop_value(argv, "--home"), _pop_value(argv, "--checkout")
    if home:
        os.environ["API_TO_MCP_HOME"] = home
    if checkout:
        os.environ["API_TO_MCP_CHECKOUT"] = checkout
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0 if argv else 2
    if argv[0] in ("-V", "--version", "version"):
        print(f"api-to-mcp {__version__}")
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "mcp":
        from . import server
        server.main(rest)
        return 0
    if cmd == "doctor":
        return _call("doctor", {"fix": _pop_flag(rest, "--fix")})
    if cmd == "workspace":
        return _call("workspace", {})
    if cmd == "search":
        category = _pop_value(rest, "--category")
        _need(rest, 1, "search <text> [--category C]")
        return _call("catalog_search", {"query": " ".join(rest), **({"category": category} if category else {})})
    if cmd == "get":
        c, i = _need(rest, 2, "get <category> <id>")[:2]
        return _call("catalog_get", {"category": c, "id": i})
    if cmd == "template":
        return _call("template_entry", {"category": rest[0] if rest else "generic"})
    if cmd == "draft":
        ops = _pop_value(rest, "--operations")
        flt = _pop_value(rest, "--filter")
        lim = _pop_value(rest, "--limit")
        docs = _pop_value(rest, "--docs-url")
        src, pid = _need(rest, 2, "draft <spec url | file> <id> [--operations a,b] [--filter F] [--limit N] [--docs-url URL]")[:2]
        return _call("draft_entry", {"source": src, "id": pid, **({"operations": [o.strip() for o in ops.split(",") if o.strip()]} if ops else {}),
                                     **({"filter": flt} if flt else {}), **({"limit": int(lim)} if lim else {}), **({"docs_url": docs} if docs else {})})
    if cmd == "ingest":
        flt = _pop_value(rest, "--filter")
        src = _need(rest, 1, "ingest <url | file | -> [--filter F]")[0]
        return _call("ingest_openapi", {"source": sys.stdin.read() if src == "-" else src, **({"filter": flt} if flt else {})})
    if cmd == "read-docs":
        offset = _pop_value(rest, "--offset")
        reader = _pop_flag(rest, "--reader")
        url = _need(rest, 1, "read-docs <url> [--offset N] [--reader]")[0]
        return _call("read_docs", {"url": url, "reader": reader, **({"offset": int(offset)} if offset else {})})
    if cmd == "save":
        c, i, src = _need(rest, 3, "save <category> <id> <entry.json | ->")[:3]
        entry = _json_arg(src)
        if isinstance(entry, dict) and isinstance(entry.get("entry"), dict) and "drafted" in entry:
            entry = entry["entry"]  # the output of `api-to-mcp draft`, saved as it is
        return _call("save_entry", {"category": c, "id": i, "entry": entry})
    if cmd in ("lint", "generate", "test"):
        c, i = _need(rest, 2, f"{cmd} <category> <id>")[:2]
        return _call({"lint": "lint_entry", "generate": "generate_server", "test": "test_server"}[cmd], {"category": c, "id": i})
    if cmd == "try":
        c, i, verb = _need(rest, 3, "try <category> <id> <verb> ['<json args>']")[:3]
        return _call("try_tool", {"category": c, "id": i, "verb": verb, "arguments": _json_arg(rest[3]) if len(rest) > 3 else {}})
    if cmd == "verify":
        lang = _pop_value(rest, "--lang") or "both"
        plan = _pop_value(rest, "--plan")
        record = _pop_flag(rest, "--record")
        c, i = _need(rest, 2, "verify <category> <id> [--lang py|ts|both] [--plan JSON] [--record]")[:2]
        return _call("live_verify", {"category": c, "id": i, "lang": lang, "record": record, **({"plan": _json_arg(plan)} if plan else {})})
    if cmd == "serve":
        c, i = _need(rest, 2, "serve <category> <id> [--http ...]")[:2]
        from . import server
        path = server.WS.catalog / c / f"{i}.json"
        if not path.is_file():
            raise SystemExit(f"api-to-mcp: no entry {path}")
        os.execvpe(server.WS.python(), [server.WS.python(), "-m", "platform_mcp_hub", "serve", "--entry", str(path), *rest[2:]], server.WS.gate_env(dict(os.environ)))
    if cmd == "call":
        tool = _need(rest, 1, "call <tool> '<json arguments>'")[0]
        args = _json_arg(rest[1]) if len(rest) > 1 else {}
        if not isinstance(args, dict):
            raise SystemExit("api-to-mcp: the arguments must be a JSON object")
        return _call(tool, args)
    print(f"api-to-mcp: unknown command {cmd!r}; run `api-to-mcp --help`", file=sys.stderr)
    return 2


def entry() -> None:
    sys.exit(main())
