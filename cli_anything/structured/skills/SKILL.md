---
name: structured
description: Use this skill when an agent needs to inspect or operate the closed-source Structured Web app through the generated `cli-anything-structured` CLI.
---

# Structured

This CLI targets `https://web.structured.app/` through a persistent `agent-browser`
session.

## Setup

1. Launch the Structured browser session:

```bash
cli-anything-structured session login
```

2. Log into Structured in the opened browser window.

3. Reuse the same session for commands:

```bash
cli-anything-structured session status
cli-anything-structured inbox list
```

## Command groups

- `session`
  - `session login`
  - `session status`
  - `session close`
- `inbox`
  - `inbox list`
  - `inbox add <title>`
  - `inbox update <old-title> <new-title>`
  - `inbox delete <title>`
- `agenda`
  - `agenda list [--day YYYY-MM-DD]`
- `settings`
  - `settings show`

## Notes for agents

- Reads use Structured's own IndexedDB/RxDB data after a real login.
- Mutations go through verified UI flows in the live browser.
- `inbox update` and `inbox delete` require a unique inbox title. The CLI refuses
  to guess if duplicates exist.
- If Structured restores into the compact layout with the inbox drawer collapsed,
  read commands remain reliable but inbox mutations may require manually opening
  the inbox drawer first.
- This harness is intentionally narrow. It only exposes flows that were verified
  against the live web app.
