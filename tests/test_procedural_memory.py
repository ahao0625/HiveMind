"""Tests for v2.0 Procedural Memory — env snapshots, validation, promote/demote."""

import os
import pytest
from hivemind.memory.procedural import ProceduralMemory, EnvSnapshot, GameRecord


@pytest.fixture
def mem_path():
    return os.path.join(os.environ.get("TMPDIR", "/tmp"), "test-proc-mem.json")


@pytest.fixture
def pm(mem_path):
    pm = ProceduralMemory(max_records=100, persistence_path=mem_path)
    yield pm
    if os.path.exists(mem_path):
        os.remove(mem_path)


class TestEnvSnapshot:
    def test_snapshot_has_required_fields(self):
        env = ProceduralMemory.snapshot_environment()
        assert len(env.os_name) > 0
        assert len(env.os_version) > 0
        assert env.python_version.startswith("3")
        assert "PATH" in env.key_env_vars

    def test_snapshot_is_frozen(self):
        env = ProceduralMemory.snapshot_environment()
        with pytest.raises(Exception):
            env.os_name = "changed"


class TestRecordAndRetrieve:
    def test_record_creates_game_record(self, pm):
        rec = pm.record("read_file", ("path", "test.txt"), "content here", success=True, latency_ms=5.0)
        assert rec.tool_name == "read_file"
        assert rec.use_count == 1
        assert rec.success is True

    def test_record_increments_existing(self, pm):
        pm.record("read_file", ("path", "x.txt"), "data", success=True)
        rec2 = pm.record("read_file", ("path", "x.txt"), "data2", success=True)
        assert rec2.use_count == 2

    def test_get_returns_record(self, pm):
        pm.record("list_files", ("path", "/"), "f1\nf2", success=True)
        rec = pm.get("list_files", ("path", "/"))
        assert rec is not None
        assert rec.tool_name == "list_files"

    def test_get_returns_none_for_unknown(self, pm):
        assert pm.get("unknown_tool", ("a", "b")) is None


class TestValidateBeforeUse:
    def test_current_env_matches(self, pm):
        pm.record("read_file", ("path", "a.txt"), "hello", success=True)
        is_valid, reason = pm.validate_before_use("read_file", ("path", "a.txt"))
        assert is_valid is True
        assert reason == "env_match"

    def test_unknown_params_returns_false(self, pm):
        is_valid, reason = pm.validate_before_use("read_file", ("path", "nonexistent.txt"))
        assert is_valid is False
        assert reason == "no_cached_record"


class TestPromoteAndDemote:
    def test_promote_increments_use_count(self, pm):
        pm.record("read_file", ("path", "p.txt"), "data", success=True)
        promoted = pm.promote("read_file", ("path", "p.txt"))
        assert promoted is not None
        assert promoted.use_count == 2

    def test_promote_unknown_returns_none(self, pm):
        assert pm.promote("unknown", ("a",)) is None

    def test_demote_removes_record(self, pm):
        pm.record("read_file", ("path", "d.txt"), "data", success=True)
        pm.demote("read_file", ("path", "d.txt"))
        assert pm.get("read_file", ("path", "d.txt")) is None


class TestGetBestMatch:
    def test_exact_match_preferred(self, pm):
        pm.record("read_file", ("path", "exact.txt"), "aaa", success=True)
        best = pm.get_best_match("read_file", ("path", "exact.txt"))
        assert best is not None
        assert best.use_count == 1

    def test_fallback_highest_use_count(self, pm):
        pm.record("read_file", ("path", "a.txt"), "aaa", success=True, latency_ms=1.0)
        pm.record("read_file", ("path", "b.txt"), "bbb", success=True, latency_ms=1.0)
        pm.promote("read_file", ("path", "b.txt"))
        best = pm.get_best_match("read_file", ("path", "c.txt"))
        assert best is not None
        assert best.use_count == 2

    def test_no_match_returns_none(self, pm):
        assert pm.get_best_match("nonexistent", ("a",)) is None


class TestPersistence:
    def test_save_and_reload(self, mem_path):
        pm1 = ProceduralMemory(max_records=10, persistence_path=mem_path)
        pm1.record("read_file", ("path", "persist.txt"), "saved data", success=True)
        # reload from disk
        pm2 = ProceduralMemory(max_records=10, persistence_path=mem_path)
        rec = pm2.get("read_file", ("path", "persist.txt"))
        assert rec is not None
        assert rec.env_snapshot.os_name == pm1.snapshot_environment().os_name
        if os.path.exists(mem_path):
            os.remove(mem_path)
