"""The control surface is exactly eight levers, and out-of-range requests are clamped, not fatal."""

from __future__ import annotations

import pytest

from blindcity.levers import LEVERS, defaults


def test_there_are_exactly_eight_levers():
    """docs/FEATURES.md: the player's entire control surface. Adding a ninth is a design change."""
    assert len(LEVERS) == 8


def test_defaults_are_within_bounds():
    for name, value in defaults().items():
        lever = LEVERS[name]
        assert lever.minimum <= value <= lever.maximum, name


@pytest.mark.parametrize("requested,expected", [(-1.0, 0.0), (99.0, 0.40), (0.25, 0.25)])
def test_clamping(requested, expected):
    assert LEVERS["income_tax_rate"].clamp(requested) == expected
