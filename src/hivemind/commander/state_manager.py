"""Commander — state manager: finite state machine for task lifecycle."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class TaskState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.IDLE: {TaskState.PLANNING},
    TaskState.PLANNING: {TaskState.AWAITING_APPROVAL, TaskState.EXECUTING, TaskState.BLOCKED},
    TaskState.AWAITING_APPROVAL: {TaskState.EXECUTING, TaskState.BLOCKED},
    TaskState.EXECUTING: {TaskState.VERIFYING, TaskState.FAILED, TaskState.COMPLETED},
    TaskState.VERIFYING: {TaskState.COMPLETED, TaskState.FAILED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.BLOCKED: set(),
}


class Task(BaseModel):
    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    tool_name: str
    params_summary: str = ""
    state: TaskState = TaskState.IDLE
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    context: dict = Field(default_factory=dict)
    error: str = ""


class StateManager:
    """Manages task state transitions with validation."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tasks: dict[str, Task] = {}

    async def create_task(self, tool_name: str, params: dict) -> Task:
        task = Task(tool_name=tool_name, params_summary=str(params)[:200], state=TaskState.IDLE)
        async with self._lock: self._tasks[task.task_id] = task
        return task

    async def transition(self, task_id: str, to_state: TaskState, error: str = "") -> Task:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None: raise ValueError(f"Unknown task: {task_id}")
            valid = TRANSITIONS.get(task.state, set())
            if to_state not in valid:
                raise ValueError(f"Invalid transition: {task.state.value} → {to_state.value}. Allowed: {[s.value for s in valid]}")
            task.state = to_state
            task.updated_at = datetime.now(timezone.utc).isoformat()
            if error: task.error = error
            return task

    async def get_task(self, task_id: str) -> Task | None:
        async with self._lock: return self._tasks.get(task_id)

    async def active_count(self) -> int:
        async with self._lock:
            active = {TaskState.IDLE, TaskState.PLANNING, TaskState.EXECUTING, TaskState.VERIFYING, TaskState.AWAITING_APPROVAL}
            return sum(1 for t in self._tasks.values() if t.state in active)
