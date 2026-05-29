"""Tests for v2.0 MemorySystem facade and ConsistencyManager."""

import os
import pytest
from hivemind.config import MemoryConfig
from hivemind.memory.facade import MemorySystem


@pytest.fixture
def config():
    return MemoryConfig()


@pytest.fixture
def ms(config):
    ms = MemorySystem(config)
    yield ms
    # cleanup procedural persistence
    proc_path = os.path.expanduser(config.procedural.persistence_path)
    if os.path.exists(proc_path):
        os.remove(proc_path)


class TestGetItemBackwardCompat:
    def test_long_term(self, ms):
        assert ms["long_term"] is ms.long_term

    def test_short_term(self, ms):
        assert ms["short_term"] is ms.short_term

    def test_working(self, ms):
        assert ms["working"] is ms.working

    def test_procedural(self, ms):
        assert ms["procedural"] is ms.procedural

    def test_unknown_key_raises(self, ms):
        with pytest.raises(KeyError):
            ms["unknown_tier"]


class TestProceduralDelegates:
    def test_record_procedural_creates_record(self, ms):
        rec = ms.record_procedural("read_file", ("path", "t.txt"), "content", success=True, latency_ms=3.0)
        assert rec.tool_name == "read_file"
        assert rec.success is True

    def test_validate_procedural_matches_current_env(self, ms):
        ms.record_procedural("read_file", ("path", "v.txt"), "hello", success=True)
        is_valid, reason = ms.validate_procedural("read_file", ("path", "v.txt"))
        assert is_valid is True
        assert reason == "env_match"

    def test_validate_procedural_unknown_fails(self, ms):
        is_valid, reason = ms.validate_procedural("unknown", ("a",))
        assert is_valid is False


class TestSearchAll:
    @pytest.mark.asyncio
    async def test_searches_short_term(self, ms):
        await ms.short_term.store("k1", "hello world value")
        results = await ms.search_all("hello world", limit=5)
        assert len(results) > 0
        assert any(r["key"] == "k1" for r in results)

    @pytest.mark.asyncio
    async def test_searches_long_term(self, ms):
        await ms.long_term.store("k2", "unique search term here")
        results = await ms.search_all("unique search term", limit=5)
        assert len(results) > 0
        assert any(r["key"] == "k2" for r in results)


class TestStoreCrossTier:
    @pytest.mark.asyncio
    async def test_stores_in_both_tiers(self, ms):
        await ms.store_cross_tier("cross-key", "cross value data")
        st = await ms.short_term.retrieve("cross-key")
        lt = await ms.long_term.retrieve("cross-key")
        assert st is not None
        assert lt is not None
        assert st.value == "cross value data"
        assert lt.value == "cross value data"
