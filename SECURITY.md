# Security policy

## Reporting a vulnerability

Please report security issues **privately** through GitHub Security Advisories: open this repository's **Security**
tab and choose **Report a vulnerability** (https://github.com/tonyyang0504/api-to-mcp/security/advisories/new).
Do not open a public issue, pull request or discussion for a vulnerability.

Include what you found, how to reproduce it (a document, a spec, a tool call), the impact you expect and the version or
commit. You will get an acknowledgement within 7 days and a fix or a plan within 30 days for confirmed issues; we
coordinate disclosure with you and credit you in the advisory unless you prefer otherwise.

## Supported versions

| version | supported |
|---|---|
| 0.1.x (main) | yes |
| anything older | no |

## Threat model

api-to-mcp reads documentation written by third parties and acts on a model's instructions, so documents are
untrusted input:

- **Network.** `ingest_openapi` and `read_docs` fetch only public hosts: every redirect is re-checked, the connection
  is pinned to the vetted address (no DNS rebinding), downloads stop at 25 MB, and private, loopback, link-local and
  metadata addresses are refused (`blocked_url`). `PLATFORM_MCP_ALLOW_PRIVATE_URLS=1` lifts this for the user, never on
  a document's say-so.
- **Files.** A local spec is read only from a `.json/.yaml/.yml/.raml/.apib/.wsdl/.xml` file outside hidden
  directories (never `~/.aws`, `~/.ssh`, `.env`), and parse errors never quote the file.
- **Live calls.** `try_tool` and `live_verify` refuse an entry whose hosts resolve to non-public addresses and never call
  write tools. Credentials come only from `PLATFORM_MCP_<ID>_*` environment variables you set.
- **The agent.** The Claude Code agent has no shell and no free web fetch; its rules treat documentation as evidence,
  never as instructions.
- **Builds.** The automatic `npm ci` in a platform-mcp checkout runs with `--ignore-scripts` from the lockfile only.
- **Releases.** Published from GitHub Actions with PyPI trusted publishing (no stored token).

This code was reviewed adversarially in October 2026 (before it became its own project); the regression tests for
those findings are in `tests/test_security_python.py`.
