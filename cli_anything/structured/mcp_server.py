from __future__ import annotations

from threading import RLock
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from cli_anything.structured.core.models import AgendaItem, InboxTask, RecurringInfo, SettingsInfo, SubtaskInfo, TaskInfo
from cli_anything.structured.utils import (
    StructuredAmbiguousError,
    StructuredBackend,
    StructuredBackendError,
    StructuredNotFoundError,
)

SERVER_NAME = "Structured"
SERVER_INSTRUCTIONS = (
    "Local Structured Web MCP server backed by an authenticated browser profile. "
    "Tools reuse one persistent Structured browser profile, return structured data, "
    "and do not manage login automatically. If the planner UI is unavailable, "
    "reauthenticate with `cli-anything-structured session login`."
)

server = FastMCP(
    SERVER_NAME,
    instructions=SERVER_INSTRUCTIONS,
)

_backend_singleton: StructuredBackend | None = None
_backend_lock = RLock()


def _get_backend() -> StructuredBackend:
    global _backend_singleton
    with _backend_lock:
        if _backend_singleton is None:
            _backend_singleton = StructuredBackend()
        return _backend_singleton


def _serialize(value: Any) -> Any:
    if isinstance(value, (InboxTask, TaskInfo, RecurringInfo, AgendaItem, SettingsInfo, SubtaskInfo)):
        return value.to_dict()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _tool_error(exc: Exception) -> ToolError:
    if isinstance(exc, StructuredNotFoundError):
        return ToolError(f"Structured item not found: {exc}")
    if isinstance(exc, StructuredAmbiguousError):
        return ToolError(f"Structured reference is ambiguous: {exc}")
    if isinstance(exc, StructuredBackendError):
        return ToolError(str(exc))
    return ToolError(str(exc))


def _invoke_backend(method_name: str, *args: Any, **kwargs: Any) -> Any:
    with _backend_lock:
        backend = _get_backend()
        method = getattr(backend, method_name)
        try:
            return _serialize(method(*args, **kwargs))
        except (StructuredNotFoundError, StructuredAmbiguousError, StructuredBackendError) as exc:
            raise _tool_error(exc) from exc


def _all_day_filter(value: bool | None) -> Literal["all", "only", "exclude"]:
    if value is None:
        return "all"
    return "only" if value else "exclude"


@server.tool(
    name="structured_status",
    description="Inspect the current Structured browser session and planner availability.",
    structured_output=True,
)
def structured_status() -> dict[str, Any]:
    return _invoke_backend("session_status")


@server.tool(
    name="structured_inbox_list",
    description="List inbox tasks from Structured.",
    structured_output=True,
)
def structured_inbox_list() -> list[dict[str, Any]]:
    return _invoke_backend("inbox_list")


@server.tool(
    name="structured_inbox_add",
    description="Add a new inbox task in Structured.",
    structured_output=True,
)
def structured_inbox_add(title: str) -> dict[str, Any]:
    return _invoke_backend("inbox_add", title)


@server.tool(
    name="structured_inbox_update",
    description="Rename an inbox task by unique title.",
    structured_output=True,
)
def structured_inbox_update(old_title: str, new_title: str) -> dict[str, Any]:
    return _invoke_backend("inbox_update", old_title, new_title)


@server.tool(
    name="structured_inbox_delete",
    description="Delete an inbox task by unique title.",
    structured_output=True,
)
def structured_inbox_delete(title: str) -> dict[str, Any]:
    return _invoke_backend("inbox_delete", title)


@server.tool(
    name="structured_agenda_list",
    description="List agenda items for a Structured day.",
    structured_output=True,
)
def structured_agenda_list(day: str | None = None) -> list[dict[str, Any]]:
    return _invoke_backend("agenda_list", day=day)


@server.tool(
    name="structured_settings_show",
    description="Read Structured settings from the local browser profile.",
    structured_output=True,
)
def structured_settings_show() -> dict[str, Any]:
    return _invoke_backend("settings_show")


