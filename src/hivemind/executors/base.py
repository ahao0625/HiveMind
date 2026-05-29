"""Executor — abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field
from hivemind.commander.intent_refiner import RefinedIntent


class ExecutorResult(BaseModel):
    success: bool
    output: str = ""
    error: str = ""
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    metadata: dict = Field(default_factory=dict)


class Executor(ABC):
    @abstractmethod
    async def execute(self, intent: RefinedIntent) -> ExecutorResult: ...
    @abstractmethod
    def can_handle(self, tool_name: str) -> bool: ...
