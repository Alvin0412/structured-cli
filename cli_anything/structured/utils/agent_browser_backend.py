from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date as date_cls
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from cli_anything.structured.core.models import (
    AgendaItem,
    InboxTask,
    RecurringInfo,
    SettingsInfo,
    SubtaskInfo,
    TaskInfo,
)

APP_URL = "https://web.structured.app/"
DEFAULT_SESSION = "structured"
DEFAULT_PROFILE = Path.home() / ".agent-browser-structured-profile"
TASK_DB = "rxdb-dexie-structured-web-app-db-v8--4--task"
RECURRING_DB = "rxdb-dexie-structured-web-app-db-v8--4--recurring"
RECURRING_OCCURRENCE_DB = "rxdb-dexie-structured-web-app-db-v8--2--recurring_occurrence"
WEEKDAY_FIELDS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WEEKDAY_NAMES = {
    "monday": "Mon",
    "tuesday": "Tue",
    "wednesday": "Wed",
    "thursday": "Thu",
    "friday": "Fri",
    "saturday": "Sat",
    "sunday": "Sun",
}
RECURRING_TYPE_TO_FREQUENCY = {
    1: "daily",
    2: "weekly",
    3: "monthly",
}
FREQUENCY_TO_RECURRING_TYPE = {value: key for key, value in RECURRING_TYPE_TO_FREQUENCY.items()}


class StructuredBackendError(RuntimeError):
    pass


class StructuredNotFoundError(StructuredBackendError):
    pass


class StructuredAmbiguousError(StructuredBackendError):
    pass


def decode_eval_output(raw: str) -> Any:
    value: Any = raw.strip()
    for _ in range(2):
        if not isinstance(value, str):
            return value
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def build_agenda_items(
    *,
    day: str,
    tasks: list[dict[str, Any]],
    occurrences: list[dict[str, Any]],
    recurring_map: dict[str, dict[str, Any]],
) -> list[AgendaItem]:
    items: list[AgendaItem] = []

    for task in tasks:
        items.append(
            AgendaItem(
                id=task["id"],
                source="task",
                title=task["title"],
                day=task["day"],
                start_time=task.get("start_time"),
                duration=task.get("duration"),
                completed_at=task.get("completed_at"),
                color=task.get("color"),
                symbol=task.get("symbol"),
                note=task.get("note"),
            )
        )

    for occurrence in occurrences:
        if occurrence.get("is_detached"):
            continue
        recurring = recurring_map.get(occurrence["recurring"])
        if not recurring:
            continue
        items.append(
            AgendaItem(
                id=occurrence["id"],
                source="recurring_occurrence",
                title=recurring["title"],
                day=day,
                start_time=recurring.get("start_time"),
                duration=recurring.get("duration"),
                completed_at=occurrence.get("completed_at"),
                color=recurring.get("color"),
                symbol=recurring.get("symbol"),
                note=recurring.get("note"),
            )
        )

    items.sort(key=lambda item: ((item.start_time is None), item.start_time or 0, item.title.lower()))
    return items


def build_task_info(row: dict[str, Any]) -> TaskInfo:
    return TaskInfo(
        id=row["id"],
        title=row["title"],
        day=row.get("day"),
        start_time=row.get("start_time"),
        duration=row.get("duration"),
        completed_at=row.get("completed_at") or None,
        modified_at=row.get("modified_at") or None,
        is_in_inbox=bool(row.get("is_in_inbox")),
        is_all_day=bool(row.get("is_all_day")),
        note=row.get("note") or "",
        color=row.get("color"),
        symbol=row.get("symbol"),
        is_hidden=bool(row.get("is_hidden")),
        subtasks=build_subtasks(row.get("subtasks")),
        metadata=dict(row.get("metadata") or {}),
    )


def build_subtasks(rows: Any) -> list[SubtaskInfo]:
    subtasks: list[SubtaskInfo] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        subtask_id = row.get("id")
        title = row.get("title")
        if not subtask_id or not title:
            continue
        subtasks.append(SubtaskInfo(id=str(subtask_id), title=str(title)))
    return subtasks


def build_recurring_info(row: dict[str, Any]) -> RecurringInfo:
    weekdays = [WEEKDAY_NAMES[field] for field in WEEKDAY_FIELDS if row.get(field)]
    return RecurringInfo(
        id=row["id"],
        title=row["title"],
        frequency=RECURRING_TYPE_TO_FREQUENCY.get(int(row.get("recurring_type") or 0), "unknown"),
        interval=int(row.get("interval") or 1),
        start_day=row.get("start_day"),
        end_day=row.get("end_day"),
        start_time=row.get("start_time"),
        duration=row.get("duration"),
        is_all_day=bool(row.get("is_all_day")),
        note=row.get("note") or "",
        color=row.get("color"),
        symbol=row.get("symbol"),
        modified_at=row.get("modified_at") or None,
        weekdays=weekdays,
        subtasks=build_subtasks(row.get("subtasks")),
        metadata=dict(row.get("metadata") or {}),
    )


