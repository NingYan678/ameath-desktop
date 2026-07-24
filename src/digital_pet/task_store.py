from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4


@dataclass
class ReminderTask:
    task_id: str
    title: str
    due_at: str
    completed: bool = False
    cancelled: bool = False

    @property
    def due_datetime(self) -> datetime:
        return datetime.fromisoformat(self.due_at)


class TaskStore:
    def __init__(self, data_root: Path) -> None:
        self.path = data_root / "reminders.json"

    def list_tasks(self) -> list[ReminderTask]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [ReminderTask(**item) for item in raw if isinstance(item, dict)]
        except (json.JSONDecodeError, OSError, TypeError):
            return []

    def add(self, title: str, due_at: datetime) -> ReminderTask:
        task = ReminderTask(task_id=uuid4().hex, title=title.strip(), due_at=due_at.isoformat(timespec="minutes"))
        tasks = self.list_tasks()
        tasks.append(task)
        self._save(tasks)
        return task

    def update(self, task_id: str, *, title: str | None = None, due_at: datetime | None = None) -> ReminderTask:
        task = self.get(task_id)
        if task is None or task.completed or task.cancelled:
            raise ValueError("Reminder is unavailable for update.")
        if title is not None:
            cleaned = title.strip()
            if not cleaned:
                raise ValueError("Reminder title cannot be empty.")
            task.title = cleaned
        if due_at is not None:
            task.due_at = due_at.isoformat(timespec="minutes")
        self._replace(task)
        return task

    def cancel(self, task_id: str) -> ReminderTask:
        task = self.get(task_id)
        if task is None or task.completed or task.cancelled:
            raise ValueError("Reminder is unavailable for cancellation.")
        task.cancelled = True
        self._replace(task)
        return task

    def get(self, task_id: str) -> ReminderTask | None:
        return next((task for task in self.list_tasks() if task.task_id == task_id), None)

    def pending_tasks(self) -> list[ReminderTask]:
        return [task for task in self.list_tasks() if not task.completed and not task.cancelled]

    def take_due(self, now: datetime) -> list[ReminderTask]:
        tasks = self.list_tasks()
        due = [task for task in tasks if not task.completed and not task.cancelled and task.due_datetime <= now]
        if due:
            due_ids = {task.task_id for task in due}
            for task in tasks:
                if task.task_id in due_ids:
                    task.completed = True
            self._save(tasks)
        return due

    def pending_summary(self) -> str:
        pending = self.pending_tasks()
        if not pending:
            return "\u6682\u65e0\u5f85\u529e\u63d0\u9192\u3002"
        return "\n".join(f"{task.due_datetime:%m-%d %H:%M}  {task.title}" for task in pending[:8])

    def _save(self, tasks: list[ReminderTask]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(task) for task in tasks]
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _replace(self, replacement: ReminderTask) -> None:
        tasks = self.list_tasks()
        for index, task in enumerate(tasks):
            if task.task_id == replacement.task_id:
                tasks[index] = replacement
                self._save(tasks)
                return
        raise ValueError("Reminder not found.")
