"""Commander — state manager: finite state machine for task lifecycle.

v2.0: Added ROLLING_BACK, ESCALATED states, checkpoint/rollback support,
and failure counting with auto-escalation.
"""

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
    ROLLING_BACK = "rolling_back"  # v2.0
    ESCALATED = "escalated"  # v2.0


TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.IDLE: {TaskState.PLANNING},
    TaskState.PLANNING: {TaskState.AWAITING_APPROVAL, TaskState.EXECUTING, TaskState.BLOCKED},
    TaskState.AWAITING_APPROVAL: {TaskState.EXECUTING, TaskState.BLOCKED},
    TaskState.EXECUTING: {TaskState.VERIFYING, TaskState.FAILED, TaskState.COMPLETED, TaskState.ESCALATED},
    TaskState.VERIFYING: {TaskState.COMPLETED, TaskState.FAILED, TaskState.ROLLING_BACK},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: {TaskState.ROLLING_BACK, TaskState.ESCALATED, TaskState.IDLE},
    TaskState.BLOCKED: {TaskState.ESCALATED, TaskState.IDLE},
    TaskState.ROLLING_BACK: {TaskState.IDLE, TaskState.ESCALATED},
    TaskState.ESCALATED: {TaskState.IDLE},
}


class Checkpoint(BaseModel, frozen=True):
    """v2.0: immutable snapshot of task state for rollback."""
    checkpoint_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str
    state: TaskState
    params_snapshot: str = ""  # JSON serialized
    memory_snapshot: str = ""  # JSON serialized
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Task(BaseModel):
    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    tool_name: str
    params_summary: str = ""
    state: TaskState = TaskState.IDLE
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    context: dict = Field(default_factory=dict)
    error: str = ""
    # v2.0 fields
    failure_count: int = 0
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    escalation_reason: str = ""


class StateManager:
    """Manages task state transitions with validation.

    v2.0: Supports checkpoint/rollback, failure counting, and auto-escalation.
    """

    def __init__(self, escalation_threshold: int = 3) -> None:
        self._lock = asyncio.Lock()
        self._tasks: dict[str, Task] = {}
        self.escalation_threshold = escalation_threshold

    async def create_task(self, tool_name: str, params: dict) -> Task:
        task = Task(tool_name=tool_name, params_summary=str(params)[:200], state=TaskState.IDLE)
        async with self._lock: self._tasks[task.task_id] = task
        return task

    async def transition(self, task_id: str, to_state: TaskState, error: str = "") -> Task:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise ValueError(f"Unknown task: {task_id}")
            valid = TRANSITIONS.get(task.state, set())
            if to_state not in valid:
                raise ValueError(
                    f"Invalid transition: {task.state.value} → {to_state.value}. "
                    f"Allowed: {[s.value for s in valid]}"
                )
            task.state = to_state
            task.updated_at = datetime.now(timezone.utc).isoformat()
            if error:
                task.error = error
            return task

    async def get_task(self, task_id: str) -> Task | None:
        async with self._lock:
            return self._tasks.get(task_id)

    async def active_count(self) -> int:
        async with self._lock:
            active = {
                TaskState.IDLE, TaskState.PLANNING, TaskState.EXECUTING,
                TaskState.VERIFYING, TaskState.AWAITING_APPROVAL,
            }
            return sum(1 for t in self._tasks.values() if t.state in active)

    # ── v2.0: Checkpoint & Rollback ─────────────────────────────

    async def save_checkpoint(
        self, task_id: str, params: str = "", memory: str = "",
    ) -> Checkpoint | None:
        """Save an immutable checkpoint for later rollback."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            cp = Checkpoint(
                task_id=task_id,
                state=task.state,
                params_snapshot=params,
                memory_snapshot=memory,
            )
            task.checkpoints.append(cp)
            return cp

    async def restore_checkpoint(self, task_id: str) -> Checkpoint | None:
        """Restore the last checkpoint (used before retry)."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None or not task.checkpoints:
                return None
            return task.checkpoints[-1]

    async def rollback(self, task_id: str) -> Task:
        """Transition to ROLLING_BACK state."""
        return await self.transition(task_id, TaskState.ROLLING_BACK)

    async def escalate(self, task_id: str, reason: str = "") -> Task:
        """Transition to ESCALATED state with reason."""
        async with self._lock:
            task = await self.transition(task_id, TaskState.ESCALATED)
            task.escalation_reason = reason
            return task

    async def record_failure(self, task_id: str) -> Task:
        """Increment failure count; auto-escalate if threshold exceeded."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise ValueError(f"Unknown task: {task_id}")
            task.failure_count += 1
            if task.failure_count >= self.escalation_threshold:
                task.escalation_reason = (
                    f"Auto-escalated after {task.failure_count} failures "
                    f"(threshold: {self.escalation_threshold})"
                )
                return await self.escalate(task_id, task.escalation_reason)
            return task
