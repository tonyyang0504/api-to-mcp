# Changelog

All notable changes to api-to-mcp are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.1] - 2026-10-05

### Fixed
- `doctor`: the dependency probe no longer imports modules from the current directory (a stray `numbers.py` made it
  report "blocked").
- The README, `doctor`'s TypeScript fix and `generate_server`'s `any_machine` hint now point at the published
  packages instead of saying "not published yet".

## [0.1.0] - 2026-10-04

First release as its own project (until 2026-10 it was "the forge" inside platform-mcp; the history came along).

### Added
- Your own workspace by default (`API_TO_MCP_HOME`, else `~/.local/share/api-to-mcp`): building an entry needs no
  platform-mcp checkout; entries run with `platform-mcp-hub serve --entry <file>`.
- Checkout mode (`API_TO_MCP_CHECKOUT` / `--checkout`) to contribute an entry to platform-mcp's catalog.
- `api-to-mcp` CLI with a command per tool, `api-to-mcp mcp` for the MCP server and `api-to-mcp serve`.
- `workspace` tool; `generate_server` returns a runnable contract-test template and, in your workspace, an MCP client
  config.
- Project files: Apache-2.0 licence and NOTICE, contributing guide with DCO sign-off, code of conduct, security
  policy, issue and pull request templates, CI, CodeQL, secret scanning, Dependabot, release workflow (PyPI trusted
  publishing).

### Changed
- Names: package `api-to-mcp` (was `platform-mcp-forge`), MCP server and plugin `api-to-mcp`, skill `/api-to-mcp`
  (was `/mcp-forge`), agent `api-to-mcp`.
- The gates run through platform-mcp-hub (`lint`, `try`, `smoke`, `verify`) instead of a checkout's `tools/` scripts.
- `generate_server` no longer writes per-platform packages: platform-mcp-hub serves every entry directly.
- Environment: `API_TO_MCP_HOME` / `API_TO_MCP_CHECKOUT` replace `PLATFORM_MCP_WORKSPACE` / `PLATFORM_MCP_ROOT`;
  `API_TO_MCP_AUTOBUILD` replaces `PLATFORM_MCP_FORGE_AUTOBUILD`.
