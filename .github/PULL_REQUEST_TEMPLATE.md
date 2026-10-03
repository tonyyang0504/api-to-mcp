## What and why

## Checklist

- [ ] `ruff check .` and `pytest -q tests` pass (with `PLATFORM_MCP_CHECKOUT` if you touched the TypeScript or checkout paths)
- [ ] New network or file access goes through the guards and has a test in `tests/test_security_python.py`
- [ ] New tools have a CLI command, a line in `docs/TOOLS.md` and are in the agent's `tools` list
- [ ] `CHANGELOG.md` updated for user-visible changes
- [ ] Commits are signed off (`git commit -s`, DCO)
