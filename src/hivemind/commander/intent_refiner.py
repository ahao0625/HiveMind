"""Commander — intent refiner: disambiguates raw tool calls into structured intents."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RefinedIntent(BaseModel):
    """Structured representation of a tool call after refinement."""
    tool_name: str
    action_type: Literal["read", "write", "delete", "execute", "query"]
    target: str = ""
    parameters: dict = Field(default_factory=dict)
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"
    estimated_impact: str = ""
    system_classification: Literal["system1", "system2"] = "system2"


class IntentRefiner:
    """Classifies raw tool parameters into a RefinedIntent using heuristics."""

    SYSTEM1_TOOLS: set[str] = {"read_file", "list_files", "recall_memory", "get_metrics", "get_constitution", "get_audit_trail"}
    SYSTEM2_TOOLS: set[str] = {"write_file", "delete_file", "run_command", "http_get", "http_post", "http_put", "http_delete", "store_memory"}

    def refine(self, tool_name: str, params: dict) -> RefinedIntent:
        action_type = self._classify_action(tool_name)
        target = self._extract_target(tool_name, params)
        risk_level = self._assess_risk(tool_name, params, action_type)
        system_class = self._classify_system(tool_name, risk_level)
        return RefinedIntent(
            tool_name=tool_name, action_type=action_type, target=target,
            parameters=params, risk_level=risk_level,
            estimated_impact=self._describe_impact(action_type, risk_level, target),
            system_classification=system_class,
        )

    def _classify_action(self, tool_name: str) -> str:
        if tool_name in ("read_file", "list_files", "recall_memory", "http_get"): return "read"
        if tool_name in ("write_file", "store_memory"): return "write"
        if tool_name == "delete_file": return "delete"
        if tool_name == "run_command": return "execute"
        if tool_name.startswith("http_"): return "query"
        return "read"

    def _extract_target(self, tool_name: str, params: dict) -> str:
        for key in ("path", "url", "command", "key", "query"):
            if key in params and isinstance(params[key], str):
                return params[key]
        return str(params)

    def _assess_risk(self, tool_name: str, params: dict, action_type: str) -> str:
        if action_type == "delete": return "high"
        if action_type == "execute":
            cmd = params.get("command", "")
            if isinstance(cmd, str) and any(x in cmd for x in ("rm ", "sudo", "chmod", "chown")):
                return "critical"
            return "high"
        if action_type == "write":
            path = str(params.get("path", ""))
            if any(d in path for d in ("/etc", "/usr", "/bin", "/boot", "/root")): return "critical"
            return "medium"
        if action_type == "read":
            path = str(params.get("path", ""))
            if any(d in path for d in ("/etc", "/proc", "/sys")): return "medium"
            return "low"
        if action_type == "query": return "medium"
        return "low"

    def _classify_system(self, tool_name: str, risk_level: str) -> str:
        if tool_name in self.SYSTEM1_TOOLS and risk_level == "low": return "system1"
        return "system2"

    def _describe_impact(self, action_type: str, risk_level: str, target: str) -> str:
        m = {
            ("read", "low"): f"Read-only access to {target or 'resource'}",
            ("read", "medium"): f"Read from potentially sensitive location: {target}",
            ("write", "medium"): f"Write new content to {target}",
            ("write", "critical"): f"Write to system-critical path: {target}",
            ("delete", "high"): f"Delete file at {target}",
            ("execute", "high"): f"Execute command targeting {target}",
            ("execute", "critical"): f"Execute destructive command: {target}",
            ("query", "medium"): f"External HTTP query to {target}",
        }
        return m.get((action_type, risk_level), f"{action_type} operation on {target}")
