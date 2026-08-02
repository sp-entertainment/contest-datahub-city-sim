"""Seeded randomness.

Determinism is a hard project rule — see CONTRIBUTING.md. The evaluation harness compares two runs
on the same seed, so any unseeded randomness makes the entire submission meaningless.

Rules, enforced by convention and by `tests/test_determinism.py`:

- Never import the global `random` module in simulation code. Take an `RNG` and use it.
- Derive per-subsystem streams with `RNG.stream()` so adding a subsystem does not shift the numbers
  every other subsystem draws.
- Never iterate over a set or an unordered dict when the order affects a draw.
"""

from __future__ import annotations

import hashlib
import random


class RNG:
    """A seeded random source that can be split into independent, reproducible substreams."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._random = random.Random(seed)

    def stream(self, name: str) -> RNG:
        """Return an independent RNG for a named subsystem.

        The substream seed is derived from the parent seed and the name, so `stream("migration")`
        yields the same sequence regardless of what other streams exist or when they were created.
        """
        digest = hashlib.sha256(f"{self.seed}:{name}".encode()).digest()
        return RNG(int.from_bytes(digest[:8], "big"))

    def random(self) -> float:
        """Uniform float in [0.0, 1.0)."""
        return self._random.random()

    def randint(self, low: int, high: int) -> int:
        """Uniform integer in [low, high], both inclusive."""
        return self._random.randint(low, high)

    def choice(self, seq):
        """Uniform choice from an indexable sequence. Do not pass a set."""
        return self._random.choice(seq)

    def normal(self, mu: float, sigma: float) -> float:
        """Gaussian draw."""
        return self._random.gauss(mu, sigma)
