"""Tests for HiveMind Rule Engine — hard gates and soft scoring."""

import pytest
from hivemind.config import HiveMindConfig, Constitution
from hivemind.commander.intent_refiner import IntentRefiner
from hivemind.commander.rule_engine import RuleEngine


@pytest.fixture
def constitution() -> Constitution:
    return HiveMindConfig.default_constitution()

@pytest.fixture
def engine(constitution: Constitution) -> RuleEngine:
    return RuleEngine(constitution)

@pytest.fixture
def refiner() -> IntentRefiner:
    return IntentRefiner()


class TestHardGates:
    def test_blocks_destructive_rm(self, engine, refiner):
        intent = refiner.refine("run_command", {"command": "rm -rf / important_data"})
        result = engine.evaluate(intent)
        assert result.blocked is True

    def test_blocks_sensitive_path(self, engine, refiner):
        intent = refiner.refine("read_file", {"path": "/etc/passwd"})
        result = engine.evaluate(intent)
        assert result.blocked is True

    def test_blocks_write_outside_sandbox(self, engine, refiner):
        intent = refiner.refine("write_file", {"path": "/etc/hosts"})
        result = engine.evaluate(intent, sandbox_root="/tmp/hivemind-sandbox")
        assert result.blocked is True

    def test_allows_safe_read(self, engine, refiner):
        intent = refiner.refine("read_file", {"path": "test.txt"})
        result = engine.evaluate(intent)
        assert result.blocked is False
        assert result.overall_score > 0.4

    def test_allows_safe_write_in_sandbox(self, engine, refiner):
        intent = refiner.refine("write_file", {"path": "output.txt", "content": "hello"})
        result = engine.evaluate(intent, sandbox_root="/tmp/hivemind-sandbox")
        assert result.blocked is False

    def test_blocks_fork_bomb(self, engine, refiner):
        intent = refiner.refine("run_command", {"command": ":(){ :|:& };:"})
        result = engine.evaluate(intent)
        assert result.blocked is True

    def test_blocks_chmod_system(self, engine, refiner):
        intent = refiner.refine("run_command", {"command": "chmod 777 /"})
        result = engine.evaluate(intent)
        assert result.blocked is True


class TestSoftScoring:
    def test_read_scores_higher_than_write(self, engine, refiner):
        r = engine.evaluate(refiner.refine("read_file", {"path": "test.txt"}))
        w = engine.evaluate(refiner.refine("write_file", {"path": "test.txt", "content": "x"}))
        assert r.overall_score > w.overall_score

    def test_delete_scores_lowest(self, engine, refiner):
        r = engine.evaluate(refiner.refine("read_file", {"path": "test.txt"}))
        d = engine.evaluate(refiner.refine("delete_file", {"path": "test.txt"}))
        assert r.overall_score > d.overall_score

    def test_soft_scores_returned(self, engine, refiner):
        result = engine.evaluate(refiner.refine("read_file", {"path": "test.txt"}))
        assert len(result.soft_scores) >= 5
        assert all(0.0 <= v <= 1.0 for v in result.soft_scores.values())


class TestArbiter:
    def test_approves_safe_operation(self, engine, refiner):
        from hivemind.commander.arbiter import Arbiter
        a = Arbiter(engine)
        intent = refiner.refine("read_file", {"path": "test.txt"})
        d = a.decide(engine.evaluate(intent), intent)
        assert d.approved is True
        assert d.requires_human_approval is False

    def test_blocks_destructive_operation(self, engine, refiner):
        from hivemind.commander.arbiter import Arbiter
        a = Arbiter(engine)
        intent = refiner.refine("run_command", {"command": "rm -rf /"})
        d = a.decide(engine.evaluate(intent), intent)
        assert d.approved is False
