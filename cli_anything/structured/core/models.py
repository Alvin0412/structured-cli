from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SubtaskInfo:
    id: str
    title: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InboxTask:
    id: str
    title: str
    completed_at: str | None
    modified_at: str | None

    @property
    def is_completed(self) -> bool:
        return bool(self.completed_at)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_completed"] = self.is_completed
        return data


@dataclass
class TaskInfo:
    id: str
    title: str
    day: str | None
    start_time: float | None
    duration: int | None
    completed_at: str | None
    modified_at: str | None
    is_in_inbox: bool
    is_all_day: bool
    note: str | None
    color: str | None
    symbol: str | None
    is_hidden: bool = False
    subtasks: list[SubtaskInfo] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_completed(self) -> bool:
        return bool(self.completed_at)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_completed"] = self.is_completed
        return data


@dataclass
class RecurringInfo:
    id: str
    title: str
    frequency: str
    interval: int
    start_day: str | None
    end_day: str | None
    start_time: float | None
    duration: int | None
    is_all_day: bool
    note: str | None
    color: str | None
    symbol: str | None
    modified_at: str | None
    weekdays: list[str] = field(default_factory=list)
    subtasks: list[SubtaskInfo] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgendaItem:
    id: str
    source: str
    title: str
    day: str
    start_time: float | None
    duration: int | None
    completed_at: str | None
    color: str | None
    symbol: str | None
    note: str | None

    @property
    def is_completed(self) -> bool:
        return bool(self.completed_at)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_completed"] = self.is_completed
        return data


@dataclass
class SettingsInfo:
    user_id: str
    theme: str
    layout: str
    first_weekday: int | None
    did_complete_onboarding: bool
    cloud_terms_date: str | None
    timezone: str | None
    duration_presets: list[int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
