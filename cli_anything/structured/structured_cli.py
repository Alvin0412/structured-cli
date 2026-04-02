from __future__ import annotations

import json
import shlex
import sys
from datetime import datetime
from typing import Any

import click

from cli_anything.structured import __version__
from cli_anything.structured.core.models import (
    AgendaItem,
    InboxTask,
    RecurringInfo,
    SettingsInfo,
    SubtaskInfo,
    TaskInfo,
)
from cli_anything.structured.utils import (
    StructuredAmbiguousError,
    StructuredBackend,
    StructuredBackendError,
    StructuredNotFoundError,
)


class AppContext:
    def __init__(self, *, json_output: bool, session: str, profile: str, agent_browser: str | None) -> None:
        self.json_output = json_output
        self.backend = StructuredBackend(
            session=session,
            profile=profile,
            agent_browser=agent_browser,
        )


def _make_context(ctx: click.Context) -> AppContext:
    app = ctx.ensure_object(AppContext)
    return app


def _emit(ctx: click.Context, payload: Any, *, human: str | None = None) -> None:
    app = _make_context(ctx)
    if app.json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if human is not None:
        click.echo(human)
        return
    if isinstance(payload, list):
        for item in payload:
            click.echo(str(item))
        return
    click.echo(str(payload))


def _format_inbox(tasks: list[InboxTask]) -> str:
    lines = [f"{len(tasks)} inbox task(s)"]
    for task in tasks:
        status = "done" if task.is_completed else "open"
        lines.append(f"- [{status}] {task.title}")
    return "\n".join(lines)


def _format_agenda(items: list[AgendaItem], *, day: str) -> str:
    lines = [f"{len(items)} agenda item(s) for {day}"]
    for item in items:
        start = format_start_time(item.start_time)
        duration = f"{item.duration} min" if item.duration is not None else "unspecified"
        status = "done" if item.is_completed else "open"
        lines.append(f"- [{status}] {start} {item.title} ({item.source}, {duration})")
    return "\n".join(lines)


def _format_settings(settings: SettingsInfo) -> str:
    return "\n".join(
        [
            f"user_id: {settings.user_id}",
            f"theme: {settings.theme}",
            f"layout: {settings.layout}",
            f"timezone: {settings.timezone}",
            f"first_weekday: {settings.first_weekday}",
            f"cloud_terms_date: {settings.cloud_terms_date}",
            f"duration_presets: {', '.join(str(value) for value in settings.duration_presets)}",
        ]
    )


def _format_task(task: TaskInfo) -> str:
    lines = [
        f"id: {task.id}",
        f"title: {task.title}",
        f"day: {task.day}",
        f"start: {format_start_time(task.start_time)}",
        f"duration: {task.duration}",
        f"inbox: {task.is_in_inbox}",
        f"all_day: {task.is_all_day}",
        f"hidden: {task.is_hidden}",
        f"completed: {task.is_completed}",
        f"note: {task.note}",
    ]
    if task.subtasks:
        lines.append(f"subtasks: {', '.join(subtask.title for subtask in task.subtasks)}")
    return "\n".join(lines)


def _format_recurring(recurring: RecurringInfo) -> str:
    lines = [
        f"id: {recurring.id}",
        f"title: {recurring.title}",
        f"frequency: {recurring.frequency}",
        f"interval: {recurring.interval}",
        f"start_day: {recurring.start_day}",
        f"end_day: {recurring.end_day}",
        f"start: {format_start_time(recurring.start_time)}",
        f"duration: {recurring.duration}",
        f"all_day: {recurring.is_all_day}",
        f"weekdays: {', '.join(recurring.weekdays) if recurring.weekdays else '-'}",
        f"note: {recurring.note}",
    ]
    if recurring.subtasks:
        lines.append(f"subtasks: {', '.join(subtask.title for subtask in recurring.subtasks)}")
    return "\n".join(lines)


def _format_subtasks(subtasks: list[SubtaskInfo]) -> str:
    lines = [f"{len(subtasks)} subtask(s)"]
    for subtask in subtasks:
        lines.append(f"- {subtask.title}")
    return "\n".join(lines)


