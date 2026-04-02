# TEST.md

## Scope

This harness wraps a live closed-source web application, so local automated tests
focus on:

- command construction
- JSON decoding/parsing
- agenda merge logic
- CLI wiring and output contracts

Live end-to-end verification against a real Structured account should be done
manually after `session login`.

## Manual checks performed during development

- login onboarding completed in a persistent `agent-browser` session
- inbox list read from IndexedDB
- inbox add through the real input and `Add` button after repairing the compact off-screen inbox drawer
- inbox task drawer opened from the card body element that owns the real React `onClick` handler
- inbox task title updated via the drawer
- inbox task deleted via drawer delete + confirm
- daily agenda merged from `task`, `recurring_occurrence`, and `recurring`
- CLI reconnect succeeded by falling back to the profile's `DevToolsActivePort`
  after Chrome profile lock blocked a fresh `agent-browser` auto-launch

## Current limitation

This is still a browser-backed harness for a closed-source webapp. It depends on
the authenticated browser profile remaining valid and on the current Structured
web UI retaining the same core DOM structure for inbox cards, task drawer
controls, and IndexedDB store names.

## Automated tests

- `test_backend.py`
- `test_cli.py`
