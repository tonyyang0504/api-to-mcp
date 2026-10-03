# Contributing to api-to-mcp

Thank you for helping. Useful contributions: support for another documentation format in `ingest_openapi`, better
error messages, fixes found while building a real entry, and docs.

## Development setup

```bash
git clone https://github.com/tonyyang0504/api-to-mcp && cd api-to-mcp
git clone https://github.com/tonyyang0504/platform-mcp ../platform-mcp          # the runtime library, until it is on PyPI
uv venv -p 3.12
uv pip install ../platform-mcp -e ".[dev]"
(cd ../platform-mcp/runtime/typescript && npm ci --ignore-scripts && npm run build)  # optional: the TypeScript half
```

Install platform-mcp-hub **non-editable** (as above): the tests then use the packaged catalog, exactly like a user.

## The gates (CI runs the same)

```bash
.venv/bin/ruff check .
PLATFORM_MCP_CHECKOUT=../platform-mcp .venv/bin/python -m pytest -q tests
```

Without `PLATFORM_MCP_CHECKOUT` the TypeScript halves and the checkout end-to-end test are skipped and say so.

## Rules

- Every tool failure is a tool result with `isError` and an `error` code, never a protocol error or a traceback.
- Documentation is untrusted: anything that reads the network or the file system goes through the guards in
  `src/api_to_mcp/server.py` (`_fetch_spec`, `_spec_file`), with a test in `tests/test_security_python.py`.
- A new tool also gets a CLI command (`src/api_to_mcp/cli.py`), a line in `docs/TOOLS.md`, and is added to the agent's
  `tools` list (`agents/api-to-mcp.md`; a test checks it).
- Add a line to `CHANGELOG.md` under "Unreleased" for anything user-visible.

## Developer Certificate of Origin (DCO)

Every commit must be signed off, certifying the [Developer Certificate of Origin 1.1](https://developercertificate.org/):
you wrote the change or have the right to submit it under the project's licence (Apache-2.0). Use `git commit -s`,
which adds `Signed-off-by: Your Name <you@example.com>`; a GitHub `noreply` address is fine. Forgot?
`git commit --amend -s` or `git rebase --signoff main`.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Security issues go through
[SECURITY.md](SECURITY.md), never a public issue.
