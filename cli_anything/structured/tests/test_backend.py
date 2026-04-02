from __future__ import annotations

import tempfile
import unittest
from datetime import date as date_cls
from pathlib import Path
from unittest import mock

from cli_anything.structured.core.models import AgendaItem
from cli_anything.structured.utils.agent_browser_backend import (
    StructuredAmbiguousError,
    StructuredBackend,
    StructuredBackendError,
    StructuredNotFoundError,
    build_agenda_items,
    build_recurring_info,
    build_subtasks,
    build_task_info,
    decode_eval_output,
)


class BackendTests(unittest.TestCase):
    def test_decode_eval_output_handles_double_encoded_json(self) -> None:
        raw = '"{\\"title\\": \\"Structured\\", \\"count\\": 2}"'
        self.assertEqual(
            decode_eval_output(raw),
            {"title": "Structured", "count": 2},
        )

    def test_decode_eval_output_leaves_plain_text_alone(self) -> None:
        self.assertEqual(decode_eval_output("Structured Web"), "Structured Web")

    def test_build_agenda_items_merges_tasks_and_recurring_occurrences(self) -> None:
        items = build_agenda_items(
            day="2026-04-01",
            tasks=[
                {
                    "id": "task-1",
                    "title": "One-off task",
                    "day": "2026-04-01",
                    "start_time": 13.5,
                    "duration": 30,
                    "completed_at": None,
                    "color": "midnight",
                    "symbol": "pin.fill",
                    "note": "",
                }
            ],
            occurrences=[
                {
                    "id": "occ-1",
                    "recurring": "rec-1",
                    "completed_at": "2026-04-01T08:05:00Z",
                }
            ],
            recurring_map={
                "rec-1": {
                    "id": "rec-1",
                    "title": "Recurring task",
                    "start_time": 8.0,
                    "duration": 60,
                    "color": "day",
                    "symbol": "alarm.fill",
                    "note": "",
                }
            },
        )

        self.assertEqual([item.title for item in items], ["Recurring task", "One-off task"])
        self.assertTrue(all(isinstance(item, AgendaItem) for item in items))
        self.assertTrue(items[0].is_completed)
        self.assertEqual(items[1].source, "task")

    def test_build_agenda_items_skips_detached_occurrences(self) -> None:
        items = build_agenda_items(
            day="2026-04-02",
            tasks=[],
            occurrences=[
                {
                    "id": "occ-1",
                    "recurring": "rec-1",
                    "completed_at": None,
                    "is_detached": True,
                    "detached_task": None,
                }
            ],
            recurring_map={
                "rec-1": {
                    "id": "rec-1",
                    "title": "Recurring task",
                    "start_time": 8.0,
                    "duration": 60,
                    "color": "day",
                    "symbol": "alarm.fill",
                    "note": "",
                }
            },
        )

        self.assertEqual(items, [])

    def test_build_task_info_maps_task_row(self) -> None:
        task = build_task_info(
            {
                "id": "task-1",
                "title": "Structured task",
                "day": "2026-04-02",
                "start_time": 9.25,
                "duration": 45,
                "completed_at": None,
                "modified_at": "2026-04-01T08:00:00Z",
                "is_in_inbox": False,
                "is_all_day": False,
                "note": "Note",
                "color": "midnight",
                "symbol": "text.badge.checkmark",
                "is_hidden": True,
                "subtasks": [{"id": "sub-1", "title": "Prepare notes"}],
                "metadata": {"source": "test"},
            }
        )
        self.assertEqual(task.title, "Structured task")
        self.assertEqual(task.day, "2026-04-02")
        self.assertEqual(task.duration, 45)
        self.assertFalse(task.is_completed)
        self.assertTrue(task.is_hidden)
        self.assertEqual([subtask.title for subtask in task.subtasks], ["Prepare notes"])
        self.assertEqual(task.metadata["source"], "test")

    def test_build_subtasks_ignores_invalid_entries(self) -> None:
        subtasks = build_subtasks(
            [
                {"id": "sub-1", "title": "One"},
                {"id": "sub-2"},
                "bad",
                {"title": "Missing id"},
            ]
        )
        self.assertEqual([subtask.title for subtask in subtasks], ["One"])

    def test_build_recurring_info_maps_weekdays(self) -> None:
        recurring = build_recurring_info(
            {
                "id": "rec-1",
                "title": "Standup",
                "recurring_type": 2,
                "interval": 1,
                "start_day": "2026-04-01",
                "end_day": "2026-06-01",
                "start_time": 8.0,
                "duration": 30,
                "is_all_day": False,
                "note": "Recurring note",
                "color": "sunrise",
                "symbol": "repeat",
                "modified_at": "2026-04-01T05:00:00Z",
                "monday": True,
                "wednesday": True,
                "subtasks": [{"id": "sub-1", "title": "Review"}],
                "metadata": {"source": "test"},
            }
        )
        self.assertEqual(recurring.frequency, "weekly")
        self.assertEqual(recurring.weekdays, ["Mon", "Wed"])
        self.assertEqual(recurring.subtasks[0].title, "Review")
        self.assertEqual(recurring.metadata["source"], "test")

    def test_backend_command_includes_profile_only_when_requested(self) -> None:
        backend = StructuredBackend(
            session="structured-test",
            profile="/tmp/profile",
            agent_browser="agent-browser",
        )
        self.assertEqual(
            backend._command(include_profile=False),
            ["agent-browser", "--session", "structured-test"],
        )
        self.assertEqual(
            backend._command(include_profile=True),
            ["agent-browser", "--session", "structured-test", "--profile", "/tmp/profile"],
        )

    def test_backend_uses_devtools_active_port_for_cdp_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            profile = Path(tmp_dir)
            (profile / "DevToolsActivePort").write_text("63606\n/devtools/browser/example\n")
            backend = StructuredBackend(
                session="structured-test",
                profile=profile,
                agent_browser="agent-browser",
            )
            self.assertEqual(
                backend._command_via_cdp(),
                ["agent-browser", "--cdp", "http://127.0.0.1:63606"],
            )

    def test_retry_via_cdp_markers(self) -> None:
        self.assertTrue(
            StructuredBackend._should_retry_via_cdp("Chrome exited before providing DevTools URL")
        )
        self.assertTrue(
            StructuredBackend._should_retry_via_cdp("Failed to create a ProcessSingleton for your profile directory")
        )
        self.assertFalse(StructuredBackend._should_retry_via_cdp("some unrelated failure"))

    def test_run_eval_does_not_leak_raw_cdp_exceptions(self) -> None:
        backend = StructuredBackend(
            session="structured-test",
            profile="/tmp/profile",
            agent_browser="agent-browser",
        )
        backend._raw_cdp_eval = mock.Mock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        failed = mock.Mock(return_value=mock.Mock(returncode=1, stdout="", stderr="eval failed"))
        with mock.patch(
            "cli_anything.structured.utils.agent_browser_backend.subprocess.run",
            failed,
        ):
            with self.assertRaisesRegex(StructuredBackendError, "eval failed"):
                backend._run(["eval", "1"])

    def test_resolve_task_time_window_skips_current_lookup_when_start_and_duration_are_explicit(self) -> None:
        backend = StructuredBackend(
            session="structured-test",
            profile="/tmp/profile",
            agent_browser="agent-browser",
        )

        def fail_current_range():
            raise AssertionError("current panel range should not be queried")

        backend._current_panel_time_range = fail_current_range  # type: ignore[method-assign]
        window = backend._resolve_task_time_window(
            day="2026-04-03",
            start="09:30 AM",
            end=None,
            duration=30,
        )
        self.assertEqual(window, (570, 600))

    def test_duration_preset_label_maps_supported_values(self) -> None:
        self.assertEqual(StructuredBackend._duration_preset_label(30), "30m")
        self.assertEqual(StructuredBackend._duration_preset_label(60), "1h")
        self.assertIsNone(StructuredBackend._duration_preset_label(20))

    def test_current_panel_time_range_parses_next_day_suffix(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        backend._eval_json = mock.Mock(return_value="10:30 PM - 01:30 AM⁺¹")  # type: ignore[method-assign]
        self.assertEqual(backend._current_panel_time_range(), (22 * 60 + 30, 24 * 60 + 90))

    def test_set_task_time_inputs_closes_picker_and_verifies_committed_range(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        backend._run = mock.Mock()  # type: ignore[method-assign]
        backend._overwrite_text_input = mock.Mock()  # type: ignore[method-assign]
        backend._click_button_by_text = mock.Mock()  # type: ignore[method-assign]
        backend._wait = mock.Mock()  # type: ignore[method-assign]
        backend._eval_json = mock.Mock(return_value=["11:40 AM", "01:40 PM"])  # type: ignore[method-assign]
        backend._task_time_picker_is_open = mock.Mock(side_effect=[True, False])  # type: ignore[method-assign]
        backend._close_task_time_picker = mock.Mock()  # type: ignore[method-assign]
        backend._current_panel_time_range = mock.Mock(return_value=(700, 820))  # type: ignore[method-assign]

        backend._set_task_time_inputs(start_minutes=700, end_minutes=820)

        backend._overwrite_text_input.assert_any_call('input[data-cli-time-role="start"]', "11:40 AM")
        backend._overwrite_text_input.assert_any_call('input[data-cli-time-role="end"]', "01:40 PM")
        backend._close_task_time_picker.assert_called_once_with()

    def test_extract_month_year_accepts_spaced_and_compact_headers(self) -> None:
        self.assertEqual(
            StructuredBackend._extract_month_year(["InboxApril2026", "April2026"]),
            ("April", 2026),
        )
        self.assertEqual(
            StructuredBackend._extract_month_year(["April 2026"]),
            ("April", 2026),
        )

    def test_extract_month_year_rejects_non_month_prefixes(self) -> None:
        self.assertEqual(
            StructuredBackend._extract_month_year(["InboxApril2026", "Tasks2026"]),
            (None, None),
        )

    def test_resolve_task_row_prefers_id_then_title(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        rows = [
            {"id": "task-1", "title": "Duplicate"},
            {"id": "task-2", "title": "Duplicate"},
        ]
        backend._read_task_rows = lambda: rows  # type: ignore[method-assign]
        self.assertEqual(backend._resolve_task_row("task-2")["id"], "task-2")
        with self.assertRaises(StructuredAmbiguousError):
            backend._resolve_task_row("Duplicate")

    def test_filter_task_rows_applies_query_and_flags(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        rows = [
            {
                "id": "task-1",
                "title": "Structured task",
                "note": "Has note",
                "subtasks": [{"id": "sub-1", "title": "Child"}],
                "day": "2026-04-02",
                "completed_at": None,
                "is_in_inbox": False,
                "is_all_day": False,
                "is_hidden": False,
                "color": "midnight",
                "symbol": "pin",
            },
            {
                "id": "task-2",
                "title": "Inbox hidden",
                "note": "",
                "subtasks": [],
                "day": None,
                "completed_at": None,
                "is_in_inbox": True,
                "is_all_day": True,
                "is_hidden": True,
                "color": "sunrise",
                "symbol": "moon",
            },
        ]
        filtered = backend._filter_task_rows(
            rows,
            query="child",
            day=None,
            date_from=None,
            date_to=None,
            status="open",
            location="scheduled",
            all_day="exclude",
            color="midnight",
            symbol="pin",
            include_hidden=False,
        )
        self.assertEqual([row["id"] for row in filtered], ["task-1"])

    def test_recurring_matches_day_weekly_interval(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        row = {
            "start_day": "2026-04-01",
            "end_day": "2026-06-01",
            "recurring_type": 2,
            "interval": 1,
            "monday": True,
            "wednesday": True,
            "friday": False,
        }
        self.assertTrue(backend._recurring_matches_day(row, date_cls.fromisoformat("2026-04-06")))
        self.assertFalse(backend._recurring_matches_day(row, date_cls.fromisoformat("2026-04-07")))

    def test_filter_recurring_rows_applies_frequency_query_and_active_day(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        backend.browser_today = lambda: {"day": "2026-04-01", "timezone": "Asia/Shanghai"}  # type: ignore[method-assign]
        rows = [
            {
                "id": "rec-1",
                "title": "Standup",
                "note": "Engineering",
                "subtasks": [{"id": "sub-1", "title": "Prepare"}],
                "recurring_type": 2,
                "interval": 1,
                "start_day": "2026-04-01",
                "end_day": "2026-06-01",
                "monday": True,
                "wednesday": True,
            },
            {
                "id": "rec-2",
                "title": "Archive",
                "note": "",
                "subtasks": [],
                "recurring_type": 1,
                "interval": 1,
                "start_day": "2026-01-01",
                "end_day": "2026-03-01",
            },
        ]
        filtered = backend._filter_recurring_rows(
            rows,
            query="prep",
            frequency="weekly",
            active_on="2026-04-06",
            include_ended=False,
        )
        self.assertEqual([row["id"] for row in filtered], ["rec-1"])

    def test_click_task_card_by_visible_text_returns_backend_bool(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        backend._eval_json = mock.Mock(return_value={"clicked": True, "strategy": "truncated-prefix"})  # type: ignore[method-assign]
        self.assertTrue(backend._click_task_card_by_visible_text("Long task title"))

    def test_occurrence_day_for_recurring_prefers_future_match(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        backend.browser_today = lambda: {"day": "2026-04-02", "timezone": "Asia/Shanghai"}  # type: ignore[method-assign]
        backend._read_occurrence_rows = mock.Mock(return_value=[])  # type: ignore[method-assign]
        row = {
            "id": "rec-1",
            "title": "Standup",
            "start_day": "2026-04-01",
            "end_day": None,
            "recurring_type": 2,
            "interval": 1,
            "monday": False,
            "tuesday": False,
            "wednesday": True,
            "thursday": False,
            "friday": True,
            "saturday": False,
            "sunday": False,
        }
        self.assertEqual(backend._occurrence_day_for_recurring(row), "2026-04-03")

    def test_occurrence_day_for_recurring_uses_last_match_for_ended_series(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        backend.browser_today = lambda: {"day": "2026-05-01", "timezone": "Asia/Shanghai"}  # type: ignore[method-assign]
        backend._read_occurrence_rows = mock.Mock(return_value=[])  # type: ignore[method-assign]
        row = {
            "id": "rec-1",
            "title": "Standup",
            "start_day": "2026-04-01",
            "end_day": "2026-04-10",
            "recurring_type": 2,
            "interval": 1,
            "monday": False,
            "tuesday": False,
            "wednesday": True,
            "thursday": False,
            "friday": True,
            "saturday": False,
            "sunday": False,
        }
        self.assertEqual(backend._occurrence_day_for_recurring(row), "2026-04-10")

    def test_search_recurring_occurrence_day_skips_detached_days(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        backend._read_occurrence_rows = mock.Mock(  # type: ignore[method-assign]
            return_value=[
                {
                    "recurring": "rec-1",
                    "day": "2026-04-02",
                    "_deleted": "0",
                    "is_detached": True,
                    "detached_task": None,
                }
            ]
        )
        row = {
            "id": "rec-1",
            "start_day": "2026-04-01",
            "end_day": "2026-04-05",
            "recurring_type": 1,
            "interval": 1,
        }

        self.assertEqual(
            backend._search_recurring_occurrence_day(
                row,
                anchor=date_cls(2026, 4, 2),
                forward=True,
            ),
            date_cls(2026, 4, 3),
        )

    def test_apply_repeat_settings_reads_selected_weekdays_from_ui(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        backend._click_repeat_button = mock.Mock()  # type: ignore[method-assign]
        backend._adjust_repeat_interval = mock.Mock()  # type: ignore[method-assign]
        backend._set_repeat_start_day = mock.Mock()  # type: ignore[method-assign]
        backend._set_repeat_end_day = mock.Mock()  # type: ignore[method-assign]
        backend._current_repeat_interval = mock.Mock(return_value=1)  # type: ignore[method-assign]
        backend._current_repeat_weekdays = mock.Mock(return_value={"Wed"})  # type: ignore[method-assign]

        backend._apply_repeat_settings(
            frequency="weekly",
            interval=1,
            current_interval=99,
            start_day="2026-04-03",
            current_start_day="2026-04-01",
            weekdays=["Fri"],
            current_weekdays=["Mon"],
            end_day=None,
            current_end_day=None,
        )

        backend._click_repeat_button.assert_any_call("Weekly")
        backend._click_repeat_button.assert_any_call("Wed")
        backend._click_repeat_button.assert_any_call("Fri")
        backend._adjust_repeat_interval.assert_called_once_with(current=1, desired=1)
        backend._set_repeat_start_day.assert_called_once_with(
            start_day="2026-04-03",
            current_start_day="2026-04-01",
        )
        backend._set_repeat_end_day.assert_called_once_with(end_day=None, current_end_day=None)

    def test_open_repeat_end_date_picker_targets_ends_row(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        backend._run = mock.Mock()  # type: ignore[method-assign]
        backend._wait = mock.Mock()  # type: ignore[method-assign]
        backend._repeat_end_date_picker_is_open = mock.Mock(side_effect=[False, True])  # type: ignore[method-assign]

        backend._open_repeat_end_date_picker()

        first_script = backend._run.call_args_list[0][0][0][1]
        self.assertIn("Ends ", first_script)
        self.assertIn("Repeat ends date row not found", first_script)
        backend._wait.assert_called_once_with(150)

    def test_open_recurring_drawer_retries_after_wrong_drawer(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        backend._ensure_main_view = mock.Mock()  # type: ignore[method-assign]
        backend._navigate_to_day = mock.Mock()  # type: ignore[method-assign]
        backend._click_recurring_occurrence_row = mock.Mock()  # type: ignore[method-assign]
        backend._close_task_drawer_if_open = mock.Mock()  # type: ignore[method-assign]
        backend._wait = mock.Mock()  # type: ignore[method-assign]
        backend._current_task_drawer_title = mock.Mock(  # type: ignore[method-assign]
            side_effect=["Wrong recurring", "Standup"]
        )
        row = {
            "id": "rec-1",
            "title": "Standup",
            "start_day": "2026-04-01",
            "end_day": None,
            "recurring_type": 2,
            "interval": 1,
            "start_time": 8.0,
            "duration": 30,
            "monday": True,
        }
        backend._occurrence_day_for_recurring = mock.Mock(return_value="2026-04-07")  # type: ignore[method-assign]

        backend._open_recurring_drawer(row)

        backend._navigate_to_day.assert_called_once_with("2026-04-07")
        self.assertEqual(backend._click_recurring_occurrence_row.call_count, 2)
        backend._close_task_drawer_if_open.assert_called_once()

    def test_assert_task_drawer_title_raises_on_drift(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        backend._current_task_drawer_title = mock.Mock(return_value="Wrong Task")  # type: ignore[method-assign]

        with self.assertRaisesRegex(StructuredBackendError, "Structured drifted to 'Wrong Task'"):
            backend._assert_task_drawer_title({"Expected Task"}, action="editing recurring repeat settings")

    def test_recurring_update_aborts_when_drawer_title_drifts(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        row = {
            "id": "rec-1",
            "title": "Standup",
            "recurring_type": 2,
            "interval": 1,
            "start_day": "2026-04-01",
            "end_day": "2026-04-24",
            "start_time": 9.0,
            "duration": 30,
            "is_all_day": False,
        }
        backend._resolve_recurring_row = mock.Mock(return_value=row)  # type: ignore[method-assign]
        backend._open_recurring_drawer = mock.Mock()  # type: ignore[method-assign]
        backend._open_repeat_panel = mock.Mock()  # type: ignore[method-assign]
        backend._apply_repeat_settings = mock.Mock()  # type: ignore[method-assign]
        backend._close_repeat_panel_if_open = mock.Mock()  # type: ignore[method-assign]
        backend._click_button_by_text = mock.Mock()  # type: ignore[method-assign]
        backend._wait = mock.Mock()  # type: ignore[method-assign]
        backend._current_task_drawer_title = mock.Mock(  # type: ignore[method-assign]
            side_effect=["Standup", "Standup", "Wrong Task"]
        )

        with self.assertRaisesRegex(StructuredBackendError, "Structured drifted to 'Wrong Task'"):
            backend.recurring_update("Standup", frequency="weekly", interval=2)

        backend._click_button_by_text.assert_not_called()

    def test_recurring_update_raises_when_result_does_not_change(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        row = {
            "id": "rec-1",
            "title": "Standup",
            "recurring_type": 2,
            "interval": 1,
            "start_day": "2026-04-01",
            "end_day": "2026-04-24",
            "start_time": 9.0,
            "duration": 30,
            "is_all_day": False,
            "weekdays": ["Fri"],
        }
        backend._resolve_recurring_row = mock.Mock(return_value=row)  # type: ignore[method-assign]
        backend._open_recurring_drawer = mock.Mock()  # type: ignore[method-assign]
        backend._open_repeat_panel = mock.Mock()  # type: ignore[method-assign]
        backend._apply_repeat_settings = mock.Mock()  # type: ignore[method-assign]
        backend._close_repeat_panel_if_open = mock.Mock()  # type: ignore[method-assign]
        backend._click_button_by_text = mock.Mock()  # type: ignore[method-assign]
        backend._wait = mock.Mock()  # type: ignore[method-assign]
        backend._close_task_drawer_if_open = mock.Mock()  # type: ignore[method-assign]
        backend._current_task_drawer_title = mock.Mock(return_value="Standup")  # type: ignore[method-assign]

        with self.assertRaisesRegex(StructuredBackendError, "did not persist the requested recurring update"):
            backend.recurring_update("Standup", interval=2)

        self.assertEqual(
            [call.args[0] for call in backend._click_button_by_text.call_args_list],
            ["Update Task"],
        )

    def test_confirm_repeating_task_scope_clicks_visible_scope_button(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        backend._button_exists = mock.Mock(side_effect=lambda text: text == "Update all tasks")  # type: ignore[method-assign]
        backend._click_button_by_text = mock.Mock()  # type: ignore[method-assign]

        clicked = backend._confirm_repeating_task_scope(action="update", scope="all")

        self.assertTrue(clicked)
        backend._click_button_by_text.assert_called_once_with("Update all tasks")

    def test_recurring_update_confirms_all_scope_before_readback(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        row = {
            "id": "rec-1",
            "title": "Standup",
            "recurring_type": 2,
            "interval": 1,
            "start_day": "2026-04-01",
            "end_day": "2026-04-24",
            "start_time": 9.0,
            "duration": 30,
            "is_all_day": False,
            "weekdays": ["Fri"],
        }
        backend._resolve_recurring_row = mock.Mock(side_effect=[row, row])  # type: ignore[method-assign]
        backend._open_recurring_drawer = mock.Mock()  # type: ignore[method-assign]
        backend._open_repeat_panel = mock.Mock()  # type: ignore[method-assign]
        backend._apply_repeat_settings = mock.Mock()  # type: ignore[method-assign]
        backend._close_repeat_panel_if_open = mock.Mock()  # type: ignore[method-assign]
        backend._confirm_repeating_task_scope = mock.Mock(return_value=True)  # type: ignore[method-assign]
        backend._click_button_by_text = mock.Mock()  # type: ignore[method-assign]
        backend._wait = mock.Mock()  # type: ignore[method-assign]
        backend._close_task_drawer_if_open = mock.Mock()  # type: ignore[method-assign]
        backend._current_task_drawer_title = mock.Mock(return_value="Standup")  # type: ignore[method-assign]

        with self.assertRaisesRegex(StructuredBackendError, "did not persist the requested recurring update"):
            backend.recurring_update("Standup", interval=2)

        backend._confirm_repeating_task_scope.assert_called_once_with(action="update", scope="all")
        backend._close_repeat_panel_if_open.assert_not_called()

    def test_recurring_update_does_not_edit_occurrence_date_row_for_series_start_day(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        row = {
            "id": "rec-1",
            "title": "Standup",
            "recurring_type": 2,
            "interval": 1,
            "start_day": "2026-04-01",
            "end_day": "2026-04-24",
            "start_time": 9.0,
            "duration": 30,
            "is_all_day": False,
            "weekdays": ["Fri"],
        }
        backend._resolve_recurring_row = mock.Mock(side_effect=[row, row])  # type: ignore[method-assign]
        backend._open_recurring_drawer = mock.Mock()  # type: ignore[method-assign]
        backend._open_repeat_panel = mock.Mock()  # type: ignore[method-assign]
        backend._apply_repeat_settings = mock.Mock()  # type: ignore[method-assign]
        backend._close_repeat_panel_if_open = mock.Mock()  # type: ignore[method-assign]
        backend._confirm_repeating_task_scope = mock.Mock(return_value=True)  # type: ignore[method-assign]
        backend._click_button_by_text = mock.Mock()  # type: ignore[method-assign]
        backend._wait = mock.Mock()  # type: ignore[method-assign]
        backend._close_task_drawer_if_open = mock.Mock()  # type: ignore[method-assign]
        backend._current_task_drawer_title = mock.Mock(return_value="Standup")  # type: ignore[method-assign]
        backend._open_task_date_picker = mock.Mock()  # type: ignore[method-assign]
        backend._set_task_date = mock.Mock()  # type: ignore[method-assign]

        with self.assertRaisesRegex(StructuredBackendError, "did not persist the requested recurring update"):
            backend.recurring_update("Standup", start_day="2026-04-10")

        backend._open_task_date_picker.assert_not_called()
        backend._set_task_date.assert_not_called()

    def test_recurring_update_applies_time_before_repeat_and_keeps_panel_open(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        row = {
            "id": "rec-1",
            "title": "Standup",
            "recurring_type": 2,
            "interval": 1,
            "start_day": "2026-04-01",
            "end_day": "2026-04-24",
            "start_time": 9.0,
            "duration": 30,
            "is_all_day": False,
            "weekdays": ["Fri"],
        }
        backend._resolve_recurring_row = mock.Mock(side_effect=[row, row])  # type: ignore[method-assign]
        backend._open_recurring_drawer = mock.Mock()  # type: ignore[method-assign]
        backend._close_repeat_panel_if_open = mock.Mock()  # type: ignore[method-assign]
        backend._confirm_repeating_task_scope = mock.Mock(return_value=True)  # type: ignore[method-assign]
        backend._click_button_by_text = mock.Mock()  # type: ignore[method-assign]
        backend._wait = mock.Mock()  # type: ignore[method-assign]
        backend._close_task_drawer_if_open = mock.Mock()  # type: ignore[method-assign]
        backend._current_task_drawer_title = mock.Mock(return_value="Standup")  # type: ignore[method-assign]
        backend._resolve_task_time_window = mock.Mock(return_value=(600, 660))  # type: ignore[method-assign]
        backend._set_task_time_inputs = mock.Mock()  # type: ignore[method-assign]

        call_order: list[str] = []

        def record(name: str):
            def inner(*args, **kwargs):
                call_order.append(name)
            return inner

        backend._open_task_time_picker = mock.Mock(side_effect=record("time"))  # type: ignore[method-assign]
        backend._open_repeat_panel = mock.Mock(side_effect=record("repeat"))  # type: ignore[method-assign]
        backend._apply_repeat_settings = mock.Mock(side_effect=record("apply"))  # type: ignore[method-assign]

        with self.assertRaisesRegex(StructuredBackendError, "did not persist the requested recurring update"):
            backend.recurring_update("Standup", interval=2, start="10:00 AM", duration=60)

        self.assertEqual(call_order[:3], ["time", "repeat", "apply"])
        backend._close_repeat_panel_if_open.assert_not_called()

    def test_recurring_update_raises_specific_error_for_occurrence_only_confirm_dialog(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        row = {
            "id": "rec-1",
            "title": "Standup",
            "recurring_type": 2,
            "interval": 1,
            "start_day": "2026-04-01",
            "end_day": "2026-04-24",
            "start_time": 9.0,
            "duration": 30,
            "is_all_day": False,
            "weekdays": ["Fri"],
        }
        backend._resolve_recurring_row = mock.Mock(return_value=row)  # type: ignore[method-assign]
        backend._open_recurring_drawer = mock.Mock()  # type: ignore[method-assign]
        backend._open_repeat_panel = mock.Mock()  # type: ignore[method-assign]
        backend._apply_repeat_settings = mock.Mock()  # type: ignore[method-assign]
        backend._close_repeat_panel_if_open = mock.Mock()  # type: ignore[method-assign]
        backend._confirm_repeating_task_scope = mock.Mock(return_value=False)  # type: ignore[method-assign]
        backend._occurrence_only_update_dialog_text = mock.Mock(  # type: ignore[method-assign]
            return_value="Only this task will be updated. Other occurrences are unaffected Cancel Confirm"
        )
        backend._button_exists = mock.Mock(side_effect=lambda label: label == "Cancel")  # type: ignore[method-assign]
        backend._click_button_by_text = mock.Mock()  # type: ignore[method-assign]
        backend._wait = mock.Mock()  # type: ignore[method-assign]
        backend._current_task_drawer_title = mock.Mock(return_value="Standup")  # type: ignore[method-assign]

        with self.assertRaisesRegex(StructuredBackendError, "occurrence-only confirmation dialog"):
            backend.recurring_update("Standup", interval=2)

        backend._click_button_by_text.assert_any_call("Update Task")
        backend._click_button_by_text.assert_any_call("Cancel")

    def test_recurring_delete_clicks_delete_button_and_confirms_scope(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        row = {
            "id": "rec-1",
            "title": "Standup",
            "recurring_type": 2,
            "interval": 1,
            "start_day": "2026-04-01",
            "end_day": "2026-04-24",
            "start_time": 9.0,
            "duration": 30,
            "is_all_day": False,
            "weekdays": ["Fri"],
        }
        backend._resolve_recurring_row = mock.Mock(  # type: ignore[method-assign]
            side_effect=[row, row, StructuredNotFoundError("missing")]
        )
        backend._occurrence_day_for_recurring = mock.Mock(return_value="2026-04-04")  # type: ignore[method-assign]
        backend._open_recurring_drawer = mock.Mock()  # type: ignore[method-assign]
        backend._click_task_delete_button = mock.Mock()  # type: ignore[method-assign]
        backend._confirm_repeating_task_scope = mock.Mock(return_value=True)  # type: ignore[method-assign]
        backend._wait = mock.Mock()  # type: ignore[method-assign]

        payload = backend.recurring_delete("Standup", scope="all")

        self.assertEqual(payload, {"deleted": True, "scope": "all", "reference": "Standup"})
        backend._click_task_delete_button.assert_called_once_with()
        backend._confirm_repeating_task_scope.assert_called_once_with(action="delete", scope="all", required=True)

    def test_recurring_delete_scope_one_waits_until_occurrence_is_gone(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        row = {
            "id": "rec-1",
            "title": "Standup",
            "recurring_type": 2,
            "interval": 1,
            "start_day": "2026-04-01",
            "end_day": "2026-04-24",
            "start_time": 9.0,
            "duration": 30,
            "is_all_day": False,
            "weekdays": ["Fri"],
        }
        backend._resolve_recurring_row = mock.Mock(  # type: ignore[method-assign]
            side_effect=[row, row, row]
        )
        backend._occurrence_day_for_recurring = mock.Mock(return_value="2026-04-04")  # type: ignore[method-assign]
        backend._open_recurring_drawer = mock.Mock()  # type: ignore[method-assign]
        backend._click_task_delete_button = mock.Mock()  # type: ignore[method-assign]
        backend._confirm_repeating_task_scope = mock.Mock(return_value=True)  # type: ignore[method-assign]
        backend._has_active_occurrence_for_recurring_day = mock.Mock(side_effect=[True, False])  # type: ignore[method-assign]
        backend._wait = mock.Mock()  # type: ignore[method-assign]

        payload = backend.recurring_delete("Standup", scope="one")

        self.assertEqual(payload["deleted"], True)
        self.assertEqual(payload["scope"], "one")
        self.assertEqual(payload["reference"], "Standup")
        self.assertEqual(payload["recurring"]["id"], "rec-1")
        backend._has_active_occurrence_for_recurring_day.assert_has_calls(
            [
                mock.call("rec-1", "2026-04-04"),
                mock.call("rec-1", "2026-04-04"),
            ]
        )

    def test_recurring_delete_scope_future_waits_until_no_future_occurrence_remains(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        row = {
            "id": "rec-1",
            "title": "Standup",
            "recurring_type": 2,
            "interval": 1,
            "start_day": "2026-04-01",
            "end_day": "2026-04-24",
            "start_time": 9.0,
            "duration": 30,
            "is_all_day": False,
            "weekdays": ["Fri"],
        }
        updated_row = dict(row, end_day="2026-04-03")
        backend._resolve_recurring_row = mock.Mock(  # type: ignore[method-assign]
            side_effect=[row, updated_row, updated_row]
        )
        backend._occurrence_day_for_recurring = mock.Mock(return_value="2026-04-04")  # type: ignore[method-assign]
        backend._open_recurring_drawer = mock.Mock()  # type: ignore[method-assign]
        backend._click_task_delete_button = mock.Mock()  # type: ignore[method-assign]
        backend._confirm_repeating_task_scope = mock.Mock(return_value=True)  # type: ignore[method-assign]
        backend._search_recurring_occurrence_day = mock.Mock(  # type: ignore[method-assign]
            side_effect=[date_cls(2026, 4, 11), None]
        )
        backend._wait = mock.Mock()  # type: ignore[method-assign]

        payload = backend.recurring_delete("Standup", scope="future")

        self.assertEqual(payload["deleted"], True)
        self.assertEqual(payload["scope"], "future")
        self.assertEqual(payload["reference"], "Standup")
        self.assertEqual(payload["recurring"]["end_day"], "2026-04-03")

    def test_recurring_delete_scope_all_raises_clear_error_when_no_visible_occurrence_remains(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        row = {
            "id": "rec-1",
            "title": "Standup",
            "recurring_type": 1,
            "interval": 1,
            "start_day": "2026-04-03",
            "end_day": "2026-04-02",
            "start_time": 9.0,
            "duration": 30,
            "is_all_day": False,
            "weekdays": [],
        }
        backend._resolve_recurring_row = mock.Mock(return_value=row)  # type: ignore[method-assign]
        backend._occurrence_day_for_recurring = mock.Mock(  # type: ignore[method-assign]
            side_effect=StructuredBackendError("Could not find a visible occurrence day")
        )

        with self.assertRaisesRegex(StructuredBackendError, "refused to approximate cleanup"):
            backend.recurring_delete("rec-1", scope="all")

    def test_close_task_drawer_if_open_retries_until_hidden(self) -> None:
        backend = StructuredBackend(session="structured-test", profile="/tmp/profile", agent_browser="agent-browser")
        backend._click_task_drawer_close_button = mock.Mock()  # type: ignore[method-assign]
        backend._wait = mock.Mock()  # type: ignore[method-assign]
        backend._ui_state = mock.Mock(  # type: ignore[method-assign]
            side_effect=[
                {"has_task_drawer": True},
                {"has_task_drawer": True},
                {"has_task_drawer": False},
            ]
        )

        backend._close_task_drawer_if_open()

        self.assertEqual(backend._click_task_drawer_close_button.call_count, 2)
        self.assertEqual(backend._wait.call_count, 2)


if __name__ == "__main__":
    unittest.main()