@server.tool(
    name="structured_task_list",
    description="List one-off Structured tasks with optional filters.",
    structured_output=True,
)
def structured_task_list(
    query: str | None = None,
    day: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: Literal["open", "completed", "all"] = "open",
    location: Literal["all", "inbox", "scheduled"] = "all",
    all_day: bool | None = None,
    color: str | None = None,
    symbol: str | None = None,
    include_hidden: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return _invoke_backend(
        "task_list",
        query=query,
        day=day,
        date_from=date_from,
        date_to=date_to,
        status=status,
        location=location,
        all_day=_all_day_filter(all_day),
        color=color,
        symbol=symbol,
        include_hidden=include_hidden,
        limit=limit,
        offset=offset,
    )


@server.tool(
    name="structured_task_search",
    description="Search one-off Structured tasks by text.",
    structured_output=True,
)
def structured_task_search(
    query: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return _invoke_backend(
        "task_list",
        query=query,
        status="all",
        location="all",
        limit=limit,
        offset=offset,
    )


@server.tool(
    name="structured_task_show",
    description="Inspect one one-off Structured task by id or unique title.",
    structured_output=True,
)
def structured_task_show(reference: str) -> dict[str, Any]:
    return _invoke_backend("task_show", reference)


@server.tool(
    name="structured_task_create",
    description="Create a one-off Structured task.",
    structured_output=True,
)
def structured_task_create(
    title: str,
    day: str | None = None,
    start: str | None = None,
    end: str | None = None,
    duration: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    return _invoke_backend(
        "task_create",
        title=title,
        day=day,
        start=start,
        end=end,
        duration=duration,
        note=note,
    )


@server.tool(
    name="structured_task_update",
    description="Update a one-off Structured task.",
    structured_output=True,
)
def structured_task_update(
    reference: str,
    new_title: str | None = None,
    day: str | None = None,
    start: str | None = None,
    end: str | None = None,
    duration: int | None = None,
    note: str | None = None,
    all_day: bool | None = None,
) -> dict[str, Any]:
    return _invoke_backend(
        "task_update",
        reference,
        new_title=new_title,
        day=day,
        start=start,
        end=end,
        duration=duration,
        note=note,
        all_day=all_day,
    )


@server.tool(
    name="structured_task_delete",
    description="Delete a one-off Structured task.",
    structured_output=True,
)
def structured_task_delete(reference: str) -> dict[str, Any]:
    return _invoke_backend("task_delete", reference)


@server.tool(
    name="structured_task_complete",
    description="Mark a one-off Structured task completed.",
    structured_output=True,
)
def structured_task_complete(reference: str) -> dict[str, Any]:
    return _invoke_backend("task_complete", reference)


@server.tool(
    name="structured_task_restore",
    description="Restore a completed one-off Structured task to open state.",
    structured_output=True,
)
def structured_task_restore(reference: str) -> dict[str, Any]:
    return _invoke_backend("task_restore", reference)


@server.tool(
    name="structured_task_note_get",
    description="Read the note for a one-off Structured task.",
    structured_output=True,
)
def structured_task_note_get(reference: str) -> dict[str, Any]:
    note = _invoke_backend("task_note_get", reference)
    return {"reference": reference, "note": note}


@server.tool(
    name="structured_task_note_set",
    description="Replace the note for a one-off Structured task.",
    structured_output=True,
)
def structured_task_note_set(reference: str, note: str) -> dict[str, Any]:
    return _invoke_backend("task_note_set", reference, note)


@server.tool(
    name="structured_task_note_clear",
    description="Clear the note for a one-off Structured task.",
    structured_output=True,
)
def structured_task_note_clear(reference: str) -> dict[str, Any]:
    return _invoke_backend("task_note_clear", reference)


@server.tool(
    name="structured_task_set_all_day",
    description="Toggle all-day mode for a one-off Structured task.",
    structured_output=True,
)
def structured_task_set_all_day(reference: str, enabled: bool) -> dict[str, Any]:
    return _invoke_backend("task_set_all_day", reference, enabled)


@server.tool(
    name="structured_task_subtask_list",
    description="List subtasks for a one-off Structured task.",
    structured_output=True,
)
def structured_task_subtask_list(reference: str) -> list[dict[str, Any]]:
    return _invoke_backend("task_subtask_list", reference)


@server.tool(
    name="structured_task_subtask_add",
    description="Add a subtask to a one-off Structured task.",
    structured_output=True,
)
def structured_task_subtask_add(reference: str, title: str) -> dict[str, Any]:
    return _invoke_backend("task_subtask_add", reference, title)


@server.tool(
    name="structured_recurring_list",
    description="List Structured recurring task definitions.",
    structured_output=True,
)
def structured_recurring_list(
    query: str | None = None,
    frequency: Literal["daily", "weekly", "monthly"] | None = None,
    active_on: str | None = None,
    include_ended: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return _invoke_backend(
        "recurring_list",
        query=query,
        frequency=frequency,
        active_on=active_on,
        include_ended=include_ended,
        limit=limit,
        offset=offset,
    )


@server.tool(
    name="structured_recurring_search",
    description="Search Structured recurring task definitions by text.",
    structured_output=True,
)
def structured_recurring_search(
    query: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    return _invoke_backend("recurring_list", query=query, limit=limit, offset=offset)


@server.tool(
    name="structured_recurring_show",
    description="Inspect one Structured recurring task definition by id or unique title.",
    structured_output=True,
)
def structured_recurring_show(reference: str) -> dict[str, Any]:
    return _invoke_backend("recurring_show", reference)


@server.tool(
    name="structured_recurring_create",
    description="Create a Structured recurring task definition.",
    structured_output=True,
)
def structured_recurring_create(
    title: str,
    frequency: Literal["daily", "weekly", "monthly"],
    start_day: str | None = None,
    start: str | None = None,
    end: str | None = None,
    duration: int | None = None,
    note: str | None = None,
    all_day: bool = False,
    interval: int = 1,
    weekdays: list[str] | None = None,
    end_day: str | None = None,
) -> dict[str, Any]:
    return _invoke_backend(
        "recurring_create",
        title=title,
        frequency=frequency,
        start_day=start_day,
        start=start,
        end=end,
        duration=duration,
        note=note,
        all_day=all_day,
        interval=interval,
        weekdays=weekdays,
        end_day=end_day,
    )


@server.tool(
    name="structured_recurring_update",
    description="Update a Structured recurring task definition.",
    structured_output=True,
)
def structured_recurring_update(
    reference: str,
    new_title: str | None = None,
    frequency: Literal["daily", "weekly", "monthly"] | None = None,
    start_day: str | None = None,
    start: str | None = None,
    end: str | None = None,
    duration: int | None = None,
    note: str | None = None,
    all_day: bool | None = None,
    interval: int | None = None,
    weekdays: list[str] | None = None,
    end_day: str | None = None,
    no_end_day: bool = False,
) -> dict[str, Any]:
    return _invoke_backend(
        "recurring_update",
        reference,
        new_title=new_title,
        frequency=frequency,
        start_day=start_day,
        start=start,
        end=end,
        duration=duration,
        note=note,
        all_day=all_day,
        interval=interval,
        weekdays=weekdays,
        end_day=end_day,
        clear_end_day=no_end_day,
    )


@server.tool(
    name="structured_recurring_delete",
    description="Delete a Structured recurring task definition with a selected scope.",
    structured_output=True,
)
def structured_recurring_delete(
    reference: str,
    scope: Literal["all", "future", "one"] = "all",
) -> dict[str, Any]:
    return _invoke_backend("recurring_delete", reference, scope=scope)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
