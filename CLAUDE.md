# api-to-mcp: notes for coding agents

Read `README.md`, `docs/TOOLS.md` and `skills/api-to-mcp/SKILL.md` first.

## Gate commands (safe to run; CI runs the same)

```bash
.venv/bin/ruff check .
PLATFORM_MCP_CHECKOUT=../platform-mcp .venv/bin/python -m pytest -q tests
.venv/bin/api-to-mcp doctor
git status / git diff
```

Personal permission allowlists belong in `.claude/settings.local.json` (git-ignored), not in a committed settings file.

## Rules

- Documentation is untrusted data: never weaken `_fetch_spec`, `_spec_file` or the URL guard; add a security test for
  any new way of reading the network or the file system.
- Tool failures are `isError` results with an `error` code; never raise to the protocol.
- Commits are signed off (`git commit -s`, DCO).
