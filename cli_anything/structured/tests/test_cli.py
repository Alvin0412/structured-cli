from __future__ import annotations

import unittest
from unittest import mock

from click.testing import CliRunner

from cli_anything.structured.core.models import (
    AgendaItem,
    InboxTask,
    RecurringInfo,
    SettingsInfo,
    SubtaskInfo,
    TaskInfo,
)
from cli_anything.structured import structured_cli


class FakeBackend:
    @staticmethod
    def _task(reference: str, **overrides):
        title = overrides.pop("title", reference)
        return TaskInfo(
            id=overrides.pop("id", "task-1"),
            title=title,
            day=overrides.pop("day", "2026-04-02"),
            start_time=overrides.pop("start_time", 9.25),
            duration=overrides.pop("duration", 45),
            completed_at=overrides.pop("completed_at", None),
            modified_at=overrides.pop("modified_at", "2026-04-01T08:00:00Z"),
            is_in_inbox=overrides.pop("is_in_inbox", False),
            is_all_day=overrides.pop("is_all_day", False),
            note=overrides.pop("note", "Note"),
            color=overrides.pop("color", "midnight"),
            symbol=overrides.pop("symbol", "text.badge.checkmark"),
            is_hidden=overrides.pop("is_hidden", False),
            subtasks=overrides.pop(
                "subtasks",
                [SubtaskInfo(id="sub-1", title="Existing subtask")],
            ),
            metadata=overrides.pop("metadata", {"source": "fake"}),
        )

    @staticmethod
    def _recurring(reference: str, **overrides):
        title = overrides.pop("title", reference)
        return RecurringInfo(
            id=overrides.pop("id", "rec-1"),
            title=title,
            frequency=overrides.pop("frequency", "weekly"),
            interval=overrides.pop("interval", 1),
            start_day=overrides.pop("start_day", "2026-04-01"),
            end_day=overrides.pop("end_day", "2026-06-01"),
            start_time=overrides.pop("start_time", 8.0),
            duration=overrides.pop("duration", 30),
            is_all_day=overrides.pop("is_all_day", False),
            note=overrides.pop("note", "Recurring note"),
            color=overrides.pop("color", "sunrise"),
            symbol=overrides.pop("symbol", "repeat"),
            modified_at=overrides.pop("modified_at", "2026-04-01T05:00:00Z"),
            weekdays=overrides.pop("weekdays", ["Mon", "Wed"]),
            subtasks=overrides.pop(
                "subtasks",
                [SubtaskInfo(id="rec-sub-1", title="Recurring subtask")],
            ),
            metadata=overrides.pop("metadata", {"source": "fake"}),
        )

    def launch_login(self):
        return {"launched": True, "session": "structured", "profile": "/tmp/profile", "url": "https://web.structured.app/"}

    def session_status(self):
        return {
            "session": "structured",
            "url": "https://web.structured.app/",
            "title": "Structured Web",
            "logged_in": True,
            "browser_day": "2026-04-01",
            "browser_timezone": "Asia/Shanghai",
            "settings": self.settings_show().to_dict(),
        }

    def browser_today(self):
        return {"day": "2026-04-01", "timezone": "Asia/Shanghai"}

    def settings_show(self):
        return SettingsInfo(
            user_id="user-1",
            theme="midnight",
            layout="full",
            first_weekday=0,
            did_complete_onboarding=True,
            cloud_terms_date="2025-09-14T04:40:20.784+00:00",
            timezone="Asia/Shanghai",
            duration_presets=[15, 30, 60],
        )

    def inbox_list(self):
        return [
            InboxTask(id="1", title="Open task", completed_at=None, modified_at="2026-04-01T00:00:00Z"),
            InboxTask(id="2", title="Done task", completed_at="2026-04-01T01:00:00Z", modified_at="2026-04-01T01:00:00Z"),
        ]

    def inbox_add(self, title: str):
        return InboxTask(id="3", title=title, completed_at=None, modified_at="2026-04-01T02:00:00Z")

    def inbox_update(self, old_title: str, new_title: str):
        return InboxTask(id="3", title=new_title, completed_at=None, modified_at="2026-04-01T03:00:00Z")

    def inbox_delete(self, title: str):
        return {"deleted": True, "title": title}

    def agenda_list(self, *, day: str | None = None):
        return [
            AgendaItem(
                id="task-1",
                source="task",
                title="One-off task",
                day=day or "2026-04-01",
                start_time=13.5,
                duration=30,
                completed_at=None,
                color="midnight",
                symbol="pin.fill",
                note="",
            )
        ]

    def close_browser(self):
        return None

    def task_list(self, **kwargs):
        tasks = [
            self._task("Structured task"),
            self._task(
                "Inbox task",
                id="task-2",
                is_in_inbox=True,
                day=None,
                start_time=None,
                duration=None,
                subtasks=[],
            ),
        ]
        query = kwargs.get("query")
        if query:
            query_text = str(query).lower()
            tasks = [task for task in tasks if query_text in task.title.lower() or query_text in task.note.lower()]
        return tasks

    def task_show(self, reference: str):
        return self._task(reference)

    def task_create(self, *, title, day=None, start=None, end=None, duration=None, note=None):
        return self._task(
            title,
            id="task-2",
            day=day or "2026-04-01",
            start_time=9.25 if start else 13.5,
            duration=duration or 45,
            note=note or "",
            subtasks=[],
        )

    def task_note_get(self, reference: str):
        return self.task_show(reference).note

    def task_note_set(self, reference: str, note: str):
        task = self.task_show(reference)
        task.note = note
        return task

    def task_note_clear(self, reference: str):
        return self.task_note_set(reference, "")

    def task_set_all_day(self, reference: str, enabled: bool):
        task = self.task_show(reference)
        task.is_all_day = enabled
        return task

    def task_subtask_list(self, reference: str):
        return self.task_show(reference).subtasks

    def task_subtask_add(self, reference: str, title: str):
        return self._task(reference, subtasks=[SubtaskInfo(id="sub-1", title="Existing subtask"), SubtaskInfo(id="sub-2", title=title)])

    def task_complete(self, reference: str):
        task = self.task_show(reference)
        task.completed_at = "2026-04-01T08:10:00Z"
        return task

    def task_update(self, reference: str, **kwargs):
        task = self.task_show(kwargs.get("new_title") or reference)
        if kwargs.get("day") is not None:
            task.day = kwargs["day"]
        if kwargs.get("duration") is not None:
            task.duration = kwargs["duration"]
        if kwargs.get("note") is not None:
            task.note = kwargs["note"]
        if kwargs.get("all_day") is not None:
            task.is_all_day = kwargs["all_day"]
        return task

    def task_restore(self, reference: str):
        return self.task_show(reference)

    def task_duplicate(self, reference: str):
        return self._task(f"{reference} copy", id="task-copy")

    def task_move_to_inbox(self, reference: str):
        return self._task(reference, is_in_inbox=True, day=None, start_time=None, duration=None)

    def task_move_out_of_inbox(self, reference: str, **kwargs):
        return self._task(
            reference,
            day=kwargs.get("day", "2026-04-04"),
            start_time=10.5 if kwargs.get("start") else None,
            duration=kwargs.get("duration", 30),
            is_in_inbox=False,
            is_all_day=kwargs.get("all_day", False),
        )

    def task_delete(self, reference: str):
        return {"deleted": True, "reference": reference}

    def recurring_list(self, **kwargs):
        rows = [
            self._recurring("Standup"),
            self._recurring("Review", id="rec-2", frequency="daily", weekdays=[]),
        ]
        query = kwargs.get("query")
        if query:
            query_text = str(query).lower()
            rows = [row for row in rows if query_text in row.title.lower() or query_text in row.note.lower()]
        frequency = kwargs.get("frequency")
        if frequency:
            rows = [row for row in rows if row.frequency == frequency]
        return rows

    def recurring_show(self, reference: str):
        return self._recurring(reference)

    def recurring_create(self, **kwargs):
        return self._recurring(
            kwargs["title"],
            id="rec-created",
            frequency=kwargs["frequency"],
            interval=kwargs.get("interval", 1),
            start_day=kwargs.get("start_day", "2026-04-01"),
            end_day=kwargs.get("end_day"),
            note=kwargs.get("note", ""),
            is_all_day=kwargs.get("all_day", False),
            weekdays=kwargs.get("weekdays") or ["Mon", "Wed"],
        )

    def recurring_update(self, reference: str, **kwargs):
        recurring = self._recurring(reference)
        if kwargs.get("new_title") is not None:
            recurring.title = kwargs["new_title"]
        if kwargs.get("frequency") is not None:
            recurring.frequency = kwargs["frequency"]
        if kwargs.get("interval") is not None:
            recurring.interval = kwargs["interval"]
        if kwargs.get("end_day") is not None:
            recurring.end_day = kwargs["end_day"]
        if kwargs.get("clear_end_day"):
            recurring.end_day = None
        if kwargs.get("weekdays") is not None:
            recurring.weekdays = kwargs["weekdays"]
        return recurring

    def recurring_delete(self, reference: str, *, scope: str = "all"):
        return {"deleted": True, "reference": reference, "scope": scope}


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.patcher = mock.patch.object(structured_cli.AppContext, "__init__", self._fake_init)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()

    @staticmethod
    def _fake_init(self, *, json_output, session, profile, agent_browser):
        self.json_output = json_output
        self.backend = FakeBackend()

    def test_inbox_list_json(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["--json", "inbox", "list"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('"title": "Open task"', result.output)
        self.assertIn('"is_completed": false', result.output)

    def test_agenda_list_human_output(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["agenda", "list", "--day", "2026-04-01"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("1 agenda item(s) for 2026-04-01", result.output)
        self.assertIn("One-off task", result.output)

    def test_session_login_human_output(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["session", "login"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Launched Structured login browser", result.output)

    def test_task_create_json(self) -> None:
        result = self.runner.invoke(
            structured_cli.cli,
            [
                "--json",
                "task",
                "create",
                "Structured task",
                "--day",
                "2026-04-02",
                "--start",
                "09:15 AM",
                "--duration",
                "45",
                "--note",
                "Created in test",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn('"title": "Structured task"', result.output)
        self.assertIn('"day": "2026-04-02"', result.output)

    def test_task_list_json(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["--json", "task", "list", "--location", "all"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('"title": "Structured task"', result.output)
        self.assertIn('"title": "Inbox task"', result.output)

    def test_task_search_human_output(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["task", "search", "structured"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Structured task", result.output)

    def test_task_note_get_json(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["--json", "task", "note", "get", "Structured task"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('"note": "Note"', result.output)

    def test_task_set_all_day_human_output(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["task", "set-all-day", "Structured task", "--on"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Set all-day=True for task: Structured task", result.output)

    def test_task_subtask_list_human_output(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["task", "subtask", "list", "Structured task"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("1 subtask(s)", result.output)
        self.assertIn("Existing subtask", result.output)

    def test_task_duplicate_json(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["--json", "task", "duplicate", "Structured task"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('"id": "task-copy"', result.output)

    def test_task_move_to_inbox_json(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["--json", "task", "move-to-inbox", "Structured task"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('"is_in_inbox": true', result.output)

    def test_task_move_out_of_inbox_json(self) -> None:
        result = self.runner.invoke(
            structured_cli.cli,
            ["--json", "task", "move-out-of-inbox", "Inbox task", "--day", "2026-04-04", "--start", "10:30 AM", "--duration", "30"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn('"day": "2026-04-04"', result.output)
        self.assertIn('"is_in_inbox": false', result.output)

    def test_task_complete_human_output(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["task", "complete", "Structured task"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Completed task: Structured task", result.output)

    def test_task_update_json(self) -> None:
        result = self.runner.invoke(
            structured_cli.cli,
            [
                "--json",
                "task",
                "update",
                "Structured task",
                "--new-title",
                "Structured task updated",
                "--day",
                "2026-04-03",
                "--duration",
                "60",
                "--note",
                "",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn('"title": "Structured task updated"', result.output)
        self.assertIn('"day": "2026-04-03"', result.output)

    def test_recurring_list_json(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["--json", "recurring", "list", "--frequency", "weekly"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('"title": "Standup"', result.output)
        self.assertNotIn('"title": "Review"', result.output)

    def test_recurring_show_human_output(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["recurring", "show", "Standup"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("frequency: weekly", result.output)
        self.assertIn("weekdays: Mon, Wed", result.output)

    def test_recurring_create_json(self) -> None:
        result = self.runner.invoke(
            structured_cli.cli,
            [
                "--json",
                "recurring",
                "create",
                "Standup",
                "--frequency",
                "weekly",
                "--start-day",
                "2026-04-02",
                "--interval",
                "2",
                "--weekday",
                "Tue",
                "--weekday",
                "Thu",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn('"id": "rec-created"', result.output)
        self.assertIn('"frequency": "weekly"', result.output)

    def test_recurring_update_json(self) -> None:
        result = self.runner.invoke(
            structured_cli.cli,
            [
                "--json",
                "recurring",
                "update",
                "Standup",
                "--new-title",
                "Daily standup",
                "--frequency",
                "daily",
                "--interval",
                "3",
                "--no-end-day",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn('"title": "Daily standup"', result.output)
        self.assertIn('"frequency": "daily"', result.output)
        self.assertIn('"interval": 3', result.output)

    def test_recurring_delete_human_output(self) -> None:
        result = self.runner.invoke(structured_cli.cli, ["recurring", "delete", "Standup", "--scope", "future"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Deleted recurring task: Standup (future)", result.output)


if __name__ == "__main__":
    unittest.main()