class StructuredBackend:
    COMMAND_TIMEOUT_SECONDS = 12
    MONTH_NAME_PATTERN = (
        "January|February|March|April|May|June|July|August|September|October|November|December"
    )

    def __init__(
        self,
        *,
        session: str = DEFAULT_SESSION,
        profile: str | Path = DEFAULT_PROFILE,
        agent_browser: str | None = None,
    ) -> None:
        self.session = session
        self.profile = str(profile)
        self.agent_browser = agent_browser or os.environ.get(
            "CLI_ANYTHING_STRUCTURED_AGENT_BROWSER",
            "agent-browser",
        )

    def launch_login(self) -> dict[str, Any]:
        self.close_browser(ignore_errors=True)
        command = self._command(include_profile=True, headed=True) + ["open", APP_URL]
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {
            "launched": True,
            "session": self.session,
            "profile": self.profile,
            "url": APP_URL,
        }

    def close_browser(self, *, ignore_errors: bool = False) -> None:
        try:
            self._run(["close"], include_profile=False)
        except StructuredBackendError:
            if not ignore_errors:
                raise

    def session_status(self) -> dict[str, Any]:
        url = self._run(["get", "url"], include_profile=False).strip()
        title = self._run(["get", "title"], include_profile=False).strip()
        browser_meta = self.browser_today()
        settings = self.settings_show()
        main_view_state = self._ui_state()
        return {
            "session": self.session,
            "profile": self.profile,
            "url": url,
            "title": title,
            "browser_day": browser_meta["day"],
            "browser_timezone": browser_meta["timezone"],
            "logged_in": bool(main_view_state["has_inbox_input"]),
            "has_task_drawer": bool(main_view_state["has_task_drawer"]),
            "settings": settings.to_dict(),
        }

    def browser_today(self) -> dict[str, str]:
        script = """
        (() => {
          const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
          const parts = new Intl.DateTimeFormat("en-CA", {
            timeZone: tz,
            year: "numeric",
            month: "2-digit",
            day: "2-digit"
          }).formatToParts(new Date());
          const get = kind => parts.find(part => part.type === kind).value;
          return JSON.stringify({
            timezone: tz,
            day: `${get("year")}-${get("month")}-${get("day")}`
          });
        })()
        """
        return self._eval_json(script)

    def settings_show(self) -> SettingsInfo:
        script = """
        (async () => {
          const request = indexedDB.open("rxdb-dexie-structured-web-app-db-v8--7--settings");
          return await new Promise((resolve, reject) => {
            request.onerror = () => reject(request.error?.message || "settings open failed");
            request.onsuccess = () => {
              const db = request.result;
              const store = db.transaction("docs", "readonly").objectStore("docs");
              const getAll = store.getAll();
              getAll.onerror = () => reject(getAll.error?.message || "settings read failed");
              getAll.onsuccess = () => {
                const row = getAll.result[0] || null;
                const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
                resolve(JSON.stringify({ row, timezone }));
                db.close();
              };
            };
          });
        })()
        """
        payload = self._eval_json(script)
        row = payload["row"]
        return SettingsInfo(
            user_id=row["user_id"],
            theme=row["theme"],
            layout=row["layout"],
            first_weekday=row.get("first_weekday"),
            did_complete_onboarding=bool(row.get("did_complete_onboarding")),
            cloud_terms_date=row.get("cloud_terms_date"),
            timezone=payload.get("timezone"),
            duration_presets=list(row.get("duration_presets") or []),
        )

    def inbox_list(self) -> list[InboxTask]:
        script = """
        (async () => {
          const request = indexedDB.open("rxdb-dexie-structured-web-app-db-v8--4--task");
          return await new Promise((resolve, reject) => {
            request.onerror = () => reject(request.error?.message || "task open failed");
            request.onsuccess = () => {
              const db = request.result;
              const store = db.transaction("docs", "readonly").objectStore("docs");
              const getAll = store.getAll();
              getAll.onerror = () => reject(getAll.error?.message || "task read failed");
              getAll.onsuccess = () => {
                const rows = getAll.result
                  .filter(row => row.is_in_inbox && row._deleted !== "1")
                  .map(row => ({
                    id: row.id,
                    title: row.title,
                    completed_at: row.completed_at || null,
                    modified_at: row.modified_at || null
                  }));
                resolve(JSON.stringify(rows));
                db.close();
              };
            };
          });
        })()
        """
        self._ensure_main_view()
        rows = self._eval_json(script)
        tasks = [InboxTask(**row) for row in rows]
        tasks.sort(key=lambda item: (item.is_completed, item.title.lower()))
        return tasks

    def task_list(
        self,
        *,
        query: str | None = None,
        day: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        status: str = "open",
        location: str = "all",
        all_day: str = "all",
        color: str | None = None,
        symbol: str | None = None,
        include_hidden: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskInfo]:
        rows = self._read_task_rows()
        filtered = self._filter_task_rows(
            rows,
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
        )
        tasks = [build_task_info(row) for row in filtered]
        tasks.sort(key=self._task_sort_key)
        start = max(offset, 0)
        stop = None if limit <= 0 else start + limit
        return tasks[start:stop]

    def recurring_list(
        self,
        *,
        query: str | None = None,
        frequency: str | None = None,
        active_on: str | None = None,
        include_ended: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RecurringInfo]:
        rows = self._read_recurring_rows()
        filtered = self._filter_recurring_rows(
            rows,
            query=query,
            frequency=frequency,
            active_on=active_on,
            include_ended=include_ended,
        )
        recurring = [build_recurring_info(row) for row in filtered]
        recurring.sort(key=self._recurring_sort_key)
        start = max(offset, 0)
        stop = None if limit <= 0 else start + limit
        return recurring[start:stop]

    def task_show(self, reference: str) -> TaskInfo:
        row = self._resolve_task_row(reference)
        return build_task_info(row)

    def recurring_show(self, reference: str) -> RecurringInfo:
        row = self._resolve_recurring_row(reference)
        return build_recurring_info(row)

    def recurring_create(
        self,
        *,
        title: str,
        frequency: str,
        start_day: str | None = None,
        start: str | None = None,
        end: str | None = None,
        duration: int | None = None,
        note: str | None = None,
        all_day: bool = False,
        interval: int = 1,
        weekdays: list[str] | None = None,
        end_day: str | None = None,
    ) -> RecurringInfo:
        if frequency not in {"daily", "weekly", "monthly"}:
            raise StructuredBackendError(f"Unsupported recurring frequency: {frequency!r}")
        if interval < 1:
            raise StructuredBackendError("Recurring interval must be at least 1")

        before_ids = {row["id"] for row in self._read_recurring_rows()}
        self._ensure_main_view()
        self._open_task_create_panel()
        self._set_controlled_value('textarea[placeholder="Structure Your Day"]', title)

        effective_start_day = start_day or self.browser_today()["day"]
        if start_day is not None:
            self._open_task_date_picker()
            self._set_task_date(start_day)

        if note is not None:
            self._set_auxiliary_task_textarea(note)

        if all_day:
            self._set_task_all_day_control(True)

        self._open_repeat_panel()
        self._apply_repeat_settings(
            frequency=frequency,
            interval=interval,
            current_interval=1,
            start_day=start_day,
            current_start_day=self.browser_today()["day"],
            weekdays=weekdays,
            current_weekdays=[datetime.strptime(effective_start_day, "%Y-%m-%d").strftime("%a")] if frequency == "weekly" else [],
            end_day=end_day,
            current_end_day=None,
        )
        self._close_repeat_panel_if_open()
        if not all_day and (start is not None or end is not None or duration is not None):
            self._open_task_time_picker()
            start_minutes, end_minutes = self._resolve_task_time_window(
                day=effective_start_day,
                start=start,
                end=end,
                duration=duration,
            )
            self._set_task_time_inputs(start_minutes=start_minutes, end_minutes=end_minutes)
        self._click_button_by_text("Create Task")
        self._wait(1200)

        after = self._read_recurring_rows()
        created = [row for row in after if row["id"] not in before_ids]
        if len(created) != 1:
            raise StructuredBackendError("Structured recurring create flow did not create exactly one recurring task")
        return build_recurring_info(created[0])

    def recurring_update(
        self,
        reference: str,
        *,
        new_title: str | None = None,
        frequency: str | None = None,
        start_day: str | None = None,
        start: str | None = None,
        end: str | None = None,
        duration: int | None = None,
        note: str | None = None,
        all_day: bool | None = None,
        interval: int | None = None,
        weekdays: list[str] | None = None,
        end_day: str | None = None,
        clear_end_day: bool = False,
    ) -> RecurringInfo:
        row = self._resolve_recurring_row(reference)
        recurring = build_recurring_info(row)
        self._open_recurring_drawer(row)
        expected_titles = {recurring.title}
        self._assert_task_drawer_title(expected_titles, action="opening recurring update drawer")

        if new_title is not None:
            self._set_controlled_value('textarea[placeholder="Structure Your Day"]', new_title)
            expected_titles.add(new_title)
            self._assert_task_drawer_title(expected_titles, action="editing recurring title")

        if all_day is not None:
            self._set_task_all_day_control(all_day)
            self._assert_task_drawer_title(expected_titles, action="toggling recurring all-day state")

        effective_start_day = start_day or recurring.start_day

        if note is not None:
            self._set_auxiliary_task_textarea(note)
            self._assert_task_drawer_title(expected_titles, action="editing recurring note")

        repeat_changes_requested = any(
            value is not None
            for value in (frequency, interval, start_day, weekdays, end_day)
        ) or clear_end_day
        if (start is not None or end is not None or duration is not None) and not all_day:
            self._open_task_time_picker()
            self._assert_task_drawer_title(expected_titles, action="opening recurring time picker")
            start_minutes, end_minutes = self._resolve_task_time_window(
                day=effective_start_day,
                start=start,
                end=end,
                duration=duration,
            )
            self._set_task_time_inputs(start_minutes=start_minutes, end_minutes=end_minutes)
            self._assert_task_drawer_title(expected_titles, action="editing recurring time window")
        if repeat_changes_requested:
            self._open_repeat_panel(frequency_hint=recurring.frequency)
            self._assert_task_drawer_title(expected_titles, action="opening recurring repeat panel")
            self._apply_repeat_settings(
                frequency=frequency or recurring.frequency,
                interval=interval or recurring.interval,
                current_interval=recurring.interval,
                start_day=start_day,
                current_start_day=recurring.start_day,
                weekdays=weekdays,
                current_weekdays=recurring.weekdays,
                end_day=None if clear_end_day else end_day,
                current_end_day=recurring.end_day,
            )
            self._assert_task_drawer_title(expected_titles, action="editing recurring repeat settings")

        self._assert_task_drawer_title(expected_titles, action="submitting recurring update")
        self._click_button_by_text("Update Task")
        self._wait(250)
        if not self._confirm_repeating_task_scope(action="update", scope="all"):
            occurrence_dialog = self._occurrence_only_update_dialog_text()
            if occurrence_dialog is not None:
                if self._button_exists("Cancel"):
                    self._click_button_by_text("Cancel")
                    self._wait(250)
                raise StructuredBackendError(
                    "Structured routed this edit to an occurrence-only confirmation dialog instead of the "
                    "series update dialog. Recurring rule edits currently land on a detached occurrence from "
                    "this drawer, so the harness refused to pretend the recurring series was updated."
                )
        self._wait(1200)
        updated = build_recurring_info(self._resolve_recurring_row(row["id"]))
        self._assert_recurring_update_applied(
            original=recurring,
            updated=updated,
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
            clear_end_day=clear_end_day,
            effective_start_day=effective_start_day,
        )
        self._close_task_drawer_if_open()
        return updated

    def recurring_delete(self, reference: str, *, scope: str = "all") -> dict[str, Any]:
        row = self._resolve_recurring_row(reference)
        try:
            target_day = self._occurrence_day_for_recurring(row)
        except StructuredBackendError as exc:
            if scope == "all":
                raise StructuredBackendError(
                    "Structured has no visible occurrence left for this recurring task, so the current UI offers "
                    "no real drawer entry point for series deletion. The harness refused to approximate cleanup "
                    "with a direct local database mutation."
                ) from exc
            raise
        self._open_recurring_drawer(row)
        self._click_task_delete_button()
        self._wait(300)
        self._confirm_repeating_task_scope(action="delete", scope=scope, required=True)
        return self._wait_for_recurring_delete_outcome(
            row=row,
            scope=scope,
            reference=reference,
            target_day=target_day,
        )

    def task_create(
        self,
        *,
        title: str,
        day: str | None = None,
        start: str | None = None,
        end: str | None = None,
        duration: int | None = None,
        note: str | None = None,
    ) -> TaskInfo:
        self._ensure_main_view()
        self._open_task_create_panel()
        self._set_controlled_value('textarea[placeholder="Structure Your Day"]', title)

        if day is not None:
            self._open_task_date_picker()
            self._set_task_date(day)

        if start is not None or end is not None or duration is not None:
            self._open_task_time_picker()
            start_minutes, end_minutes = self._resolve_task_time_window(
                day=day,
                start=start,
                end=end,
                duration=duration,
            )
            self._set_task_time_inputs(start_minutes=start_minutes, end_minutes=end_minutes)

        if note is not None:
            self._set_auxiliary_task_textarea(note)

        self._click_button_by_text("Create Task")
        self._wait(1200)
        return self._expect_unique_task(title)

    def task_update(
        self,
        reference: str,
        *,
        new_title: str | None = None,
        day: str | None = None,
        start: str | None = None,
        end: str | None = None,
        duration: int | None = None,
        note: str | None = None,
        all_day: bool | None = None,
    ) -> TaskInfo:
        task = self._expect_unique_task(reference)
        self._open_task_drawer(task.title, task=task)

        if new_title is not None:
            self._set_controlled_value('textarea[placeholder="Structure Your Day"]', new_title)

        if all_day is not None:
            self._set_task_all_day_control(all_day)

        if day is not None:
            self._open_task_date_picker()
            self._set_task_date(day)

        if (start is not None or end is not None or duration is not None) and not all_day:
            self._open_task_time_picker()
            start_minutes, end_minutes = self._resolve_task_time_window(
                day=day or task.day,
                start=start,
                end=end,
                duration=duration,
            )
            self._set_task_time_inputs(start_minutes=start_minutes, end_minutes=end_minutes)

        if note is not None:
            self._set_auxiliary_task_textarea(note)

        self._click_button_by_text("Update Task")
        self._wait(1200)
        updated = self._expect_unique_task(new_title or reference)
        self._close_task_drawer_if_open()
        return updated

    def task_note_get(self, reference: str) -> str:
        return self._expect_unique_task(reference).note or ""

    def task_note_set(self, reference: str, note: str) -> TaskInfo:
        return self.task_update(reference, note=note)

    def task_note_clear(self, reference: str) -> TaskInfo:
        return self.task_update(reference, note="")

    def task_set_all_day(self, reference: str, enabled: bool) -> TaskInfo:
        return self.task_update(reference, all_day=enabled)

    def task_subtask_list(self, reference: str) -> list[SubtaskInfo]:
        return self._expect_unique_task(reference).subtasks

    def task_subtask_add(self, reference: str, title: str) -> TaskInfo:
        task = self._expect_unique_task(reference)
        self._open_task_drawer(task.title, task=task)
        self._set_controlled_value('input[placeholder="Add Subtask"]', title)
        self._run(["press", "Enter"])
        self._wait(250)
        self._click_button_by_text("Update Task")
        self._wait(1200)
        updated = self._expect_unique_task(reference)
        if not any(subtask.title == title for subtask in updated.subtasks):
            raise StructuredBackendError(f"Structured did not add subtask {title!r}")
        self._close_task_drawer_if_open()
        return updated

    def task_complete(self, reference: str) -> TaskInfo:
        task = self._expect_unique_task(reference)
        if task.is_completed:
            return task
        self._open_task_drawer(task.title, task=task)
        self._click_task_completion_toggle()
        self._wait(900)
        updated = self._expect_unique_task(reference)
        if not updated.is_completed:
            raise StructuredBackendError(f"Structured did not mark task {reference!r} as completed")
        self._close_task_drawer_if_open()
        return updated

    def task_restore(self, reference: str) -> TaskInfo:
        task = self._expect_unique_task(reference)
        if not task.is_completed:
            return task
        self._open_task_drawer(task.title, task=task)
        self._click_task_completion_toggle()
        self._wait(900)
        updated = self._expect_unique_task(reference)
        if updated.is_completed:
            raise StructuredBackendError(f"Structured did not restore task {reference!r} to open state")
        self._close_task_drawer_if_open()
        return updated

    def task_duplicate(self, reference: str) -> TaskInfo:
        task = self._expect_unique_task(reference)
        before = {row["id"] for row in self._read_task_rows()}
        self._open_task_drawer(task.title, task=task)
        self._click_task_more_action("Duplicate")
        self._wait(1200)
        after = self._read_task_rows()
        created = [row for row in after if row["id"] not in before]
        if len(created) != 1:
            raise StructuredBackendError("Structured duplicate flow did not create exactly one new task")
        self._close_task_drawer_if_open()
        return build_task_info(created[0])

    def task_move_to_inbox(self, reference: str) -> TaskInfo:
        task = self._expect_unique_task(reference)
        self._open_task_drawer(task.title, task=task)
        self._click_task_more_action("Move to Inbox")
        self._wait(1200)
        updated = self._expect_unique_task(reference)
        if not updated.is_in_inbox:
            raise StructuredBackendError(f"Structured did not move task {reference!r} to inbox")
        self._close_task_drawer_if_open()
        return updated

    def task_move_out_of_inbox(
        self,
        reference: str,
        *,
        day: str,
        start: str | None = None,
        end: str | None = None,
        duration: int | None = None,
        all_day: bool = False,
    ) -> TaskInfo:
        updated = self.task_update(
            reference,
            day=day,
            start=start,
            end=end,
            duration=duration,
            all_day=all_day,
        )
        if updated.is_in_inbox:
            raise StructuredBackendError(f"Structured did not move inbox task {reference!r} into the schedule")
        return updated

    def task_delete(self, reference: str) -> dict[str, Any]:
        task = self._expect_unique_task(reference)
        self._open_task_drawer(task.title, task=task)
        self._click_task_delete_button()
        self._wait(300)
        self._click_button_by_text("Confirm")
        self._wait(1200)
        try:
            self._expect_unique_task(reference)
        except StructuredNotFoundError:
            return {"deleted": True, "reference": reference}
        raise StructuredBackendError(f"Structured still reports task {reference!r} after delete")

    def inbox_add(self, title: str) -> InboxTask:
        self._ensure_main_view()
        self._ensure_inbox_drawer_accessible()
        self._set_controlled_value('input[placeholder="Add a new inbox task..."]', title)
        self._run(["click", 'button[aria-label="Add"]'])
        self._wait(900)
        try:
            return self._expect_unique_inbox_task(title)
        except StructuredNotFoundError as exc:
            raise StructuredBackendError(
                "Structured did not surface the new inbox task after the real inbox add flow."
            ) from exc

    def inbox_update(self, old_title: str, new_title: str) -> InboxTask:
        self._ensure_unique_inbox_title(old_title)
        self._open_inbox_task(old_title)
        self._set_controlled_value('textarea[placeholder="Structure Your Day"]', new_title)
        self._click_button_by_text("Update Task")
        self._wait(900)
        self._close_task_drawer_if_open()
        return self._expect_unique_inbox_task(new_title)

    def inbox_delete(self, title: str) -> dict[str, Any]:
        self._ensure_unique_inbox_title(title)
        self._open_inbox_task(title)
        self._click_task_delete_button()
        self._wait(300)
        self._click_button_by_text("Confirm")
        self._wait(1200)
        try:
            self._expect_unique_inbox_task(title)
        except StructuredNotFoundError:
            return {"deleted": True, "title": title}
        raise StructuredBackendError(f"Structured still reports inbox task {title!r} after delete")

    def agenda_list(self, *, day: str | None = None) -> list[AgendaItem]:
        if day is None:
            day = self.browser_today()["day"]
        self._ensure_main_view()
        payload = self._eval_json(
            f"""
            (async () => {{
              return await new Promise((resolve, reject) => {{
                const targetDay = {json.dumps(day)};
                const readDocs = dbName => new Promise((resolveDocs, rejectDocs) => {{
                  const request = indexedDB.open(dbName);
                  request.onerror = () => rejectDocs(request.error?.message || `open failed: ${{dbName}}`);
                  request.onsuccess = () => {{
                    const db = request.result;
                    const store = db.transaction("docs", "readonly").objectStore("docs");
                    const getAll = store.getAll();
                    getAll.onerror = () => rejectDocs(getAll.error?.message || `read failed: ${{dbName}}`);
                    getAll.onsuccess = () => {{
                      resolveDocs(getAll.result);
                      db.close();
                    }};
                  }};
                }});

                Promise.all([
                  readDocs("rxdb-dexie-structured-web-app-db-v8--4--task"),
                  readDocs("rxdb-dexie-structured-web-app-db-v8--4--recurring"),
                  readDocs("rxdb-dexie-structured-web-app-db-v8--2--recurring_occurrence")
                ]).then(([tasks, recurring, occurrences]) => {{
                  const dayTasks = tasks.filter(row =>
                    row._deleted !== "1" &&
                    !row.is_in_inbox &&
                    !row.is_hidden &&
                    row.day === targetDay
                  );
                  const dayOccurrences = occurrences.filter(row =>
                    row._deleted !== "1" &&
                    row.day === targetDay
                  );
                  const neededRecurringIds = [...new Set(dayOccurrences.map(row => row.recurring))];
                  const recurringRows = recurring.filter(row =>
                    row._deleted !== "1" &&
                    neededRecurringIds.includes(row.id)
                  );

                  resolve(JSON.stringify({{
                    day: targetDay,
                    tasks: dayTasks,
                    occurrences: dayOccurrences,
                    recurring: recurringRows
                  }}));
                }}).catch(reject);
              }});
            }})()
            """
        )
        recurring_map = {row["id"]: row for row in payload["recurring"]}
        return build_agenda_items(
            day=payload["day"],
            tasks=payload["tasks"],
            occurrences=payload["occurrences"],
            recurring_map=recurring_map,
        )

    def _ensure_main_view(self) -> None:
        state = self._ui_state()
        if state["has_confirm_dialog"]:
            self._click_button_by_text("Cancel")
            self._wait(300)
            state = self._ui_state()
        if state["has_task_drawer"]:
            self._close_task_drawer_if_open()
            self._wait(300)
            state = self._ui_state()
        if not state["has_inbox_input"] and self._button_exists("Got It"):
            self._click_button_by_text("Got It")
            self._wait(600)
            state = self._ui_state()
        if not state["has_inbox_input"] and self._button_exists("Start Planning"):
            self._click_button_by_text("Start Planning")
            self._wait(800)
            state = self._ui_state()
        if not state["has_inbox_input"]:
            self._run(["open", APP_URL], include_profile=True)
            self._wait(1200)
            state = self._ui_state()
        if not state["has_inbox_input"] and self._button_exists("Got It"):
            self._click_button_by_text("Got It")
            self._wait(600)
            state = self._ui_state()
        if not state["has_inbox_input"] and self._button_exists("Start Planning"):
            self._click_button_by_text("Start Planning")
            self._wait(800)
            state = self._ui_state()
        if not state["has_inbox_input"]:
            raise StructuredBackendError(
                "Structured main planner UI is not available. Log in again with `session login`."
            )

    def _ensure_inbox_drawer_accessible(self) -> None:
        self._run(
            [
                "eval",
                """
                (() => {
                  const drawer = document.querySelector(".MuiDrawer-paperAnchorDockedLeft");
                  if (!drawer) {
                    throw new Error("Inbox drawer not found");
                  }
                  drawer.style.transform = "none";
                  drawer.style.transition = "none";
                  drawer.style.visibility = "visible";
                  const rect = drawer.getBoundingClientRect();
                  return JSON.stringify({
                    x: rect.x,
                    y: rect.y,
                    width: rect.width,
                    height: rect.height,
                    visibility: window.getComputedStyle(drawer).visibility
                  });
                })()
                """,
            ]
        )

    def _open_task_create_panel(self) -> None:
        if self._button_exists("Create Task"):
            return
        self._run(
            [
                "eval",
                """
                (() => {
                  const button = [...document.querySelectorAll("button")].find(node =>
                    node.getAttribute("aria-label") === "add" &&
                    String(node.className || "").includes("MuiFab")
                  );
                  if (!button) {
                    throw new Error("Floating add button not found");
                  }
                  button.click();
                  return true;
                })()
                """,
            ]
        )
        self._wait(400)
        if not self._button_exists("Create Task"):
            raise StructuredBackendError("Structured did not open the task creation panel")

    def _open_task_date_picker(self) -> None:
        if self._task_time_picker_is_open():
            self._close_task_time_picker()
        self._run(
            [
                "eval",
                """
                (() => {
                  const target = [...document.querySelectorAll('button,[role="button"],div')].find(node => {
                    const testId = node.querySelector("svg[data-testid]")?.getAttribute("data-testid") || "";
                    const clickable = node.tagName === "BUTTON" ||
                      node.getAttribute("role") === "button" ||
                      window.getComputedStyle(node).cursor === "pointer";
                    return clickable && testId === "CalendarMonthIcon";
                  });
                  if (!target) {
                    throw new Error("Task date trigger not found");
                  }
                  target.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
                  return true;
                })()
                """,
            ]
        )
        self._wait(250)

    def _open_task_time_picker(self) -> None:
        if self._task_time_picker_is_open():
            return
        self._run(
            [
                "eval",
                """
                (() => {
                  const target = [...document.querySelectorAll('button,[role="button"],div')].find(node => {
                    const testId = node.querySelector("svg[data-testid]")?.getAttribute("data-testid") || "";
                    const clickable = node.tagName === "BUTTON" ||
                      node.getAttribute("role") === "button" ||
                      window.getComputedStyle(node).cursor === "pointer";
                    const isClockTrigger = testId === "WatchLaterIcon" || testId === "WatchLaterRoundedIcon";
                    return clickable && isClockTrigger;
                  });
                  if (!target) {
                    throw new Error("Task time trigger not found");
                  }
                  target.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
                  return true;
                })()
                """,
            ]
        )
        self._wait(250)

    def _close_task_time_picker(self) -> None:
        self._run(
            [
                "eval",
                """
                (() => {
                  const popover = [...document.querySelectorAll(".MuiPopover-paper")].find(node =>
                    node.querySelectorAll('input[placeholder="hh:mm aa"]').length >= 2
                  );
                  if (!popover) {
                    throw new Error("Task time picker popover not found");
                  }
                  const button = [...popover.querySelectorAll("button")].find(node => {
                    const svg = node.querySelector("svg[data-testid]");
                    return svg && svg.getAttribute("data-testid") === "CloseRoundedIcon";
                  });
                  if (!button) {
                    throw new Error("Task time picker close button not found");
                  }
                  button.click();
                  return true;
                })()
                """,
            ]
        )
        self._wait(250)

    def _task_time_picker_is_open(self) -> bool:
        script = """
        (() => JSON.stringify(document.querySelectorAll('input[placeholder="hh:mm aa"]').length >= 2))()
        """
        return bool(self._eval_json(script))

    def _close_task_drawer_if_open(self) -> None:
        state = self._ui_state()
        if state["has_task_drawer"]:
            for _ in range(2):
                self._click_task_drawer_close_button()
                self._wait(250)
                if not self._ui_state()["has_task_drawer"]:
                    return
            raise StructuredBackendError("Structured task drawer remained open after close attempts")

    def _click_task_drawer_close_button(self) -> None:
        self._run(
            [
                "eval",
                """
                (() => {
                  const visible = node => {
                    const rect = node.getBoundingClientRect();
                    const style = window.getComputedStyle(node);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                  };
                  const button = [...document.querySelectorAll('button')]
                    .filter(node => {
                      const svg = node.querySelector('svg[data-testid]');
                      if (!svg || svg.getAttribute('data-testid') !== 'CloseRoundedIcon' || !visible(node)) {
                        return false;
                      }
                      const rect = node.getBoundingClientRect();
                      return rect.x > window.innerWidth * 0.55 && rect.y < window.innerHeight * 0.2;
                    })
                    .sort((left, right) => {
                      const leftRect = left.getBoundingClientRect();
                      const rightRect = right.getBoundingClientRect();
                      if (leftRect.y !== rightRect.y) {
                        return leftRect.y - rightRect.y;
                      }
                      return rightRect.x - leftRect.x;
                    })[0];
                  if (!button) {
                    throw new Error('Task drawer close button not found');
                  }
                  button.click();
                  return true;
                })()
                """,
            ]
        )

    def _ui_state(self) -> dict[str, Any]:
        script = """
        (() => JSON.stringify({
          has_inbox_input: !!document.querySelector('input[placeholder="Add a new inbox task..."]'),
          has_task_drawer: !!document.querySelector('textarea[placeholder="Structure Your Day"]'),
          has_confirm_dialog: [...document.querySelectorAll("button")].some(
            button => (button.innerText || "").trim() === "Confirm"
          )
        }))()
        """
        return self._eval_json(script)

    def _ensure_unique_inbox_title(self, title: str) -> InboxTask:
        return self._expect_unique_inbox_task(title)

    def _read_docs(self, db_name: str, *, filter_deleted: bool = True) -> list[dict[str, Any]]:
        script = f"""
        (async () => {{
          const request = indexedDB.open({json.dumps(db_name)});
          return await new Promise((resolve, reject) => {{
            request.onerror = () => reject(request.error?.message || "open failed");
            request.onsuccess = () => {{
              const db = request.result;
              const store = db.transaction("docs", "readonly").objectStore("docs");
              const getAll = store.getAll();
              getAll.onerror = () => reject(getAll.error?.message || "read failed");
              getAll.onsuccess = () => {{
                const rows = getAll.result{'.filter(row => row._deleted !== "1")' if filter_deleted else ''};
                resolve(JSON.stringify(rows));
                db.close();
              }};
            }};
          }});
        }})()
        """
        return list(self._eval_json(script))

    def _read_task_rows(self) -> list[dict[str, Any]]:
        return self._read_docs(TASK_DB)

    def _read_recurring_rows(self) -> list[dict[str, Any]]:
        return self._read_docs(RECURRING_DB)

    def _read_occurrence_rows(self) -> list[dict[str, Any]]:
        return self._read_docs(RECURRING_OCCURRENCE_DB)

    def _task_sort_key(self, task: TaskInfo) -> tuple[Any, ...]:
        return (
            task.day or "9999-12-31",
            task.start_time is None,
            task.start_time or 0.0,
            task.title.lower(),
            task.id,
        )

    def _recurring_sort_key(self, recurring: RecurringInfo) -> tuple[Any, ...]:
        return (
            recurring.start_day or "9999-12-31",
            recurring.start_time is None,
            recurring.start_time or 0.0,
            recurring.title.lower(),
            recurring.id,
        )

    def _expect_unique_task(self, reference: str) -> TaskInfo:
        row = self._resolve_task_row(reference)
        return build_task_info(row)

    def _resolve_task_row(self, reference: str) -> dict[str, Any]:
        rows = self._read_task_rows()
        for row in rows:
            if row.get("id") == reference:
                return row
        matches = [row for row in rows if row.get("title") == reference]
        if not matches:
            raise StructuredNotFoundError(f"Task {reference!r} was not found")
        if len(matches) > 1:
            raise StructuredAmbiguousError(
                f"Task reference {reference!r} is ambiguous; use the task id instead"
            )
        return matches[0]

    def _resolve_recurring_row(self, reference: str) -> dict[str, Any]:
        rows = self._read_recurring_rows()
        for row in rows:
            if row.get("id") == reference:
                return row
        matches = [row for row in rows if row.get("title") == reference]
        if not matches:
            raise StructuredNotFoundError(f"Recurring task {reference!r} was not found")
        if len(matches) > 1:
            raise StructuredAmbiguousError(
                f"Recurring reference {reference!r} is ambiguous; use the recurring id instead"
            )
        return matches[0]

    def _expect_unique_inbox_task(self, title: str) -> InboxTask:
        matches = [task for task in self.inbox_list() if task.title == title]
        if not matches:
            raise StructuredNotFoundError(f"Inbox task {title!r} was not found")
        if len(matches) > 1:
            raise StructuredAmbiguousError(
                f"Inbox task title {title!r} is ambiguous; rename duplicates before using this command"
            )
        return matches[0]

    def _filter_task_rows(
        self,
        rows: list[dict[str, Any]],
        *,
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
    ) -> list[dict[str, Any]]:
        query_text = (query or "").strip().lower()
        filtered: list[dict[str, Any]] = []
        for row in rows:
            row_day = row.get("day")
            hidden = bool(row.get("is_hidden"))
            if hidden and not include_hidden:
                continue
            if day is not None and row_day != day:
                continue
            if date_from is not None and row_day and row_day < date_from:
                continue
            if date_to is not None and row_day and row_day > date_to:
                continue
            if status == "open" and row.get("completed_at"):
                continue
            if status == "completed" and not row.get("completed_at"):
                continue
            if location == "inbox" and not row.get("is_in_inbox"):
                continue
            if location == "scheduled" and row.get("is_in_inbox"):
                continue
            if all_day == "only" and not row.get("is_all_day"):
                continue
            if all_day == "exclude" and row.get("is_all_day"):
                continue
            if color is not None and row.get("color") != color:
                continue
            if symbol is not None and row.get("symbol") != symbol:
                continue
            if query_text:
                haystack = " ".join(
                    [
                        str(row.get("title") or ""),
                        str(row.get("note") or ""),
                        " ".join(str(subtask.get("title") or "") for subtask in row.get("subtasks") or [] if isinstance(subtask, dict)),
                    ]
                ).lower()
                if query_text not in haystack:
                    continue
            filtered.append(row)
        return filtered

    def _filter_recurring_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        query: str | None,
        frequency: str | None,
        active_on: str | None,
        include_ended: bool,
    ) -> list[dict[str, Any]]:
        query_text = (query or "").strip().lower()
        target_day = date_cls.fromisoformat(active_on) if active_on else None
        filtered: list[dict[str, Any]] = []
        for row in rows:
            if not include_ended and row.get("end_day") and row["end_day"] < self.browser_today()["day"]:
                continue
            if frequency is not None and RECURRING_TYPE_TO_FREQUENCY.get(int(row.get("recurring_type") or 0)) != frequency:
                continue
            if target_day is not None and not self._recurring_matches_day(row, target_day):
                continue
            if query_text:
                haystack = " ".join(
                    [
                        str(row.get("title") or ""),
                        str(row.get("note") or ""),
                        " ".join(str(subtask.get("title") or "") for subtask in row.get("subtasks") or [] if isinstance(subtask, dict)),
                    ]
                ).lower()
                if query_text not in haystack:
                    continue
            filtered.append(row)
        return filtered

    def _open_inbox_task(self, title: str) -> None:
        self._ensure_inbox_drawer_accessible()
        script = f"""
        (() => {{
          const target = {json.dumps(title)};
          const root = [...document.querySelectorAll('div[role="button"]')].find(node =>
            [...node.querySelectorAll('h6')].some(heading => (heading.textContent || '').trim() === target)
          );
          if (!root) {{
            throw new Error(`Inbox card not found: ${{target}}`);
          }}
          const clickable = root.firstElementChild;
          if (!clickable) {{
            throw new Error(`Inbox card body not found: ${{target}}`);
          }}
          clickable.dispatchEvent(new MouseEvent("pointerdown", {{ bubbles: true, cancelable: true, view: window }}));
          clickable.dispatchEvent(new MouseEvent("mousedown", {{ bubbles: true, cancelable: true, view: window }}));
          clickable.dispatchEvent(new MouseEvent("mouseup", {{ bubbles: true, cancelable: true, view: window }}));
          clickable.dispatchEvent(new MouseEvent("click", {{ bubbles: true, cancelable: true, view: window }}));
          return JSON.stringify({{
            clicked: true,
            title: target
          }});
        }})()
        """
        self._run(["eval", script])
        self._wait(500)
        active_title = self._current_task_drawer_title()
        if active_title != title:
            raise StructuredBackendError(
                f"Structured opened {active_title!r} instead of the requested inbox task {title!r}."
            )

    def _recurring_matches_day(self, row: dict[str, Any], target_day: date_cls) -> bool:
        start_day = row.get("start_day")
        if not start_day:
            return False
        start = date_cls.fromisoformat(start_day)
        if target_day < start:
            return False
        end_day = row.get("end_day")
        if end_day and target_day > date_cls.fromisoformat(end_day):
            return False
        recurring_type = RECURRING_TYPE_TO_FREQUENCY.get(int(row.get("recurring_type") or 0))
        interval = max(int(row.get("interval") or 1), 1)
        if recurring_type == "daily":
            return (target_day - start).days % interval == 0
        if recurring_type == "weekly":
            if not row.get(WEEKDAY_FIELDS[target_day.weekday()]):
                return False
            return ((target_day - start).days // 7) % interval == 0
        if recurring_type == "monthly":
            month_delta = (target_day.year - start.year) * 12 + (target_day.month - start.month)
            return target_day.day == start.day and month_delta % interval == 0
        return False

    def _occurrence_day_for_recurring(self, row: dict[str, Any]) -> str:
        start_day = row.get("start_day")
        if not start_day:
            raise StructuredBackendError(f"Recurring task {row.get('id')!r} is missing start_day")
        start = date_cls.fromisoformat(start_day)
        end = date_cls.fromisoformat(row["end_day"]) if row.get("end_day") else None
        today = date_cls.fromisoformat(self.browser_today()["day"])

        if end is not None and end < today:
            day = self._search_recurring_occurrence_day(row, anchor=end, forward=False)
        else:
            anchor = max(today, start)
            day = self._search_recurring_occurrence_day(row, anchor=anchor, forward=True)
        if day is None:
            raise StructuredBackendError(f"Could not find a visible occurrence day for recurring task {row.get('title')!r}")
        return day.isoformat()

    def _search_recurring_occurrence_day(
        self,
        row: dict[str, Any],
        *,
        anchor: date_cls,
        forward: bool,
        max_days: int = 730,
    ) -> date_cls | None:
        start = date_cls.fromisoformat(row["start_day"])
        end = date_cls.fromisoformat(row["end_day"]) if row.get("end_day") else None
        detached_days = {
            occurrence.get("day")
            for occurrence in self._read_occurrence_rows()
            if occurrence.get("_deleted") != "1"
            and occurrence.get("recurring") == row.get("id")
            and occurrence.get("is_detached")
            and occurrence.get("day")
        }
        step = 1 if forward else -1
        for delta in range(max_days + 1):
            candidate = anchor + timedelta(days=delta * step)
            if candidate < start:
                break
            if end is not None and candidate > end:
                if forward:
                    break
                continue
            if candidate.isoformat() in detached_days:
                continue
            if self._recurring_matches_day(row, candidate):
                return candidate
        return None

    def _has_active_occurrence_for_recurring_day(self, recurring_id: str, day: str) -> bool:
        return any(
            occurrence.get("_deleted") != "1"
            and occurrence.get("recurring") == recurring_id
            and occurrence.get("day") == day
            and not occurrence.get("is_detached")
            for occurrence in self._read_occurrence_rows()
        )

    def _wait_for_recurring_delete_outcome(
        self,
        *,
        row: dict[str, Any],
        scope: str,
        reference: str,
        target_day: str,
        attempts: int = 8,
        delay_ms: int = 300,
    ) -> dict[str, Any]:
        target_date = date_cls.fromisoformat(target_day)
        for attempt in range(attempts):
            updated_row: dict[str, Any] | None
            try:
                updated_row = self._resolve_recurring_row(row["id"])
            except StructuredNotFoundError:
                updated_row = None

            if scope == "all":
                if updated_row is None:
                    return {"deleted": True, "scope": scope, "reference": reference}
            elif scope == "one":
                if updated_row is None or not self._has_active_occurrence_for_recurring_day(row["id"], target_day):
                    payload: dict[str, Any] = {
                        "deleted": True,
                        "scope": scope,
                        "reference": reference,
                    }
                    if updated_row is not None:
                        payload["recurring"] = build_recurring_info(updated_row).to_dict()
                    return payload
            elif scope == "future":
                if updated_row is None:
                    return {"deleted": True, "scope": scope, "reference": reference}
                next_day = self._search_recurring_occurrence_day(
                    updated_row,
                    anchor=target_date,
                    forward=True,
                )
                if next_day is None:
                    return {
                        "deleted": True,
                        "scope": scope,
                        "reference": reference,
                        "recurring": build_recurring_info(updated_row).to_dict(),
                    }
            else:
                raise StructuredBackendError(f"Unsupported recurring delete scope: {scope!r}")

            if attempt < attempts - 1:
                self._wait(delay_ms)

        if scope == "all":
            raise StructuredBackendError(f"Structured still reports recurring task {reference!r} after delete")
        if scope == "one":
            raise StructuredBackendError(
                f"Structured still shows an active occurrence of recurring task {reference!r} on {target_day} after delete"
            )
        next_day = self._search_recurring_occurrence_day(
            self._resolve_recurring_row(row["id"]),
            anchor=target_date,
            forward=True,
        )
        suffix = f"; next visible occurrence is {next_day.isoformat()}" if next_day is not None else ""
        raise StructuredBackendError(
            f"Structured still shows current or future occurrences for recurring task {reference!r} after delete{suffix}"
        )

    def _open_recurring_drawer(self, row: dict[str, Any]) -> None:
        recurring = build_recurring_info(row)
        target_day = self._occurrence_day_for_recurring(row)
        self._ensure_main_view()
        self._navigate_to_day(target_day)
        range_label = self._timeline_range_label(recurring.start_time, recurring.duration)
        for attempt in range(2):
            self._click_recurring_occurrence_row(recurring.title, range_label=range_label)
            self._wait(500)
            active_title = self._current_task_drawer_title()
            if active_title == recurring.title:
                return
            if active_title:
                self._close_task_drawer_if_open()
                self._wait(400)
                continue
            if attempt == 0:
                self._wait(300)
        active_title = self._current_task_drawer_title()
        raise StructuredBackendError(
            f"Structured opened {active_title!r} instead of the requested recurring task {recurring.title!r}."
        )

    def _click_recurring_occurrence_row(self, title: str, *, range_label: str | None) -> None:
        script = f"""
        (() => {{
          const target = {json.dumps(title)};
          const rangeLabel = {json.dumps(range_label)};
          const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
          const rows = [...document.querySelectorAll('li[role="button"]')]
            .filter(node => normalize(node.innerText).includes(target))
            .sort((left, right) => left.getBoundingClientRect().y - right.getBoundingClientRect().y);
          let row = null;
          if (rows.length === 1) {{
            row = rows[0];
          }} else if (rangeLabel) {{
            row = rows.find(node => normalize(node.innerText).includes(rangeLabel)) || null;
          }}
          if (!row) {{
            throw new Error(`Recurring occurrence row not found: ${{target}}`);
          }}
          row.click();
          row.dispatchEvent(new MouseEvent("pointerdown", {{ bubbles: true, cancelable: true, view: window }}));
          row.dispatchEvent(new MouseEvent("mousedown", {{ bubbles: true, cancelable: true, view: window }}));
          row.dispatchEvent(new MouseEvent("mouseup", {{ bubbles: true, cancelable: true, view: window }}));
          row.dispatchEvent(new MouseEvent("click", {{ bubbles: true, cancelable: true, view: window }}));
          return true;
        }})()
        """
        self._run(["eval", script])

    def _timeline_range_label(self, start_time: float | None, duration: int | None) -> str | None:
        if start_time is None or duration is None:
            return None
        start_minutes = round(start_time * 60)
        end_minutes = start_minutes + duration
        return f"{self._format_picker_time(start_minutes)} - {self._format_picker_time(end_minutes)}"

    def _open_repeat_panel(self, *, frequency_hint: str | None = None) -> None:
        script = f"""
        (() => {{
          const target = {json.dumps((frequency_hint or "").title())};
          const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
          const visible = node => {{
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          }};
          const clickNode = node => {{
            if (typeof node.click === 'function') {{
              node.click();
            }} else {{
              node.dispatchEvent(new MouseEvent("pointerdown", {{ bubbles: true, cancelable: true, view: window }}));
              node.dispatchEvent(new MouseEvent("mousedown", {{ bubbles: true, cancelable: true, view: window }}));
              node.dispatchEvent(new MouseEvent("mouseup", {{ bubbles: true, cancelable: true, view: window }}));
              node.dispatchEvent(new MouseEvent("click", {{ bubbles: true, cancelable: true, view: window }}));
            }}
          }};
          const titleInput = document.querySelector('textarea[placeholder="Structure Your Day"]');
          const drawerRoot = titleInput
            ? [titleInput, ...(() => {{
                const ancestors = [];
                let current = titleInput.parentElement;
                while (current) {{
                  ancestors.push(current);
                  current = current.parentElement;
                }}
                return ancestors;
              }})()].find(node => {{
                const rect = node.getBoundingClientRect();
                return rect.width > 320 && rect.height > 420 && rect.x > window.innerWidth * 0.35;
              }}) || document
            : document;
          const inDrawer = selector => [...drawerRoot.querySelectorAll(selector)];

          const explicit = inDrawer('button').find(node =>
            visible(node) && normalize(node.innerText) === 'Repeat'
          );
          if (explicit) {{
            clickNode(explicit);
            return true;
          }}

          const choices = ['Once', 'Daily', 'Weekly', 'Monthly'];
          const matches = inDrawer('button,[role="button"],div')
            .filter(node => visible(node) && choices.includes(normalize(node.innerText)) && node.getBoundingClientRect().x > 650);
          const filtered = target ? matches.filter(node => normalize(node.innerText) === target) : matches;
          const clickableMatches = filtered.filter(node => {{
            const rect = node.getBoundingClientRect();
            return node.tagName === 'BUTTON' ||
              node.getAttribute('role') === 'button' ||
              window.getComputedStyle(node).cursor === 'pointer' ||
              String(node.className || '').includes('cursor-pointer') ||
              rect.width < 430;
          }});
          const pool = (clickableMatches.length ? clickableMatches : filtered)
            .sort((left, right) => {{
              const leftRect = left.getBoundingClientRect();
              const rightRect = right.getBoundingClientRect();
              return (rightRect.width * rightRect.height) - (leftRect.width * leftRect.height);
            }});
          const frequencyNode = pool[0];
          if (!frequencyNode) {{
            throw new Error('Repeat trigger not found');
          }}
          clickNode(frequencyNode);
          return true;
        }})()
        """
        for attempt in range(2):
            self._run(["eval", script])
            self._wait(250 + attempt * 150)
            if self._repeat_panel_is_open():
                return
        raise StructuredBackendError("Structured did not open the repeat panel")

    def _repeat_panel_is_open(self) -> bool:
        script = r"""
        (() => {
          const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
          const visible = node => {
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const tabLabels = ['Once', 'Daily', 'Weekly', 'Monthly'];
          const panel = [...document.querySelectorAll('*')].find(node => {
            if (!visible(node)) {
              return false;
            }
            const rect = node.getBoundingClientRect();
            if (rect.x <= 650 || rect.width <= 180 || rect.height <= 80) {
              return false;
            }
            const tabs = [...node.querySelectorAll('button')]
              .filter(button => visible(button) && tabLabels.includes(normalize(button.innerText)));
            const closeButton = [...node.querySelectorAll('button')].find(button => {
              const svg = button.querySelector('svg[data-testid]');
              return visible(button) &&
                svg &&
                svg.getAttribute('data-testid') === 'CloseRoundedIcon';
            });
            const heading = [...node.querySelectorAll('*')].some(child =>
              visible(child) && normalize(child.textContent) === 'Repeat'
            );
            return Boolean(closeButton) && heading && tabs.length >= 2;
          });
          return JSON.stringify(!!panel);
        })()
        """
        return bool(self._eval_json(script))

    def _close_repeat_panel_if_open(self) -> None:
        if not self._repeat_panel_is_open():
            return
        script = r"""
        (() => {
          const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
          const visible = node => {
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const tabLabels = ['Once', 'Daily', 'Weekly', 'Monthly'];
          const panel = [...document.querySelectorAll('*')].find(node => {
            if (!visible(node)) {
              return false;
            }
            const rect = node.getBoundingClientRect();
            if (rect.x <= 650 || rect.width <= 180 || rect.height <= 80) {
              return false;
            }
            const tabs = [...node.querySelectorAll('button')]
              .filter(button => visible(button) && tabLabels.includes(normalize(button.innerText)));
            const closeButton = [...node.querySelectorAll('button')].find(button => {
              const svg = button.querySelector('svg[data-testid]');
              return visible(button) &&
                svg &&
                svg.getAttribute('data-testid') === 'CloseRoundedIcon';
            });
            const heading = [...node.querySelectorAll('*')].some(child =>
              visible(child) && normalize(child.textContent) === 'Repeat'
            );
            return Boolean(closeButton) && heading && tabs.length >= 2;
          });
          if (!panel) {
            return JSON.stringify(false);
          }
          const button = [...panel.querySelectorAll('button')].find(node => {
            const svg = node.querySelector('svg[data-testid]');
            return visible(node) &&
              svg &&
              svg.getAttribute('data-testid') === 'CloseRoundedIcon';
          });
          if (!button) {
            throw new Error('Repeat panel close button not found');
          }
          button.click();
          return JSON.stringify(true);
        })()
        """
        for attempt in range(2):
            self._run(["eval", script])
            self._wait(200 + attempt * 150)
            if not self._repeat_panel_is_open():
                return
        raise StructuredBackendError("Structured repeat panel remained open after close attempts")

    def _apply_repeat_settings(
        self,
        *,
        frequency: str,
        interval: int,
        current_interval: int,
        start_day: str | None,
        current_start_day: str | None,
        weekdays: list[str] | None,
        current_weekdays: list[str],
        end_day: str | None,
        current_end_day: str | None,
    ) -> None:
        self._click_repeat_button(frequency.title())
        actual_interval = self._current_repeat_interval() or current_interval
        self._adjust_repeat_interval(current=actual_interval, desired=interval)
        self._set_repeat_start_day(start_day=start_day, current_start_day=current_start_day)
        if frequency == "weekly" and weekdays is not None:
            current = self._current_repeat_weekdays() or set(current_weekdays)
            desired = set(weekdays)
            for day_name in WEEKDAY_NAMES.values():
                if day_name in desired and day_name not in current:
                    self._click_repeat_button(day_name)
            current = self._current_repeat_weekdays() or desired
            for day_name in WEEKDAY_NAMES.values():
                if day_name in current and day_name not in desired:
                    self._click_repeat_button(day_name)
        self._set_repeat_end_day(end_day=end_day, current_end_day=current_end_day)

    def _click_repeat_button(self, label: str) -> None:
        script = f"""
        (() => {{
          const target = {json.dumps(label)};
          const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
          const visible = node => {{
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          }};
          const tabLabels = ['Once', 'Daily', 'Weekly', 'Monthly'];
          const panel = [...document.querySelectorAll('*')].find(node => {{
            if (!visible(node)) {{
              return false;
            }}
            const rect = node.getBoundingClientRect();
            if (rect.x <= 650 || rect.width <= 180 || rect.height <= 80) {{
              return false;
            }}
            const tabs = [...node.querySelectorAll('button')]
              .filter(button => visible(button) && tabLabels.includes(normalize(button.innerText)));
            const closeButton = [...node.querySelectorAll('button')].find(button => {{
              const svg = button.querySelector('svg[data-testid]');
              return visible(button) &&
                svg &&
                svg.getAttribute('data-testid') === 'CloseRoundedIcon';
            }});
            const heading = [...node.querySelectorAll('*')].some(child =>
              visible(child) && normalize(child.textContent) === 'Repeat'
            );
            return Boolean(closeButton) && heading && tabs.length >= 2;
          }});
          const button = [...(panel || document).querySelectorAll('button')].find(node => {{
            return visible(node) && normalize(node.innerText) === target;
          }});
          if (!button) {{
            throw new Error(`Repeat button not found: ${{target}}`);
          }}
          button.click();
          return true;
        }})()
        """
        self._run(["eval", script])
        self._wait(120)

    def _current_repeat_interval(self) -> int | None:
        script = r"""
        (() => {
          const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
          const visible = node => {
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const tabLabels = ['Once', 'Daily', 'Weekly', 'Monthly'];
          const panel = [...document.querySelectorAll('*')].find(node => {
            if (!visible(node)) {
              return false;
            }
            const rect = node.getBoundingClientRect();
            if (rect.x <= 650 || rect.width <= 180 || rect.height <= 80) {
              return false;
            }
            const tabs = [...node.querySelectorAll('button')]
              .filter(button => visible(button) && tabLabels.includes(normalize(button.innerText)));
            const closeButton = [...node.querySelectorAll('button')].find(button => {
              const svg = button.querySelector('svg[data-testid]');
              return visible(button) &&
                svg &&
                svg.getAttribute('data-testid') === 'CloseRoundedIcon';
            });
            const heading = [...node.querySelectorAll('*')].some(child =>
              visible(child) && normalize(child.textContent) === 'Repeat'
            );
            return Boolean(closeButton) && heading && tabs.length >= 2;
          });
          const texts = [...(panel || document).querySelectorAll('*')]
            .map(node => normalize(node.textContent))
            .filter(Boolean);
          const match = texts
            .map(text => text.match(/^Every\s+(\d+)\s+(day|week|month)s?$/i))
            .find(Boolean);
          return JSON.stringify(match ? Number(match[1]) : null);
        })()
        """
        payload = self._eval_json(script)
        if payload in (None, "null"):
            return None
        return int(payload)

    def _current_repeat_weekdays(self) -> set[str]:
        script = """
        (() => {
          const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
          const visible = node => {
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
          const tabLabels = ['Once', 'Daily', 'Weekly', 'Monthly'];
          const panel = [...document.querySelectorAll('*')].find(node => {
            if (!visible(node)) {
              return false;
            }
            const rect = node.getBoundingClientRect();
            if (rect.x <= 650 || rect.width <= 180 || rect.height <= 80) {
              return false;
            }
            const tabs = [...node.querySelectorAll('button')]
              .filter(button => visible(button) && tabLabels.includes(normalize(button.innerText)));
            const closeButton = [...node.querySelectorAll('button')].find(button => {
              const svg = button.querySelector('svg[data-testid]');
              return visible(button) &&
                svg &&
                svg.getAttribute('data-testid') === 'CloseRoundedIcon';
            });
            const heading = [...node.querySelectorAll('*')].some(child =>
              visible(child) && normalize(child.textContent) === 'Repeat'
            );
            return Boolean(closeButton) && heading && tabs.length >= 2;
          }) || document;
          const selected = [...panel.querySelectorAll('button')]
            .map(node => {
              const text = (node.innerText || '').trim();
              const rect = node.getBoundingClientRect();
              if (!labels.includes(text) || !visible(node)) {
                return null;
              }
              const style = window.getComputedStyle(node);
              const selectedStyle = style.backgroundColor !== 'rgb(255, 255, 255)' &&
                style.backgroundColor !== 'rgba(0, 0, 0, 0)' &&
                style.color !== 'rgb(133, 133, 133)';
              return selectedStyle ? text : null;
            })
            .filter(Boolean);
          return JSON.stringify(selected);
        })()
        """
        return set(self._eval_json(script) or [])

    def _adjust_repeat_interval(self, *, current: int, desired: int) -> None:
        if desired < 1:
            raise StructuredBackendError("Recurring interval must be at least 1")
        delta = desired - current
        if delta == 0:
            return
        icon = "AddRoundedIcon" if delta > 0 else "RemoveRoundedIcon"
        for _ in range(abs(delta)):
            self._run(
                [
                    "eval",
                    f"""
                    (() => {{
                      const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
                      const visible = node => {{
                        const rect = node.getBoundingClientRect();
                        const style = window.getComputedStyle(node);
                        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                      }};
                      const tabLabels = ['Once', 'Daily', 'Weekly', 'Monthly'];
                      const panel = [...document.querySelectorAll('*')].find(node => {{
                        if (!visible(node)) {{
                          return false;
                        }}
                        const rect = node.getBoundingClientRect();
                        if (rect.x <= 650 || rect.width <= 180 || rect.height <= 80) {{
                          return false;
                        }}
                        const tabs = [...node.querySelectorAll('button')]
                          .filter(button => visible(button) && tabLabels.includes(normalize(button.innerText)));
                        const closeButton = [...node.querySelectorAll('button')].find(button => {{
                          const svg = button.querySelector('svg[data-testid]');
                          return visible(button) &&
                            svg &&
                            svg.getAttribute('data-testid') === 'CloseRoundedIcon';
                        }});
                        const heading = [...node.querySelectorAll('*')].some(child =>
                          visible(child) && normalize(child.textContent) === 'Repeat'
                        );
                        return Boolean(closeButton) && heading && tabs.length >= 2;
                      }});
                      const button = [...(panel || document).querySelectorAll("button")].find(node => {{
                        const svg = node.querySelector("svg[data-testid]");
                        const rect = node.getBoundingClientRect();
                        return svg &&
                          svg.getAttribute("data-testid") === {json.dumps(icon)} &&
                          visible(node) &&
                          rect.x > 650;
                      }});
                      if (!button) {{
                        throw new Error("Repeat interval button not found");
                      }}
                      button.click();
                      return true;
                    }})()
                    """,
                ]
            )
            self._wait(80)

    def _set_repeat_start_day(self, *, start_day: str | None, current_start_day: str | None) -> None:
        if start_day is None or start_day == current_start_day:
            return
        self._open_repeat_start_date_picker()
        display = datetime.strptime(start_day, "%Y-%m-%d").strftime("%d/%m/%Y")
        self._overwrite_text_input('input[placeholder="DD/MM/YYYY"]', display)
        self._run(["press", "Enter"])
        self._wait(250)
        self._close_date_picker_if_open()

    def _set_repeat_end_day(self, *, end_day: str | None, current_end_day: str | None) -> None:
        if end_day is None:
            if current_end_day is None:
                return
            script = """
            (() => {
              const node = [...document.querySelectorAll('*')].find(el =>
                (el.textContent || '').replace(/\\s+/g, ' ').trim() === 'Repeat indefinitely instead.'
              );
              if (!node) {
                throw new Error('Repeat indefinitely toggle not found');
              }
              node.click();
              return true;
            })()
            """
            self._run(["eval", script])
            self._wait(250)
            return

        if current_end_day is None:
            self._click_repeat_button("Set End Date")
            self._wait(150)
        self._open_repeat_end_date_picker()
        display = datetime.strptime(end_day, "%Y-%m-%d").strftime("%d/%m/%Y")
        self._overwrite_text_input('input[placeholder="DD/MM/YYYY"]', display)
        self._run(["press", "Enter"])
        self._wait(250)
        self._close_date_picker_if_open()

    def _repeat_end_date_picker_is_open(self) -> bool:
        script = """
        (() => JSON.stringify(!!document.querySelector('input[placeholder="DD/MM/YYYY"]')))()
        """
        return bool(self._eval_json(script))

    def _open_repeat_start_date_picker(self) -> None:
        self._open_repeat_date_picker("Start")

    def _open_repeat_end_date_picker(self) -> None:
        self._open_repeat_date_picker("Ends")

    def _open_repeat_date_picker(self, label: str) -> None:
        if self._repeat_end_date_picker_is_open():
            return
        script = """
        (() => {{
          const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
          const datePattern = /^\\d{{1,2}}\\. [A-Za-z]{{3}} \\d{{4}}$/;
          const visible = node => {{
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          }};
          const tabLabels = ['Once', 'Daily', 'Weekly', 'Monthly'];
          const panel = [...document.querySelectorAll('*')].find(node => {{
            if (!visible(node)) {{
              return false;
            }}
            const rect = node.getBoundingClientRect();
            if (rect.x <= 650 || rect.width <= 180 || rect.height <= 80) {{
              return false;
            }}
            const tabs = [...node.querySelectorAll('button')]
              .filter(button => visible(button) && tabLabels.includes(normalize(button.innerText)));
            const closeButton = [...node.querySelectorAll('button')].find(button => {{
              const svg = button.querySelector('svg[data-testid]');
              return visible(button) &&
                svg &&
                svg.getAttribute('data-testid') === 'CloseRoundedIcon';
            }});
            const heading = [...node.querySelectorAll('*')].some(child =>
              visible(child) && normalize(child.textContent) === 'Repeat'
            );
            return Boolean(closeButton) && heading && tabs.length >= 2;
          }}) || document;
          const row = [...panel.querySelectorAll('*')]
            .filter(el => {{
              const text = normalize(el.textContent);
              const rect = el.getBoundingClientRect();
              return text.startsWith({label_prefix}) &&
                datePattern.test(text.slice({slice_start})) &&
                rect.width > 120 &&
                rect.height > 24;
            }})
            .sort((left, right) => left.getBoundingClientRect().y - right.getBoundingClientRect().y)
            .at(0);
          if (!row) {{
            throw new Error({missing_message});
          }}
          const node = [row, ...row.querySelectorAll('*')].find(el => {{
            const text = normalize(el.textContent);
            const rect = el.getBoundingClientRect();
            return datePattern.test(text) &&
              rect.width > 0 &&
              rect.height > 0 &&
              window.getComputedStyle(el).cursor === 'pointer';
          }});
          if (!node) {{
            throw new Error('Repeat end date trigger not found');
          }}
          node.click();
          return true;
        }})()
        """.format(
            label_prefix=json.dumps(label + " "),
            slice_start=len(label) + 1,
            missing_message=json.dumps(f"Repeat {label.lower()} date row not found"),
        )
        for attempt in range(2):
            self._run(
                [
                    "eval",
                    script,
                ]
            )
            self._wait(150 + attempt * 150)
            if self._repeat_end_date_picker_is_open():
                return
        raise StructuredBackendError(f"Structured did not open the repeat {label.lower()} date picker")

    def _close_date_picker_if_open(self) -> None:
        if not self._repeat_end_date_picker_is_open():
            return
        self._run(
            [
                "eval",
                """
                (() => {
                  const visible = node => {
                    const rect = node.getBoundingClientRect();
                    const style = window.getComputedStyle(node);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                  };
                  const inputs = [...document.querySelectorAll('input[placeholder="DD/MM/YYYY"]')].filter(visible);
                  if (!inputs.length) {
                    return JSON.stringify(false);
                  }
                  const input = inputs.sort((left, right) => right.getBoundingClientRect().y - left.getBoundingClientRect().y)[0];
                  const inputRect = input.getBoundingClientRect();
                  const button = [...document.querySelectorAll('button')].find(node => {
                    const svg = node.querySelector('svg[data-testid]');
                    const rect = node.getBoundingClientRect();
                    return svg &&
                      svg.getAttribute('data-testid') === 'CloseRoundedIcon' &&
                      rect.y >= inputRect.y - 80 &&
                      rect.y <= inputRect.y + 10 &&
                      rect.x >= inputRect.x + inputRect.width - 48 &&
                      rect.x <= inputRect.x + inputRect.width + 96;
                  });
                  if (!button) {
                    throw new Error('Date picker close button not found');
                  }
                  button.click();
                  return JSON.stringify(true);
                })()
                """,
            ]
        )
        self._wait(150)

    def _open_task_drawer(self, title: str, *, task: TaskInfo | None = None) -> None:
        task = task or self._expect_unique_task(title)
        self._ensure_main_view()
        if task.is_in_inbox:
            self._open_inbox_task(title)
            return
        if not task.day:
            raise StructuredBackendError(f"Task {title!r} does not expose a day and cannot be navigated")
        self._navigate_to_day(task.day)
        script = f"""
        (() => {{
          const target = {json.dumps(title)};
          const label = document.querySelector(`[aria-label="${{CSS.escape(target)}}"]`);
          if (!label) {{
            throw new Error(`Scheduled task label not found: ${{target}}`);
          }}
          const row = label.closest('[role="button"]');
          if (!row) {{
            throw new Error(`Scheduled task row not found: ${{target}}`);
          }}
          const clickable = row.querySelector('div[style*="cursor: pointer"]') || label;
          clickable.dispatchEvent(new MouseEvent("pointerdown", {{ bubbles: true, cancelable: true, view: window }}));
          clickable.dispatchEvent(new MouseEvent("mousedown", {{ bubbles: true, cancelable: true, view: window }}));
          clickable.dispatchEvent(new MouseEvent("mouseup", {{ bubbles: true, cancelable: true, view: window }}));
          clickable.dispatchEvent(new MouseEvent("click", {{ bubbles: true, cancelable: true, view: window }}));
          return true;
        }})()
        """
        self._run(["eval", script])
        self._wait(500)
        active_title = self._current_task_drawer_title()
        if active_title != title and self._click_task_card_by_visible_text(title):
            self._wait(500)
            active_title = self._current_task_drawer_title()
        if active_title != title:
            raise StructuredBackendError(
                f"Structured opened {active_title!r} instead of the requested task {title!r}."
            )

    def _click_task_card_by_visible_text(self, title: str) -> bool:
        script = f"""
        (() => {{
          const target = {json.dumps(title)};
          const nodes = [...document.querySelectorAll('[role="button"],button')];
          const normalize = value => (value || '').replace(/\\s+/g, ' ').trim();
          const clickNode = node => {{
            const targetNode =
              node.querySelector('.cursor-pointer, [style*="cursor: pointer"]') ||
              node.firstElementChild ||
              node;
            if (typeof targetNode.click === 'function') {{
              targetNode.click();
              return;
            }}
            targetNode.dispatchEvent(new MouseEvent("pointerdown", {{ bubbles: true, cancelable: true, view: window }}));
            targetNode.dispatchEvent(new MouseEvent("mousedown", {{ bubbles: true, cancelable: true, view: window }}));
            targetNode.dispatchEvent(new MouseEvent("mouseup", {{ bubbles: true, cancelable: true, view: window }}));
            targetNode.dispatchEvent(new MouseEvent("click", {{ bubbles: true, cancelable: true, view: window }}));
          }};

          const exact = nodes.find(node => normalize(node.innerText) === target || normalize(node.getAttribute('aria-label')) === target);
          if (exact) {{
            clickNode(exact);
            return JSON.stringify({{ clicked: true, strategy: "exact" }});
          }}

          const truncatedMatches = nodes.filter(node => {{
            const text = normalize(node.innerText);
            return text.endsWith('...') && target.startsWith(text.slice(0, -3));
          }});
          if (truncatedMatches.length === 1) {{
            clickNode(truncatedMatches[0]);
            return JSON.stringify({{ clicked: true, strategy: "truncated-prefix", text: normalize(truncatedMatches[0].innerText) }});
          }}

          return JSON.stringify({{ clicked: false, matches: truncatedMatches.length }});
        }})()
        """
        payload = self._eval_json(script)
        return bool(payload.get("clicked"))

    def _navigate_to_day(self, day: str) -> None:
        target = date_cls.fromisoformat(day)
        state = self._top_strip_state()
        selected = date_cls.fromisoformat(state["selected_day"])
        max_steps = max(32, abs((target - selected).days) // 7 + 8)
        for _ in range(min(max_steps, 400)):
            selected = state["selected_day"]
            if selected == day:
                return
            if self._top_strip_contains(target):
                self._click_top_strip_day(target)
                self._wait(700)
                state = self._top_strip_state()
                if state["selected_day"] == day:
                    return
            direction = "next" if target > date_cls.fromisoformat(selected) else "prev"
            self._click_top_strip_arrow(direction)
            self._wait(700)
        raise StructuredBackendError(f"Could not navigate Structured planner to {day}")

    def _top_strip_state(self) -> dict[str, Any]:
        script = """
        (() => {
          const monthRegex = new RegExp(`(__MONTH_PATTERN__)\\\\s*\\\\d{4}`);
          const headerTexts = [...document.querySelectorAll("*")]
            .map(node => (node.textContent || "").replace(/\\s+/g, " ").trim())
            .filter(text => monthRegex.test(text))
            .slice(0, 32);
          const days = [...document.querySelectorAll("button")]
            .map(button => {
              const parts = [...button.querySelectorAll("p")].map(node => (node.textContent || "").trim()).filter(Boolean);
              if (parts.length < 2) {
                return null;
              }
              const [weekday, dayNumber] = parts;
              if (!/^(Sun|Mon|Tue|Wed|Thu|Fri|Sat)$/.test(weekday) || !/^\\d{1,2}$/.test(dayNumber)) {
                return null;
              }
              const activeBubble = [...button.querySelectorAll("p")].find(node => (node.textContent || "").trim() === dayNumber);
              const activeStyle = activeBubble ? window.getComputedStyle(activeBubble).backgroundColor : "";
              return {
                weekday,
                day_number: Number(dayNumber),
                selected: !!activeStyle && activeStyle !== "rgba(0, 0, 0, 0)" && activeStyle !== "transparent"
              };
            })
            .filter(Boolean);

          const selected = days.find(day => day.selected) || null;
          return JSON.stringify({
            header_texts: headerTexts,
            days,
            selected
          });
        })()
        """.replace("__MONTH_PATTERN__", self.MONTH_NAME_PATTERN)
        payload = self._eval_json(script)
        month_name, year = self._extract_month_year(payload.get("header_texts") or [])
        selected = payload["selected"]
        if not month_name or year is None or selected is None:
            raise StructuredBackendError("Structured top day strip state is unavailable")
        selected_date = datetime.strptime(
            f"{selected['day_number']} {month_name} {year}",
            "%d %B %Y",
        ).date()
        return {
            "selected_day": selected_date.isoformat(),
            "days": payload["days"],
            "month": month_name,
            "year": year,
        }

    @classmethod
    def _extract_month_year(cls, values: list[str]) -> tuple[str | None, int | None]:
        month_regex = re.compile(rf"^({cls.MONTH_NAME_PATTERN})\s*(\d{{4}})$")
        for value in sorted((value.strip() for value in values if value and value.strip()), key=len):
            match = month_regex.match(value.replace(" ", ""))
            if match:
                return match.group(1), int(match.group(2))
            match = month_regex.match(" ".join(value.split()))
            if match:
                return match.group(1), int(match.group(2))
        return None, None

    def _top_strip_contains(self, target: date_cls) -> bool:
        state = self._top_strip_state()
        weekday = target.strftime("%a")
        return any(day["weekday"] == weekday and day["day_number"] == target.day for day in state["days"])

    def _click_top_strip_day(self, target: date_cls) -> None:
        script = f"""
        (() => {{
          const targetWeekday = {json.dumps(target.strftime("%a"))};
          const targetDay = {target.day};
          const button = [...document.querySelectorAll("button")].find(node => {{
            const parts = [...node.querySelectorAll("p")].map(el => (el.textContent || "").trim()).filter(Boolean);
            return parts.length >= 2 && parts[0] === targetWeekday && Number(parts[1]) === targetDay;
          }});
          if (!button) {{
            throw new Error(`Top strip day not found: ${{targetWeekday}} ${{targetDay}}`);
          }}
          button.click();
          return true;
        }})()
        """
        self._run(["eval", script])

    def _click_top_strip_arrow(self, direction: str) -> None:
        icon = "ChevronRightRoundedIcon" if direction == "next" else "ChevronLeftRoundedIcon"
        script = f"""
        (() => {{
          const button = [...document.querySelectorAll("button")].find(node => {{
            const svg = node.querySelector("svg[data-testid]");
            return svg && svg.getAttribute("data-testid") === {json.dumps(icon)};
          }});
          if (!button) {{
            throw new Error(`Top strip arrow not found: {direction}`);
          }}
          button.click();
          return true;
        }})()
        """
        self._run(["eval", script])

    def _click_button_by_text(self, text: str) -> None:
        script = f"""
        (() => {{
          const target = {json.dumps(text)};
          const visible = node => {{
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          }};
          const button = [...document.querySelectorAll("button")].find(node =>
            visible(node) && (node.innerText || "").trim() === target
          );
          if (!button) {{
            throw new Error(`Button not found: ${{target}}`);
          }}
          button.click();
          return true;
        }})()
        """
        self._run(["eval", script])

    def _button_exists(self, text: str) -> bool:
        script = f"""
        (() => {{
          const target = {json.dumps(text)};
          const visible = node => {{
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          }};
          return JSON.stringify(
            [...document.querySelectorAll("button,a")].some(node =>
              visible(node) && (node.innerText || "").trim() === target
            )
          );
        }})()
        """
        return bool(self._eval_json(script))

    def _confirm_repeating_task_scope(
        self,
        *,
        action: str,
        scope: str,
        required: bool = False,
    ) -> bool:
        labels = {
            "update": {
                "one": "Update this instance only",
                "future": "Update all future tasks",
                "all": "Update all tasks",
            },
            "delete": {
                "one": "Delete this task only",
                "future": "Delete all future tasks",
                "all": "Delete all tasks",
            },
        }.get(action)
        if labels is None or scope not in labels:
            raise StructuredBackendError(f"Unsupported repeating {action} scope: {scope!r}")

        for _ in range(4):
            visible_labels = [label for label in labels.values() if self._button_exists(label)]
            if visible_labels:
                self._click_button_by_text(labels[scope])
                return True
            self._wait(150)
        if required:
            raise StructuredBackendError(f"Structured did not show the repeating {action} scope dialog")
        return False

    def _occurrence_only_update_dialog_text(self) -> str | None:
        script = r"""
        (() => {
          const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
          const visible = node => {
            const rect = node.getBoundingClientRect();
            const style = window.getComputedStyle(node);
            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
          };
          const dialog = [...document.querySelectorAll('[role="dialog"]')].find(node => {
            if (!visible(node)) {
              return false;
            }
            const text = normalize(node.textContent);
            if (!text.includes('Only this task will be updated. Other occurrences are unaffected')) {
              return false;
            }
            const buttons = [...node.querySelectorAll('button')]
              .filter(button => visible(button))
              .map(button => normalize(button.innerText));
            return buttons.includes('Cancel') && buttons.includes('Confirm');
          });
          return JSON.stringify(dialog ? normalize(dialog.textContent) : null);
        })()
        """
        payload = self._eval_json(script)
        if payload in (None, "null"):
            return None
        return str(payload)

    def _current_task_drawer_title(self) -> str | None:
        script = """
        (() => {
          const input = document.querySelector('textarea[placeholder="Structure Your Day"]');
          if (!input) {
            return "null";
          }
          return JSON.stringify(input.value || "");
        })()
        """
        title = self._eval_json(script)
        if title in (None, "null"):
            return None
        return str(title)

    def _assert_task_drawer_title(self, expected_titles: set[str], *, action: str) -> None:
        active_title = self._current_task_drawer_title()
        if active_title in expected_titles:
            return
        allowed = ", ".join(sorted(expected_titles))
        raise StructuredBackendError(
            f"Structured drifted to {active_title!r} while {action}; expected drawer title to remain one of: {allowed}"
        )

    def _assert_recurring_update_applied(
        self,
        *,
        original: RecurringInfo,
        updated: RecurringInfo,
        new_title: str | None,
        frequency: str | None,
        start_day: str | None,
        start: str | None,
        end: str | None,
        duration: int | None,
        note: str | None,
        all_day: bool | None,
        interval: int | None,
        weekdays: list[str] | None,
        end_day: str | None,
        clear_end_day: bool,
        effective_start_day: str | None,
    ) -> None:
        mismatches: list[str] = []

        if new_title is not None and updated.title != new_title:
            mismatches.append(f"title={updated.title!r}")
        if frequency is not None and updated.frequency != frequency:
            mismatches.append(f"frequency={updated.frequency!r}")
        if interval is not None and updated.interval != interval:
            mismatches.append(f"interval={updated.interval!r}")
        if start_day is not None and updated.start_day != start_day:
            mismatches.append(f"start_day={updated.start_day!r}")
        if clear_end_day and updated.end_day is not None:
            mismatches.append(f"end_day={updated.end_day!r}")
        if end_day is not None and updated.end_day != end_day:
            mismatches.append(f"end_day={updated.end_day!r}")
        if weekdays is not None and set(updated.weekdays) != set(weekdays):
            mismatches.append(f"weekdays={updated.weekdays!r}")
        if all_day is not None and updated.is_all_day != all_day:
            mismatches.append(f"all_day={updated.is_all_day!r}")
        if note is not None and updated.note != note:
            mismatches.append(f"note={updated.note!r}")

        if (start is not None or end is not None or duration is not None) and all_day is not True:
            start_minutes, end_minutes = self._resolve_task_time_window(
                day=effective_start_day,
                start=start,
                end=end,
                duration=duration,
            )
            expected_start = start_minutes / 60
            expected_duration = end_minutes - start_minutes
            if updated.start_time is None or abs(updated.start_time - expected_start) > (1 / 120):
                mismatches.append(f"start_time={updated.start_time!r}")
            if updated.duration != expected_duration:
                mismatches.append(f"duration={updated.duration!r}")

        if mismatches:
            requested: list[str] = []
            if new_title is not None:
                requested.append(f"title={new_title!r}")
            if frequency is not None:
                requested.append(f"frequency={frequency!r}")
            if interval is not None:
                requested.append(f"interval={interval!r}")
            if start_day is not None:
                requested.append(f"start_day={start_day!r}")
            if clear_end_day:
                requested.append("end_day=None")
            elif end_day is not None:
                requested.append(f"end_day={end_day!r}")
            if weekdays is not None:
                requested.append(f"weekdays={weekdays!r}")
            if all_day is not None:
                requested.append(f"all_day={all_day!r}")
            if note is not None:
                requested.append(f"note={note!r}")
            if start is not None or end is not None or duration is not None:
                requested.append(f"time=start:{start!r},end:{end!r},duration:{duration!r}")
            raise StructuredBackendError(
                "Structured did not persist the requested recurring update. "
                f"Requested: {', '.join(requested) or 'no-op'}. "
                f"Observed: {', '.join(mismatches)}."
            )

    def _click_task_completion_toggle(self) -> None:
        self._run(
            [
                "eval",
                """
                (() => {
                  const button = [...document.querySelectorAll("button")].find(node => {
                    const testid = node.querySelector("svg[data-testid]")?.getAttribute("data-testid") || "";
                    return /RadioButtonUnchecked|CheckCircle/.test(testid) &&
                      node.getBoundingClientRect().x > 1050 &&
                      node.getBoundingClientRect().y < 200;
                  });
                  if (!button) {
                    throw new Error("Task completion toggle not found");
                  }
                  button.click();
                  return true;
                })()
                """,
            ]
        )

    def _click_task_delete_button(self) -> None:
        self._run(
            [
                "eval",
                """
                (() => {
                  const visible = node => {
                    const rect = node.getBoundingClientRect();
                    const style = window.getComputedStyle(node);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                  };
                  const button = [...document.querySelectorAll("button")].find(node => {
                    const svg = node.querySelector("svg[data-testid]");
                    return visible(node) &&
                      svg &&
                      svg.getAttribute("data-testid") === "DeleteRoundedIcon";
                  });
                  if (!button) {
                    throw new Error("Task delete button not found");
                  }
                  button.click();
                  return true;
                })()
                """,
            ]
        )

    def _set_task_all_day_control(self, enabled: bool) -> None:
        script = f"""
        (() => {{
          const checkbox = [...document.querySelectorAll('input[type="checkbox"]')].find(node => {{
            const label = node.closest('label');
            return label && (label.textContent || '').replace(/\\s+/g, ' ').includes('All-Day');
          }});
          if (!checkbox) {{
            throw new Error('Task all-day checkbox not found');
          }}
          if (checkbox.checked !== {str(enabled).lower()}) {{
            checkbox.click();
          }}
          return JSON.stringify({{ checked: checkbox.checked }});
        }})()
        """
        payload = self._eval_json(script)
        if bool(payload.get("checked")) != enabled:
            raise StructuredBackendError("Structured did not apply the requested all-day state")

    def _click_task_more_action(self, text: str) -> None:
        self._run(
            [
                "eval",
                """
                (() => {
                  const button = [...document.querySelectorAll("button")].find(node => {
                    const svg = node.querySelector("svg[data-testid]");
                    return svg && svg.getAttribute("data-testid") === "MoreHorizRoundedIcon";
                  });
                  if (!button) {
                    throw new Error("Task more menu button not found");
                  }
                  button.click();
                  return true;
                })()
                """,
            ]
        )
        self._wait(200)
        script = f"""
        (() => {{
          const target = {json.dumps(text)};
          const item = [...document.querySelectorAll('[role="menuitem"], li')].find(node =>
            (node.textContent || '').replace(/\\s+/g, ' ').trim() === target
          );
          if (!item) {{
            throw new Error(`Task menu item not found: ${{target}}`);
          }}
          item.click();
          return true;
        }})()
        """
        self._run(["eval", script])

    def _set_task_date(self, day: str) -> None:
        display = datetime.strptime(day, "%Y-%m-%d").strftime("%d/%m/%Y")
        self._set_controlled_value('input[placeholder="DD/MM/YYYY"]', display)
        self._run(["press", "Enter"])
        self._wait(250)
        self._close_date_picker_if_open()

    def _set_task_time_inputs(self, *, start_minutes: int, end_minutes: int) -> None:
        start_text = self._format_picker_time(start_minutes)
        end_text = self._format_picker_time(end_minutes)
        self._run(
            [
                "eval",
                f"""
                (() => {{
                  const inputs = [...document.querySelectorAll('input[placeholder="hh:mm aa"]')];
                  if (inputs.length < 2) {{
                    throw new Error("Task time inputs not found");
                  }}
                  inputs[0].setAttribute("data-cli-time-role", "start");
                  inputs[1].setAttribute("data-cli-time-role", "end");
                  return JSON.stringify(inputs.slice(0, 2).map(node => node.value));
                }})()
                """,
            ]
        )
        self._overwrite_text_input('input[data-cli-time-role="start"]', start_text)
        preset_label = self._duration_preset_label(end_minutes - start_minutes)
        if preset_label is not None:
            self._click_button_by_text(preset_label)
        else:
            self._overwrite_text_input('input[data-cli-time-role="end"]', end_text)
            self._run(
                [
                    "eval",
                    """
                    (() => {
                      const active = document.activeElement;
                      if (active && typeof active.blur === "function") {
                        active.blur();
                      }
                      return true;
                    })()
                    """,
                ]
            )
        self._wait(150)
        values = self._eval_json(
            """
            (() => JSON.stringify(
              [...document.querySelectorAll('input[placeholder="hh:mm aa"]')].slice(0, 2).map(node => node.value)
            ))()
            """
        )
        if len(values) < 2 or values[0] != start_text or values[1] != end_text:
            raise StructuredBackendError(
                f"Structured did not retain the requested task time window ({start_text} -> {end_text}); current values: {values}"
            )
        if self._task_time_picker_is_open():
            self._close_task_time_picker()
        if self._task_time_picker_is_open():
            raise StructuredBackendError("Structured time picker remained open after time entry")
        try:
            current_start, current_end = self._current_panel_time_range()
        except StructuredBackendError:
            return
        if current_start != start_minutes or current_end != end_minutes:
            raise StructuredBackendError(
                "Structured did not commit the requested task time window "
                f"({start_text} -> {end_text}); current panel range is "
                f"{self._format_picker_time(current_start)} -> {self._format_picker_time(current_end)}"
            )

    @staticmethod
    def _format_picker_time(total_minutes: int) -> str:
        hours = (total_minutes // 60) % 24
        minutes = total_minutes % 60
        suffix = "AM" if hours < 12 else "PM"
        display_hour = hours % 12 or 12
        return f"{display_hour:02d}:{minutes:02d} {suffix}"

    @staticmethod
    def _duration_preset_label(duration: int) -> str | None:
        presets = {
            1: "1m",
            15: "15m",
            30: "30m",
            45: "45m",
            60: "1h",
            90: "1h 30m",
        }
        return presets.get(duration)

    def _set_auxiliary_task_textarea(self, value: str) -> None:
        self._run(
            [
                "eval",
                f"""
                (() => {{
                  const node = document.querySelector('div[contenteditable="true"][role="textbox"]');
                  if (!node) {{
                    throw new Error("Task notes editor not found");
                  }}
                  const targetValue = {json.dumps(value)};
                  node.focus();
                  const selection = window.getSelection();
                  const range = document.createRange();
                  range.selectNodeContents(node);
                  selection?.removeAllRanges();
                  selection?.addRange(range);

                  let applied = false;
                  if (typeof document.execCommand === "function") {{
                    applied = document.execCommand("insertText", false, targetValue);
                  }}

                  if (!applied || (node.textContent || "") !== targetValue) {{
                    const lines = targetValue.split(/\\n/);
                    const paragraphs = lines.length ? lines : [""];
                    node.replaceChildren(
                      ...paragraphs.map(line => {{
                        const paragraph = document.createElement("p");
                        if (line) {{
                          paragraph.textContent = line;
                        }} else {{
                          paragraph.appendChild(document.createElement("br"));
                        }}
                        return paragraph;
                      }})
                    );
                    node.dispatchEvent(new InputEvent("input", {{
                      bubbles: true,
                      inputType: targetValue ? "insertText" : "deleteContentBackward",
                      data: targetValue || null
                    }}));
                  }}
                  node.dispatchEvent(new Event("change", {{ bubbles: true }}));
                  node.blur();
                  return JSON.stringify({{
                    text: node.textContent || ""
                  }});
                }})()
                """,
            ]
        )

    def _overwrite_text_input(self, selector: str, value: str) -> None:
        current = self._eval_json(
            f"""
            (() => {{
              const node = document.querySelector({json.dumps(selector)});
              if (!node) {{
                throw new Error("Text input not found for overwrite");
              }}
              const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
              if (!setter) {{
                throw new Error("Text input setter unavailable");
              }}
              node.focus();
              if (typeof node.select === "function") {{
                node.select();
              }}
              setter.call(node, "");
              node.dispatchEvent(new Event("input", {{ bubbles: true }}));
              let applied = false;
              if (typeof document.execCommand === "function") {{
                applied = document.execCommand("insertText", false, {json.dumps(value)});
              }}
              if (!applied || node.value !== {json.dumps(value)}) {{
                setter.call(node, {json.dumps(value)});
              }}
              node.dispatchEvent(new Event("input", {{ bubbles: true }}));
              node.dispatchEvent(new Event("change", {{ bubbles: true }}));
              return JSON.stringify(node.value);
            }})()
            """
        )
        if current != value:
            raise StructuredBackendError(
                f"Structured did not retain the requested text input value {value!r}; current value: {current!r}"
            )

    def _resolve_task_time_window(
        self,
        *,
        day: str | None,
        start: str | None,
        end: str | None,
        duration: int | None,
    ) -> tuple[int, int]:
        current: tuple[int, int] | None = None
        if start is None or (end is None and duration is None):
            current = self._current_panel_time_range()
        start_minutes = self._parse_time_string(start) if start is not None else current[0]
        if end is not None:
            end_minutes = self._parse_time_string(end)
        elif duration is not None:
            end_minutes = start_minutes + duration
        else:
            end_minutes = current[1]
        if end_minutes <= start_minutes:
            raise StructuredBackendError("Task end time must be after start time")
        return start_minutes, end_minutes

    def _current_panel_time_range(self) -> tuple[int, int]:
        label = self._eval_json(
            r"""
            (() => {
              const node = [...document.querySelectorAll("*")].find(el =>
                /^\d{2}:\d{2} [AP]M - \d{2}:\d{2} [AP]M(?:[⁺+][\d⁰¹²³⁴⁵⁶⁷⁸⁹]+)?$/.test((el.textContent || "").trim())
              );
              return JSON.stringify(node ? (node.textContent || "").trim() : null);
            })()
            """
        )
        if not label:
            raise StructuredBackendError("Task time range is not visible in the current panel")
        match = re.match(
            r"^(?P<start>\d{2}:\d{2} [AP]M) - (?P<end>\d{2}:\d{2} [AP]M)(?P<offset>[⁺+](?P<days>[\d⁰¹²³⁴⁵⁶⁷⁸⁹]+))?$",
            str(label),
        )
        if not match:
            raise StructuredBackendError(f"Task time range label could not be parsed: {label!r}")
        start_minutes = self._parse_time_string(match.group("start"))
        end_minutes = self._parse_time_string(match.group("end"))
        superscript_digits = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
        extra_days = int((match.group("days") or "0").translate(superscript_digits))
        if extra_days:
            end_minutes += extra_days * 1440
        return start_minutes, end_minutes

    @staticmethod
    def _parse_time_string(value: str) -> int:
        parsed = datetime.strptime(value.strip().upper(), "%I:%M %p")
        return parsed.hour * 60 + parsed.minute

    def _set_controlled_value(self, selector: str, value: str) -> None:
        script = f"""
        (() => {{
          const node = document.querySelector({json.dumps(selector)});
          if (!node) {{
            throw new Error(`Control not found: {selector}`);
          }}
          const proto = node.tagName === "TEXTAREA"
            ? window.HTMLTextAreaElement.prototype
            : window.HTMLInputElement.prototype;
          const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
          if (!setter) {{
            throw new Error(`Value setter unavailable for: {selector}`);
          }}
          setter.call(node, {json.dumps(value)});
          node.dispatchEvent(new Event("input", {{ bubbles: true }}));
          node.dispatchEvent(new Event("change", {{ bubbles: true }}));
          return JSON.stringify({{
            selector: {json.dumps(selector)},
            value: node.value
          }});
        }})()
        """
        self._run(["eval", script])

    def _eval_json(self, script: str) -> Any:
        raw = self._run(["eval", " ".join(line.strip() for line in script.strip().splitlines())])
        return decode_eval_output(raw)

    def _wait(self, milliseconds: int) -> None:
        self._run(["wait", str(milliseconds)])

    def _run(
        self,
        args: list[str],
        *,
        include_profile: bool = True,
    ) -> str:
        command = self._command(include_profile=include_profile) + args
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.COMMAND_TIMEOUT_SECONDS,
            )
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            result = exc
            timed_out = True

        if timed_out or result.returncode != 0:
            if timed_out:
                detail = (
                    f"agent-browser command timed out after {self.COMMAND_TIMEOUT_SECONDS}s: "
                    f"{' '.join(command)}"
                )
            else:
                stderr = (result.stderr or "").strip()
                stdout = (result.stdout or "").strip()
                detail = stderr or stdout or f"exit code {result.returncode}"
            cdp_command = self._command_via_cdp()
            if cdp_command and (timed_out or self._should_retry_via_cdp(detail)):
                try:
                    retry = subprocess.run(
                        cdp_command + args,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=self.COMMAND_TIMEOUT_SECONDS,
                    )
                    retry_timed_out = False
                except subprocess.TimeoutExpired:
                    retry_timed_out = True
                    retry = None
                if not retry_timed_out and retry.returncode == 0:
                    return (retry.stdout or "").strip()
                if retry_timed_out:
                    detail = (
                        f"agent-browser CDP retry timed out after {self.COMMAND_TIMEOUT_SECONDS}s: "
                        f"{' '.join(cdp_command + args)}"
                    )
                else:
                    retry_stderr = (retry.stderr or "").strip()
                    retry_stdout = (retry.stdout or "").strip()
                    detail = retry_stderr or retry_stdout or f"exit code {retry.returncode}"
            if args and args[0] == "eval":
                try:
                    return self._raw_cdp_eval(args[1])
                except Exception:
                    pass
            raise StructuredBackendError(detail)
        return (result.stdout or "").strip()

    def _command(self, *, include_profile: bool, headed: bool = False) -> list[str]:
        command = [self.agent_browser, "--session", self.session]
        if include_profile:
            command.extend(["--profile", self.profile])
        if headed:
            command.append("--headed")
        return command

    def _command_via_cdp(self) -> list[str] | None:
        active_port = Path(self.profile) / "DevToolsActivePort"
        if not active_port.exists():
            return None
        lines = [line.strip() for line in active_port.read_text().splitlines() if line.strip()]
        if not lines:
            return None
        port = lines[0]
        if not port.isdigit():
            return None
        return [self.agent_browser, "--cdp", f"http://127.0.0.1:{port}"]

    def _page_cdp_websocket_url(self) -> str | None:
        active_port = Path(self.profile) / "DevToolsActivePort"
        if not active_port.exists():
            return None
        lines = [line.strip() for line in active_port.read_text().splitlines() if line.strip()]
        if not lines:
            return None
        port = lines[0]
        if not port.isdigit():
            return None
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=self.COMMAND_TIMEOUT_SECONDS) as response:
                targets = json.load(response)
        except Exception:
            return None
        for target in targets:
            if target.get("type") == "page" and str(target.get("url", "")).startswith(APP_URL):
                return target.get("webSocketDebuggerUrl")
        return None

    def _raw_cdp_eval(self, expression: str) -> str:
        try:
            import websocket  # type: ignore[import-not-found]
        except Exception as exc:
            raise StructuredBackendError(
                "Raw CDP eval fallback requires websocket-client. Install websocket-client>=1.8."
            ) from exc

        ws_url = self._page_cdp_websocket_url()
        if not ws_url:
            raise StructuredBackendError("Structured page websocket URL is unavailable for raw CDP eval")

        request = {
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        }
        try:
            ws = websocket.create_connection(
                ws_url,
                timeout=self.COMMAND_TIMEOUT_SECONDS,
                suppress_origin=True,
            )
            try:
                ws.send(json.dumps(request))
                while True:
                    message = json.loads(ws.recv())
                    if message.get("id") != 1:
                        continue
                    if "error" in message:
                        raise StructuredBackendError(str(message["error"]))
                    result = message.get("result", {}).get("result", {})
                    if "value" in result:
                        value = result["value"]
                        return value if isinstance(value, str) else json.dumps(value)
                    if result.get("type") == "undefined":
                        return "null"
                    return json.dumps(result)
            finally:
                ws.close()
        except StructuredBackendError:
            raise
        except Exception as exc:
            raise StructuredBackendError(f"Raw CDP eval failed: {exc}") from exc

    @staticmethod
    def _should_retry_via_cdp(detail: str) -> bool:
        retry_markers = (
            "Failed to create a ProcessSingleton",
            "Chrome exited before providing DevTools URL",
            "Auto-launch failed",
        )
        return any(marker in detail for marker in retry_markers)
