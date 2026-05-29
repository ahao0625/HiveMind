"""Verification — abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field
from hivemind.commander.intent_refiner import RefinedIntent
from hivemind.executors.base import ExecutorResult


class VerifyResult(BaseModel):
    passed: bool
    verifier_name: str
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    score: float = 1.0


class Verifier(ABC):
    @abstractmethod
    async def verify(self, intent: RefinedIntent, result: ExecutorResult) -> VerifyResult: ...
