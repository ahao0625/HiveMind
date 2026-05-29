"""Commander — arbiter: final decision authority after rule evaluation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from hivemind.commander.intent_refiner import RefinedIntent
from hivemind.commander.rule_engine import RuleEngineResult, RuleEngine


class Decision(BaseModel):
    approved: bool
    requires_human_approval: bool = False
    reasoning: str = ""
    risk_assessment: Literal["safe", "caution", "dangerous"] = "safe"
    suggested_mitigations: list[str] = Field(default_factory=list)
    execution_mode: Literal["system1", "system2"] = "system2"


class Arbiter:
    """Final go/no-go decision. Logic: hard gate veto → critical risk → score thresholds."""

    def __init__(self, rule_engine: RuleEngine) -> None:
        self._engine = rule_engine

    def decide(self, rule_result: RuleEngineResult, intent: RefinedIntent) -> Decision:
        # 1. Hard gate veto
        if rule_result.blocked:
            return Decision(approved=False, reasoning=rule_result.block_reason,
                            risk_assessment="dangerous",
                            suggested_mitigations=["Review the blocked operation and consider alternatives."])

        # 2. Critical risk → human approval
        if intent.risk_level == "critical":
            return Decision(approved=False, requires_human_approval=True,
                            reasoning=f"Critical-risk operation: {intent.estimated_impact}",
                            risk_assessment="dangerous",
                            suggested_mitigations=["This operation requires explicit human approval.",
                                                   "Consider whether the same goal can be achieved with lower risk."],
                            execution_mode="system2")

        score = rule_result.overall_score
        approval = self._engine.approval_threshold
        human = self._engine.human_threshold

        # 3. Score below approval threshold
        if score < approval:
            return Decision(approved=False,
                            reasoning=f"Overall safety score {score:.2f} below approval threshold {approval:.2f}",
                            risk_assessment="dangerous" if score < 0.3 else "caution",
                            suggested_mitigations=[f"Score {score:.2f} < {approval:.2f} (approval). Narrow scope or use safer alternatives."])

        # 4. Score below human threshold
        if score < human:
            risk = "dangerous" if score < approval + 0.1 else "caution"
            return Decision(approved=True, requires_human_approval=True,
                            reasoning=f"Safety score {score:.2f} requires human review (threshold: {human:.2f})",
                            risk_assessment=risk,
                            suggested_mitigations=[f"Score breakdown: {rule_result.soft_scores}"],
                            execution_mode="system2")

        # 5. Approved
        risk = "safe" if score >= 0.75 else "caution"
        return Decision(approved=True, reasoning=f"All gates passed, safety score {score:.2f}",
                        risk_assessment=risk, execution_mode=intent.system_classification)
