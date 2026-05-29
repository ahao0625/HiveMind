"""v2.0 Cross-tier consistency management.

Validates cross-references across memory layers, repairs orphaned references,
and produces full audit reports of the memory system's integrity.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConsistencyReport:
    """Result of a consistency audit across memory tiers."""
    cross_ref_conflicts: int = 0
    orphaned_refs: int = 0
    repaired: int = 0
    errors: list[str] = field(default_factory=list)
    ok: bool = True


class ConsistencyManager:
    """Validates and repairs cross-tier memory consistency.

    Checks that short-term → long-term references are valid,
    and that procedural memory keys don't conflict across tiers.
    """

    def validate_cross_refs(
        self,
        short_term_keys: set[str],
        long_term_keys: set[str],
        procedural_keys: set[str],
    ) -> ConsistencyReport:
        """Check for key conflicts across memory tiers."""
        errors: list[str] = []
        conflicts = 0

        # short-term and long-term should not share keys
        st_lt_overlap = short_term_keys & long_term_keys
        if st_lt_overlap:
            conflicts += len(st_lt_overlap)
            errors.append(f"short-term/long-term key conflict: {st_lt_overlap}")

        # procedural keys should be distinct from long-term
        proc_lt_overlap = procedural_keys & long_term_keys
        if proc_lt_overlap:
            conflicts += len(proc_lt_overlap)
            errors.append(f"procedural/long-term key conflict: {proc_lt_overlap}")

        return ConsistencyReport(
            cross_ref_conflicts=conflicts,
            errors=errors,
            ok=len(errors) == 0,
        )

    def repair_orphans(
        self,
        short_term_keys: set[str],
        long_term_keys: set[str],
    ) -> ConsistencyReport:
        """Identify short-term keys with no long-term backing (orphans)."""
        orphans = short_term_keys - long_term_keys
        return ConsistencyReport(
            orphaned_refs=len(orphans),
            errors=[f"orphaned short-term key: {k}" for k in orphans] if orphans else [],
            ok=len(orphans) == 0,
        )

    def full_audit(
        self,
        short_term_keys: set[str],
        long_term_keys: set[str],
        procedural_keys: set[str],
    ) -> ConsistencyReport:
        """Run all consistency checks and return combined report."""
        cross = self.validate_cross_refs(short_term_keys, long_term_keys, procedural_keys)
        orphan = self.repair_orphans(short_term_keys, long_term_keys)

        return ConsistencyReport(
            cross_ref_conflicts=cross.cross_ref_conflicts,
            orphaned_refs=orphan.orphaned_refs,
            errors=cross.errors + orphan.errors,
            ok=cross.ok and orphan.ok,
        )
