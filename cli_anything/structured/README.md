# cli-anything-structured

`cli-anything-structured` is a browser-backed CLI harness for
`https://web.structured.app/`.

## What it can do today

- launch a persistent Structured browser session for login
- inspect session status
- list inbox tasks
- add inbox tasks
- update inbox task titles
- delete inbox tasks
- list a day's agenda by combining one-off tasks with recurring occurrences
- list and search one-off tasks across Structured's local dataset
- inspect one-off tasks by id or unique title
- list and inspect recurring task definitions
- create, update, and delete recurring task definitions
- create and update one-off tasks with date, time, duration, and note fields
- read, set, and clear task notes
- toggle task all-day mode
- list and add task subtasks
- inspect app settings stored in Structured's local IndexedDB
- expose the stable Structured tool surface through a local `stdio` MCP server

## Why browser-backed

Structured is closed-source, so this harness uses the real web app plus
`agent-browser` instead of generating a wrapper from source code. Reads come from
the app's own IndexedDB/RxDB data. Mutations go through verified UI flows.

When Structured restores into the compact layout with the inbox drawer hidden
off-screen, the harness temporarily re-exposes that existing drawer in the live
DOM so it can keep using the app's own add/edit/delete handlers. It still does
not write directly into IndexedDB.

If `agent-browser` cannot reattach through its saved session because Chrome is
already holding the profile lock, the harness falls back to the profile's live
`DevToolsActivePort` and reconnects to the already-running browser.

One UI-specific adaptation is worth calling out explicitly: Structured can
truncate visible all-day task titles into `...` inside the live DOM. The
harness has a narrow selector fallback for that case so it can still click the
real card. This is still a UI-layer interaction, not a direct data write.

## Authentication

```bash
cli-anything-structured session login
```

That launches a persistent browser profile. Log into Structured in that window,
then reuse the same profile for future commands.

The MCP server does not open the login flow automatically. If the browser profile
has expired, reauthenticate with the CLI first and then reuse the same profile
from MCP.

## MCP

Run the local MCP server over `stdio`:

```bash
structured-mcp
```

The server reuses the same persistent Structured browser profile as the CLI and
keeps one in-process backend instance for all tool calls. It exposes only the
stable business tools, not raw browser controls and not the experimental
`duplicate` / `move-to-inbox` paths.

If you need to refresh the login state, do that outside MCP:

```bash
cli-anything-structured session login
```

## Examples

```bash
cli-anything-structured session status
cli-anything-structured inbox list
cli-anything-structured inbox add "Prepare math notes"
cli-anything-structured inbox update "Prepare math notes" "Prepare calculus notes"
cli-anything-structured inbox delete "Prepare calculus notes"
cli-anything-structured agenda list --day 2026-04-01
cli-anything-structured task list --location all --limit 20
cli-anything-structured task search "calculus"
cli-anything-structured task create "Prepare slides" --day 2026-04-10 --start "09:15 AM" --duration 45 --note "Draft outline first"
cli-anything-structured task note set "Prepare slides" "Updated note"
cli-anything-structured task set-all-day "Prepare slides" --on
cli-anything-structured recurring list --frequency weekly --limit 20
cli-anything-structured recurring show 17c47c2c-cd7e-4d5e-8c32-9a1886f47986
cli-anything-structured recurring create "Friday review" --frequency weekly --weekday Fri --start-day 2026-04-03 --start "09:00 AM" --duration 30 --end-day 2026-04-24
cli-anything-structured recurring update "Friday review" --frequency monthly --interval 1
cli-anything-structured recurring delete "Friday review"
cli-anything-structured settings show
```

`recurring delete` supports `--scope one`, `--scope future`, and `--scope all`.
If Structured leaves an orphaned recurring row with no visible occurrence left,
the harness surfaces that explicitly instead of approximating cleanup with a
direct IndexedDB write.

## REPL

Running the command without a subcommand starts a simple interactive REPL:

```bash
cli-anything-structured
structured> inbox list
structured> agenda list --day 2026-04-01
structured> quit
```