def format_start_time(value: float | None) -> str:
    if value is None:
        return "--:--"
    total_minutes = round(value * 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def parse_day_option(value: str | None) -> str | None:
    if value is None:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date().isoformat()


@click.group(invoke_without_command=True)
@click.option("--json", "json_output", is_flag=True, help="Emit structured JSON output.")
@click.option("--session", default="structured", show_default=True, help="agent-browser session name.")
@click.option(
    "--profile",
    default=str(StructuredBackend().profile),
    show_default=True,
    help="Persistent agent-browser profile path.",
)
@click.option("--agent-browser", default=None, help="Path to the agent-browser executable.")
@click.version_option(__version__)
@click.pass_context
def cli(
    ctx: click.Context,
    json_output: bool,
    session: str,
    profile: str,
    agent_browser: str | None,
) -> None:
    ctx.obj = AppContext(
        json_output=json_output,
        session=session,
        profile=profile,
        agent_browser=agent_browser,
    )
    if ctx.invoked_subcommand is None:
        _run_repl(ctx, session=session)


@cli.group()
def session() -> None:
    """Manage the authenticated Structured browser session."""


@session.command("login")
@click.pass_context
def session_login(ctx: click.Context) -> None:
    payload = _make_context(ctx).backend.launch_login()
    _emit(
        ctx,
        payload,
        human=(
            f"Launched Structured login browser for session {payload['session']!r}.\n"
            "Log into Structured in that window, then reuse the same session for later commands."
        ),
    )


@session.command("status")
@click.pass_context
def session_status(ctx: click.Context) -> None:
    payload = _make_context(ctx).backend.session_status()
    human = "\n".join(
        [
            f"session: {payload['session']}",
            f"url: {payload['url']}",
            f"title: {payload['title']}",
            f"logged_in: {payload['logged_in']}",
            f"browser_day: {payload['browser_day']}",
            f"browser_timezone: {payload['browser_timezone']}",
        ]
    )
    _emit(ctx, payload, human=human)


@session.command("close")
@click.pass_context
def session_close(ctx: click.Context) -> None:
    _make_context(ctx).backend.close_browser()
    _emit(ctx, {"closed": True}, human="Structured browser session closed.")


@cli.group()
def inbox() -> None:
    """Manage Structured inbox tasks."""


@inbox.command("list")
@click.pass_context
def inbox_list(ctx: click.Context) -> None:
    tasks = _make_context(ctx).backend.inbox_list()
    payload = [task.to_dict() for task in tasks]
    _emit(ctx, payload, human=_format_inbox(tasks))


@inbox.command("add")
@click.argument("title")
@click.pass_context
def inbox_add(ctx: click.Context, title: str) -> None:
    task = _make_context(ctx).backend.inbox_add(title)
    _emit(ctx, task.to_dict(), human=f"Added inbox task: {task.title}")


@inbox.command("update")
@click.argument("old_title")
@click.argument("new_title")
@click.pass_context
def inbox_update(ctx: click.Context, old_title: str, new_title: str) -> None:
    task = _make_context(ctx).backend.inbox_update(old_title, new_title)
    _emit(ctx, task.to_dict(), human=f"Updated inbox task to: {task.title}")


@inbox.command("delete")
@click.argument("title")
@click.pass_context
def inbox_delete(ctx: click.Context, title: str) -> None:
    payload = _make_context(ctx).backend.inbox_delete(title)
    _emit(ctx, payload, human=f"Deleted inbox task: {title}")


@cli.group()
def agenda() -> None:
    """Inspect Structured day agenda items."""


@agenda.command("list")
@click.option("--day", default=None, help="Target day in YYYY-MM-DD. Defaults to the browser's local day.")
@click.pass_context
def agenda_list(ctx: click.Context, day: str | None) -> None:
    items = _make_context(ctx).backend.agenda_list(day=day)
    target_day = day or _make_context(ctx).backend.browser_today()["day"]
    payload = [item.to_dict() for item in items]
    _emit(ctx, payload, human=_format_agenda(items, day=target_day))


@cli.group()
def settings() -> None:
    """Inspect Structured settings."""


@settings.command("show")
@click.pass_context
def settings_show(ctx: click.Context) -> None:
    settings_info = _make_context(ctx).backend.settings_show()
    _emit(ctx, settings_info.to_dict(), human=_format_settings(settings_info))


@cli.group()
def task() -> None:
    """Manage non-recurring Structured tasks with fuller controls."""


@task.command("list")
@click.option("--query", default=None, help="Filter by title, note, or subtask text.")
@click.option("--day", default=None, callback=lambda _ctx, _param, value: parse_day_option(value), help="Exact day in YYYY-MM-DD.")
@click.option("--from", "date_from", default=None, callback=lambda _ctx, _param, value: parse_day_option(value), help="Earliest day in YYYY-MM-DD.")
@click.option("--to", "date_to", default=None, callback=lambda _ctx, _param, value: parse_day_option(value), help="Latest day in YYYY-MM-DD.")
@click.option("--status", type=click.Choice(["open", "completed", "all"]), default="open", show_default=True)
@click.option("--location", type=click.Choice(["all", "inbox", "scheduled"]), default="all", show_default=True)
@click.option("--all-day", "all_day", type=click.Choice(["all", "only", "exclude"]), default="all", show_default=True)
@click.option("--color", default=None, help="Exact task color.")
@click.option("--symbol", default=None, help="Exact task symbol.")
@click.option("--include-hidden", is_flag=True, help="Include tasks marked hidden.")
@click.option("--limit", type=int, default=50, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.pass_context
def task_list(
    ctx: click.Context,
    query: str | None,
    day: str | None,
    date_from: str | None,
    date_to: str | None,
    status: str,
    location: str,
    all_day: str,
    color: str | None,
    symbol: str | None,
    include_hidden: bool,
    limit: int,
    offset: int,
) -> None:
    tasks = _make_context(ctx).backend.task_list(
        query=query,
        day=day,
        date_from=date_from,
        date_to=date_to,
        status=status,
        location=location,
        all_day=all_day,
        color=color,
        symbol=symbol,
        include_hidden=include_hidden,
        limit=limit,
        offset=offset,
    )
    payload = [task.to_dict() for task in tasks]
    _emit(ctx, payload, human="\n\n".join(_format_task(task) for task in tasks))


@task.command("search")
@click.argument("query")
@click.option("--limit", type=int, default=50, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.pass_context
def task_search(ctx: click.Context, query: str, limit: int, offset: int) -> None:
    tasks = _make_context(ctx).backend.task_list(query=query, status="all", location="all", limit=limit, offset=offset)
    payload = [task.to_dict() for task in tasks]
    _emit(ctx, payload, human="\n\n".join(_format_task(task) for task in tasks))


@task.command("show")
@click.argument("reference")
@click.pass_context
def task_show(ctx: click.Context, reference: str) -> None:
    task_info = _make_context(ctx).backend.task_show(reference)
    _emit(ctx, task_info.to_dict(), human=_format_task(task_info))


@task.command("create")
@click.argument("title")
@click.option("--day", default=None, callback=lambda _ctx, _param, value: parse_day_option(value), help="Target day in YYYY-MM-DD.")
@click.option("--start", default=None, help="Start time in hh:mm AM/PM, for example 09:15 AM.")
@click.option("--end", default=None, help="End time in hh:mm AM/PM, for example 10:00 AM.")
@click.option("--duration", type=int, default=None, help="Duration in minutes. Used when --end is omitted.")
@click.option("--note", default=None, help="Optional note text.")
@click.pass_context
def task_create(
    ctx: click.Context,
    title: str,
    day: str | None,
    start: str | None,
    end: str | None,
    duration: int | None,
    note: str | None,
) -> None:
    task_info = _make_context(ctx).backend.task_create(
        title=title,
        day=day,
        start=start,
        end=end,
        duration=duration,
        note=note,
    )
    _emit(ctx, task_info.to_dict(), human=f"Created task: {task_info.title}")


@task.command("update")
@click.argument("reference")
@click.option("--new-title", default=None, help="Replacement title.")
@click.option("--day", default=None, callback=lambda _ctx, _param, value: parse_day_option(value), help="Target day in YYYY-MM-DD.")
@click.option("--start", default=None, help="Start time in hh:mm AM/PM, for example 09:15 AM.")
@click.option("--end", default=None, help="End time in hh:mm AM/PM, for example 10:00 AM.")
@click.option("--duration", type=int, default=None, help="Duration in minutes. Used when --end is omitted.")
@click.option("--note", default=None, help="Replacement note text. Pass an empty string to clear it.")
@click.option("--all-day", "all_day", default=None, type=click.Choice(["on", "off"]), help="Toggle all-day mode.")
@click.pass_context
def task_update(
    ctx: click.Context,
    reference: str,
    new_title: str | None,
    day: str | None,
    start: str | None,
    end: str | None,
    duration: int | None,
    note: str | None,
    all_day: str | None,
) -> None:
    task_info = _make_context(ctx).backend.task_update(
        reference,
        new_title=new_title,
        day=day,
        start=start,
        end=end,
        duration=duration,
        note=note,
        all_day={"on": True, "off": False}.get(all_day),
    )
    _emit(ctx, task_info.to_dict(), human=f"Updated task: {task_info.title}")


@task.group("note")
def task_note() -> None:
    """Manage task notes."""


@task_note.command("get")
@click.argument("reference")
@click.pass_context
def task_note_get(ctx: click.Context, reference: str) -> None:
    payload = {"reference": reference, "note": _make_context(ctx).backend.task_note_get(reference)}
    _emit(ctx, payload, human=payload["note"])


@task_note.command("set")
@click.argument("reference")
@click.argument("note")
@click.pass_context
def task_note_set(ctx: click.Context, reference: str, note: str) -> None:
    task_info = _make_context(ctx).backend.task_note_set(reference, note)
    _emit(ctx, task_info.to_dict(), human=f"Updated note for task: {task_info.title}")


@task_note.command("clear")
@click.argument("reference")
@click.pass_context
def task_note_clear(ctx: click.Context, reference: str) -> None:
    task_info = _make_context(ctx).backend.task_note_clear(reference)
    _emit(ctx, task_info.to_dict(), human=f"Cleared note for task: {task_info.title}")


@task.command("set-all-day")
@click.argument("reference")
@click.option("--on/--off", "enabled", default=True, show_default=True)
@click.pass_context
def task_set_all_day(ctx: click.Context, reference: str, enabled: bool) -> None:
    task_info = _make_context(ctx).backend.task_set_all_day(reference, enabled)
    _emit(ctx, task_info.to_dict(), human=f"Set all-day={enabled} for task: {task_info.title}")


@task.group("subtask")
def task_subtask() -> None:
    """Manage task subtasks."""


@task_subtask.command("list")
@click.argument("reference")
@click.pass_context
def task_subtask_list(ctx: click.Context, reference: str) -> None:
    subtasks = _make_context(ctx).backend.task_subtask_list(reference)
    payload = [subtask.to_dict() for subtask in subtasks]
    _emit(ctx, payload, human=_format_subtasks(subtasks))


@task_subtask.command("add")
@click.argument("reference")
@click.argument("title")
@click.pass_context
def task_subtask_add(ctx: click.Context, reference: str, title: str) -> None:
    task_info = _make_context(ctx).backend.task_subtask_add(reference, title)
    _emit(ctx, task_info.to_dict(), human=f"Added subtask to task: {task_info.title}")


@task.command("complete")
@click.argument("reference")
@click.pass_context
def task_complete(ctx: click.Context, reference: str) -> None:
    task_info = _make_context(ctx).backend.task_complete(reference)
    _emit(ctx, task_info.to_dict(), human=f"Completed task: {task_info.title}")


@task.command("restore")
@click.argument("reference")
@click.pass_context
def task_restore(ctx: click.Context, reference: str) -> None:
    task_info = _make_context(ctx).backend.task_restore(reference)
    _emit(ctx, task_info.to_dict(), human=f"Restored task: {task_info.title}")


@task.command("duplicate")
@click.argument("reference")
@click.pass_context
def task_duplicate(ctx: click.Context, reference: str) -> None:
    task_info = _make_context(ctx).backend.task_duplicate(reference)
    _emit(ctx, task_info.to_dict(), human=f"Duplicated task: {task_info.title}")


@task.command("move-to-inbox")
@click.argument("reference")
@click.pass_context
def task_move_to_inbox(ctx: click.Context, reference: str) -> None:
    task_info = _make_context(ctx).backend.task_move_to_inbox(reference)
    _emit(ctx, task_info.to_dict(), human=f"Moved task to inbox: {task_info.title}")


@task.command("move-out-of-inbox")
@click.argument("reference")
@click.option("--day", required=True, callback=lambda _ctx, _param, value: parse_day_option(value), help="Target day in YYYY-MM-DD.")
@click.option("--start", default=None, help="Start time in hh:mm AM/PM.")
@click.option("--end", default=None, help="End time in hh:mm AM/PM.")
@click.option("--duration", type=int, default=None, help="Duration in minutes.")
@click.option("--all-day", "all_day", is_flag=True, help="Move to the schedule as an all-day task.")
@click.pass_context
def task_move_out_of_inbox(
    ctx: click.Context,
    reference: str,
    day: str,
    start: str | None,
    end: str | None,
    duration: int | None,
    all_day: bool,
) -> None:
    task_info = _make_context(ctx).backend.task_move_out_of_inbox(
        reference,
        day=day,
        start=start,
        end=end,
        duration=duration,
        all_day=all_day,
    )
    _emit(ctx, task_info.to_dict(), human=f"Moved inbox task into the schedule: {task_info.title}")


@task.command("delete")
@click.argument("reference")
@click.pass_context
def task_delete(ctx: click.Context, reference: str) -> None:
    payload = _make_context(ctx).backend.task_delete(reference)
    _emit(ctx, payload, human=f"Deleted task: {reference}")


@cli.group()
def recurring() -> None:
    """Inspect Structured recurring tasks."""


@recurring.command("list")
@click.option("--query", default=None, help="Filter by title, note, or subtask text.")
@click.option("--frequency", type=click.Choice(["daily", "weekly", "monthly"]), default=None)
@click.option("--active-on", default=None, callback=lambda _ctx, _param, value: parse_day_option(value), help="Only recurring tasks active on this day.")
@click.option("--include-ended/--exclude-ended", "include_ended", default=True, show_default=True)
@click.option("--limit", type=int, default=50, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.pass_context
def recurring_list(
    ctx: click.Context,
    query: str | None,
    frequency: str | None,
    active_on: str | None,
    include_ended: bool,
    limit: int,
    offset: int,
) -> None:
    recurring_tasks = _make_context(ctx).backend.recurring_list(
        query=query,
        frequency=frequency,
        active_on=active_on,
        include_ended=include_ended,
        limit=limit,
        offset=offset,
    )
    payload = [item.to_dict() for item in recurring_tasks]
    _emit(ctx, payload, human="\n\n".join(_format_recurring(item) for item in recurring_tasks))


@recurring.command("search")
@click.argument("query")
@click.option("--limit", type=int, default=50, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.pass_context
def recurring_search(ctx: click.Context, query: str, limit: int, offset: int) -> None:
    recurring_tasks = _make_context(ctx).backend.recurring_list(query=query, limit=limit, offset=offset)
    payload = [item.to_dict() for item in recurring_tasks]
    _emit(ctx, payload, human="\n\n".join(_format_recurring(item) for item in recurring_tasks))


@recurring.command("show")
@click.argument("reference")
@click.pass_context
def recurring_show(ctx: click.Context, reference: str) -> None:
    recurring_info = _make_context(ctx).backend.recurring_show(reference)
    _emit(ctx, recurring_info.to_dict(), human=_format_recurring(recurring_info))


@recurring.command("create")
@click.argument("title")
@click.option("--frequency", type=click.Choice(["daily", "weekly", "monthly"]), required=True)
@click.option("--start-day", default=None, callback=lambda _ctx, _param, value: parse_day_option(value), help="Recurring start day in YYYY-MM-DD.")
@click.option("--start", default=None, help="Start time in hh:mm AM/PM.")
@click.option("--end", default=None, help="End time in hh:mm AM/PM.")
@click.option("--duration", type=int, default=None, help="Duration in minutes.")
@click.option("--note", default=None, help="Optional note text.")
@click.option("--all-day", "all_day", is_flag=True, help="Create as an all-day recurring task.")
@click.option("--interval", type=int, default=1, show_default=True, help="Repeat interval.")
@click.option("--weekday", "weekdays", multiple=True, type=click.Choice(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]))
@click.option("--end-day", default=None, callback=lambda _ctx, _param, value: parse_day_option(value), help="Recurring end day in YYYY-MM-DD.")
@click.pass_context
def recurring_create(
    ctx: click.Context,
    title: str,
    frequency: str,
    start_day: str | None,
    start: str | None,
    end: str | None,
    duration: int | None,
    note: str | None,
    all_day: bool,
    interval: int,
    weekdays: tuple[str, ...],
    end_day: str | None,
) -> None:
    recurring_info = _make_context(ctx).backend.recurring_create(
        title=title,
        frequency=frequency,
        start_day=start_day,
        start=start,
        end=end,
        duration=duration,
        note=note,
        all_day=all_day,
        interval=interval,
        weekdays=list(weekdays) or None,
        end_day=end_day,
    )
    _emit(ctx, recurring_info.to_dict(), human=f"Created recurring task: {recurring_info.title}")


@recurring.command("update")
@click.argument("reference")
@click.option("--new-title", default=None, help="Replacement title.")
@click.option("--frequency", type=click.Choice(["daily", "weekly", "monthly"]), default=None)
@click.option("--start-day", default=None, callback=lambda _ctx, _param, value: parse_day_option(value), help="Recurring start day in YYYY-MM-DD.")
@click.option("--start", default=None, help="Start time in hh:mm AM/PM.")
@click.option("--end", default=None, help="End time in hh:mm AM/PM.")
@click.option("--duration", type=int, default=None, help="Duration in minutes.")
@click.option("--note", default=None, help="Replacement note text. Pass an empty string to clear it.")
@click.option("--all-day", "all_day", default=None, type=click.Choice(["on", "off"]), help="Toggle all-day mode.")
@click.option("--interval", type=int, default=None, help="Repeat interval.")
@click.option("--weekday", "weekdays", multiple=True, type=click.Choice(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]))
@click.option("--end-day", default=None, callback=lambda _ctx, _param, value: parse_day_option(value), help="Recurring end day in YYYY-MM-DD.")
@click.option("--no-end-day", is_flag=True, help="Clear the recurring end day and repeat indefinitely.")
@click.pass_context
def recurring_update(
    ctx: click.Context,
    reference: str,
    new_title: str | None,
    frequency: str | None,
    start_day: str | None,
    start: str | None,
    end: str | None,
    duration: int | None,
    note: str | None,
    all_day: str | None,
    interval: int | None,
    weekdays: tuple[str, ...],
    end_day: str | None,
    no_end_day: bool,
) -> None:
    recurring_info = _make_context(ctx).backend.recurring_update(
        reference,
        new_title=new_title,
        frequency=frequency,
        start_day=start_day,
        start=start,
        end=end,
        duration=duration,
        note=note,
        all_day={"on": True, "off": False}.get(all_day),
        interval=interval,
        weekdays=list(weekdays) or None,
        end_day=end_day,
        clear_end_day=no_end_day,
    )
    _emit(ctx, recurring_info.to_dict(), human=f"Updated recurring task: {recurring_info.title}")


@recurring.command("delete")
@click.argument("reference")
@click.option("--scope", type=click.Choice(["all", "future", "one"]), default="all", show_default=True)
@click.pass_context
def recurring_delete(ctx: click.Context, reference: str, scope: str) -> None:
    payload = _make_context(ctx).backend.recurring_delete(reference, scope=scope)
    _emit(ctx, payload, human=f"Deleted recurring task: {reference} ({scope})")


def _run_repl(ctx: click.Context, *, session: str) -> None:
    if not sys.stdin.isatty():
        click.echo(ctx.get_help())
        return

    click.echo(f"cli-anything-structured v{__version__}")
    click.echo(f"Structured REPL connected to session {session!r}. Type `help` or `quit`.")

    while True:
        try:
            line = input("structured> ").strip()
        except EOFError:
            click.echo()
            break
        except KeyboardInterrupt:
            click.echo()
            continue

        if not line:
            continue
        if line in {"quit", "exit"}:
            break
        if line in {"help", "?"}:
            click.echo(ctx.get_help())
            continue

        try:
            cli.main(
                args=shlex.split(line),
                prog_name="cli-anything-structured",
                obj=ctx.obj,
                standalone_mode=False,
            )
        except StructuredNotFoundError as exc:
            click.echo(f"Error: {exc}", err=True)
        except StructuredAmbiguousError as exc:
            click.echo(f"Error: {exc}", err=True)
        except StructuredBackendError as exc:
            click.echo(f"Error: {exc}", err=True)
        except click.ClickException as exc:
            exc.show()
        except SystemExit as exc:
            if exc.code not in (0, None):
                click.echo(f"Error: command exited with {exc.code}", err=True)


def main() -> None:
    cli()
