from datetime import datetime, timedelta

from digital_pet.task_store import TaskStore


def test_due_task_is_returned_once(tmp_path):
    store = TaskStore(tmp_path)
    task = store.add("test reminder", datetime.now() - timedelta(minutes=1))

    assert [item.task_id for item in store.take_due(datetime.now())] == [task.task_id]
    assert store.take_due(datetime.now()) == []


def test_reminder_can_be_updated_then_cancelled(tmp_path):
    store = TaskStore(tmp_path)
    task = store.add("old title", datetime.now() + timedelta(days=1))
    updated = store.update(task.task_id, title="new title", due_at=datetime(2026, 7, 25, 9, 0))

    assert updated.title == "new title"
    assert updated.due_datetime == datetime(2026, 7, 25, 9, 0)
    cancelled = store.cancel(task.task_id)
    assert cancelled.cancelled
    assert store.pending_tasks() == []
