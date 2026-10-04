# Release checklist

api-to-mcp is published to PyPI from GitHub Actions (`.github/workflows/release.yml`) when a tag `vX.Y.Z` is pushed,
through **trusted publishing** (OIDC; no token is stored). It depends on `platform-mcp-hub`, so platform-mcp-hub must
be on PyPI first (its own checklist: platform-mcp's `docs/RELEASE_CHECKLIST.md`). There is no npm package.

## One-time setup (operator)

1. **GitHub environment**: repository settings → Environments → `pypi`; add yourself as a required reviewer and
   restrict it to tags `v*`.
2. **PyPI pending trusted publisher**: pypi.org → Your account → Publishing → Add a new pending publisher → GitHub:
   project `api-to-mcp-forge`, owner `tonyyang0504`, repository `api-to-mcp`, workflow `release.yml`, environment `pypi`.
## Release

1. CI green on `main` (tests on 3.10/3.12/3.13 with both runtimes, ruff, CodeQL, secret scan).
2. Same version in `pyproject.toml`, `src/api_to_mcp/__init__.py` and `.claude-plugin/plugin.json` (the workflow checks
   the tag against all three); `CHANGELOG.md` "Unreleased" moved under the version.
3. `git tag -s v0.1.0 -m "api-to-mcp 0.1.0" && git push origin v0.1.0`, then approve the `pypi` deployment.
4. On a clean machine: `uvx --from api-to-mcp-forge api-to-mcp doctor` reports your workspace and `mode: full` or `python_only`;
   `claude plugin marketplace add tonyyang0504/api-to-mcp && claude plugin install api-to-mcp@api-to-mcp` starts the
   server.
