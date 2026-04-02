# Structured Harness Notes

This harness targets the closed-source `Structured Web` application at
`https://web.structured.app/`.

## Backend choice

- Reads use the app's own browser-side IndexedDB/RxDB stores after a real login.
- Writes use verified browser UI flows through `agent-browser`.
- The local MCP server reuses one in-process `StructuredBackend` singleton over
  the same persistent browser profile and serializes tool calls so browser state
  does not drift between overlapping operations.
- When Structured restores into the compact layout, the harness temporarily
  re-exposes the existing inbox drawer in the live DOM so it can drive the
  app's own controls. This is a layout-reachability repair, not a direct data
  write.
- Direct IndexedDB writes are intentionally avoided because they bypass app logic
  and are more likely to desynchronize local state and remote sync.

## Verified flows

- Launching a persistent browser session for login.
- Reconnecting to an already-running Structured browser via the profile's
  `DevToolsActivePort` when `agent-browser` session auto-launch is blocked by
  Chrome's profile singleton lock.
- Reading inbox tasks from IndexedDB.
- Reading daily agenda items by combining one-off tasks with recurring
  occurrences plus their recurring definitions.
- Reading one-off task lists and searches directly from IndexedDB task rows.
- Reading recurring task definitions directly from IndexedDB recurring rows.
- Adding an inbox task through the real inbox input and `Add` button, including
  the compact restored layout where the drawer would otherwise be off-screen.
- Opening an inbox task drawer by clicking the card body that owns the real
  React `onClick` handler.
- Updating an inbox task title in the drawer.
- Deleting an inbox task via the drawer's delete button and confirm dialog.
- Creating timed one-off tasks through the real create panel.
- Updating one-off task date, time, duration, note, and all-day state through
  the real task drawer.
- Reading, setting, and clearing task notes through the real task drawer.
- Adding a subtask through the real `Add Subtask` control.
- Creating, updating, and deleting recurring task definitions through the real
  repeat editor and repeating-scope dialogs.
- Opening truncated all-day cards with a narrow visible-text fallback when the
  live DOM only exposes a `...`-shortened label.

## Recurring update guardrail

- Structured's recurring update flow is sensitive to how the repeat editor is
  dismissed.
- Verified behavior: closing the repeat panel before clicking `Update Task` can
  send Structured down an occurrence-only confirmation path that detaches a
  single occurrence instead of updating the recurring series.
- The harness therefore keeps the repeat panel open for recurring rule updates
  and only accepts success after the recurring row itself changes in IndexedDB.

## Recurring delete semantics

- `delete --scope one` removes only the selected occurrence and can leave a
  detached occurrence tombstone in IndexedDB. The harness treats that tombstone
  as non-visible and excludes it from `agenda list`.
- `delete --scope future` is only accepted after Structured stops exposing any
  current-or-later visible occurrence for that series. A detached current-day
  occurrence by itself is not enough.
- `delete --scope all` is polled until the recurring row itself disappears.
- If Structured leaves a truncated recurring row with no visible occurrence at
  all, the harness raises a clear error and refuses to approximate cleanup with
  a direct local database mutation.

## Known limitations

- This is a browser-backed adapter for a closed-source webapp, not a source-code
  harness generated from an open repository.
- Inbox update/delete targets visible inbox cards and require a unique task
  title. If multiple inbox tasks share the same title, the command refuses to
  guess.
- Commands assume the authenticated browser session has already finished
  onboarding and is able to render the main planner UI.
- The MCP server does not own login. If the profile is logged out, it returns a
  clear error and expects reauthentication through `cli-anything-structured
  session login`.
- `duplicate` and `move-to-inbox` command paths are still under investigation.
  The CLI surface exists, but these flows are not yet treated as stable.
- Color, symbol, tag, archive, and hide write operations are intentionally not
  exposed yet because no verified end-to-end UI or backing model path has been
  locked down for them.
