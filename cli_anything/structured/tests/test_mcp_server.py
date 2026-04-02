from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from mcp.server.fastmcp.exceptions import ToolError

from cli_anything.structured.mcp_server import (
    server,
    structured_recurring_delete,
    structured_status,
    structured_task_list,
    structured_task_note_get,
)
from cli_anything.structured.utils import StructuredBackendError


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def session_status(self):
        self.calls.append(("session_status", (), {}))
        return {"logged_in": True, "url": "https://web.structured.app/"}

    def task_list(self, **kwargs):
        self.calls.append(("task_list", (), kwargs))
        return []

    def task_note_get(self, reference: str):
        self.calls.append(("task_note_get", (reference,), {}))
        return "hello"

    def recurring_delete(self, reference: str, *, scope: str = "all"):
        self.calls.append(("recurring_delete", (reference,), {"scope": scope}))
        return {"deleted": True, "reference": reference, "scope": scope}


class McpServerTests(unittest.TestCase):
    def test_server_lists_only_stable_tools(self) -> None:
        names = {tool.name for tool in asyncio.run(server.list_tools())}
        self.assertEqual(
            names,
            {
                "structured_status",
                "structured_inbox_list",
                "structured_inbox_add",
                "structured_inbox_update",
                "structured_inbox_delete",
                "structured_agenda_list",
                "structured_settings_show",
                "structured_task_list",
                "structured_task_search",
                "structured_task_show",
                "structured_task_create",
                "structured_task_update",
                "structured_task_delete",
                "structured_task_complete",
                "structured_task_restore",
                "structured_task_note_get",
                "structured_task_note_set",
                "structured_task_note_clear",
                "structured_task_set_all_day",
                "structured_task_subtask_list",
                "structured_task_subtask_add",
                "structured_recurring_list",
                "structured_recurring_search",
                "structured_recurring_show",
                "structured_recurring_create",
                "structured_recurring_update",
                "structured_recurring_delete",
            },
        )

    def test_structured_status_uses_backend_singleton(self) -> None:
        backend = FakeBackend()
        with mock.patch("cli_anything.structured.mcp_server._get_backend", return_value=backend):
            payload = structured_status()

        self.assertEqual(payload["logged_in"], True)
        self.assertEqual(backend.calls, [("session_status", (), {})])

    def test_task_list_maps_optional_all_day_filter(self) -> None:
        backend = FakeBackend()
        with mock.patch("cli_anything.structured.mcp_server._get_backend", return_value=backend):
            structured_task_list(all_day=True)
            structured_task_list(all_day=False)
            structured_task_list(all_day=None)

        self.assertEqual(
            [call[2]["all_day"] for call in backend.calls],
            ["only", "exclude", "all"],
        )

    def test_task_note_get_wraps_note_payload(self) -> None:
        backend = FakeBackend()
        with mock.patch("cli_anything.structured.mcp_server._get_backend", return_value=backend):
            payload = structured_task_note_get("task-1")

        self.assertEqual(payload, {"reference": "task-1", "note": "hello"})

    def test_recurring_delete_forwards_scope(self) -> None:
        backend = FakeBackend()
        with mock.patch("cli_anything.structured.mcp_server._get_backend", return_value=backend):
            payload = structured_recurring_delete("rec-1", scope="future")

        self.assertEqual(payload["scope"], "future")
        self.assertEqual(
            backend.calls[-1],
            ("recurring_delete", ("rec-1",), {"scope": "future"}),
        )

    def test_backend_errors_are_translated_to_tool_errors(self) -> None:
        backend = FakeBackend()
        backend.task_note_get = mock.Mock(side_effect=StructuredBackendError("planner unavailable"))  # type: ignore[method-assign]
        with mock.patch("cli_anything.structured.mcp_server._get_backend", return_value=backend):
            with self.assertRaises(ToolError):
                structured_task_note_get("task-1")


if __name__ == "__main__":
    unittest.main()
