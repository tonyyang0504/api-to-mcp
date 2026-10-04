"""api-to-mcp: turn API documentation (a docs URL, an OpenAPI/Swagger file, an HTML page, pasted text) into an MCP
server. The judgement (reading a platform's docs and writing an evidence-only entry) belongs to the model driving the
skill; the deterministic parts (templates, lint, run config, tests, live checks) are tools here, so any MCP client can
run them. Entries run with platform-mcp-hub (`platform-mcp-hub serve --entry <file>`)."""

__version__ = "0.1.1"
