# Structured Agent Harness

[![Build](https://img.shields.io/badge/build-passing-66cc33?style=for-the-badge)](./cli_anything/structured/tests)
[![Release](https://img.shields.io/badge/release-v0.1.0-3b82f6?style=for-the-badge)](./setup.py)
[![Access](https://img.shields.io/badge/access-public-4f46e5?style=for-the-badge)](https://github.com/Alvin0412/structured-agent-harness)
[![License](https://img.shields.io/badge/license-MIT-2563eb?style=for-the-badge)](./LICENSE)

Browser-backed CLI and MCP adapter for `https://web.structured.app/`.

This project wraps the closed-source Structured web app with:

- a CLI: `cli-anything-structured`
- a local `stdio` MCP server: `structured-mcp`

The harness reads Structured data from the app's own browser-side stores and
drives mutations through verified UI flows instead of direct local database
writes.

## Quick Start

Install the package in editable mode:

```bash
pip install -e .
```

Log into Structured once with the CLI:

```bash
cli-anything-structured session login
```

Then either use the CLI:

```bash
cli-anything-structured session status
cli-anything-structured task list --location all
cli-anything-structured recurring list --frequency weekly
```

Or start the local MCP server:

```bash
structured-mcp
```

## Repository Layout

```text
agent-harness/
├── README.md                              # repo entrypoint
├── STRUCTURED.md                          # backend notes and guardrails
├── setup.py                               # package metadata + console entry points
└── cli_anything/structured/
    ├── README.md                          # user-facing CLI and MCP usage
    ├── structured_cli.py                  # Click CLI
    ├── mcp_server.py                      # local stdio MCP server
    ├── core/
    │   └── models.py                      # shared dataclasses
    ├── utils/
    │   └── agent_browser_backend.py       # browser-backed Structured adapter
    ├── tests/
    │   ├── TEST.md                        # test scope and manual verification notes
    │   ├── test_backend.py                # backend unit tests
    │   ├── test_cli.py                    # CLI tests
    │   └── test_mcp_server.py             # MCP surface tests
    └── skills/
        └── SKILL.md                       # skill metadata for agent workflows
```

## Documentation

- [Harness Notes](./STRUCTURED.md)
- [CLI and MCP Usage](./cli_anything/structured/README.md)
- [Test Notes](./cli_anything/structured/tests/TEST.md)

## License

MIT. See [LICENSE](./LICENSE).

## Validation

Typical local checks:

```bash
python3 -m unittest cli_anything/structured/tests/test_backend.py -v
python3 -m unittest cli_anything/structured/tests/test_cli.py -v
python3 -m unittest cli_anything/structured/tests/test_mcp_server.py -v
```
