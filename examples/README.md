# Example generic entries

Seven entries built with api-to-mcp in generic mode during the October 2026 verification (`docs/VERIFICATION.md`,
"Generic mode"): four drafted from OpenAPI with `draft_entry` (Open-Meteo, PokéAPI, Open Food Facts, Stripe) and three written by hand from other documentation (GitHub from its RAML 0.8 description, Microsoft
Graph from its HTML reference, the OpenAPI being too large to read, and Open Library from its HTML docs).

Run one:

```bash
platform-mcp-hub serve --entry examples/generic/open_library.json
# or copy it into your workspace: api-to-mcp save generic open_library examples/generic/open_library.json
```

Stripe and Microsoft Graph need your credentials (`platform-mcp-hub describe --entry <file>` lists the variables).
