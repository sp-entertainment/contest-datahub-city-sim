"""Determinism guards.

CONTRIBUTING.md makes reproducibility from a seed a hard rule, because the A/B evaluation compares
two runs that must differ only in the agent's context. These tests are cheap insurance on the RNG
itself; the real test arrives when the tick loop does — two full runs on one seed, byte-identical.
"""

from __future__ import annotations

from blindcity.rng import RNG


def test_same_seed_same_sequence():
    a = [RNG(42).random() for _ in range(3)]
    b = [RNG(42).random() for _ in range(3)]
    assert a == b


def test_different_seeds_diverge():
    assert RNG(1).random() != RNG(2).random()


def test_named_streams_are_independent_of_creation_order():
    """Adding a subsystem must not shift the numbers every other subsystem draws."""
    parent = RNG(42)
    migration_first = parent.stream("migration").random()

    parent = RNG(42)
    parent.stream("power")
    parent.stream("roads")
    migration_later = parent.stream("migration").random()

    assert migration_first == migration_later


def test_named_streams_differ_from_each_other():
    parent = RNG(42)
    assert parent.stream("migration").random() != parent.stream("power").random()
