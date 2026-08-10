"""The viewer must not leak a number the agent modes cannot see.

This is information parity, not a style rule. The `human` mode is only a fair baseline if the
player reads the same city an agent reads: worn roads look worn, and nobody is shown a
population count, a treasury balance, or a health score. A single gauge in this panel would make
every human-versus-agent comparison meaningless.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from blindcity.levers import LEVERS

VIEWER = Path(__file__).resolve().parents[1] / "viewer" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return VIEWER.read_text(encoding="utf-8")


def test_every_lever_is_controllable(html):
    """The lever panel is the one part of the viewer that is not cosmetic: without all eight
    controls the human mode cannot play the same game as the agents.

    Checks the declared lever table rather than the rendered ids, which are built at runtime --
    an earlier version of this test looked for the generated markup and passed on an empty panel.
    """
    for name in LEVERS:
        assert f'["{name}",' in html, f"no control declared for {name}"
    # And the panel is actually built from that table, rather than the table being decoration.
    assert 'id="lv_${name}"' in html, "the lever table is not wired to any input"
    assert "readLevers" in html and "/lever" in html, "levers are never posted anywhere"


def test_lever_bounds_match_the_source_of_truth(html):
    """A slider that stops short of a lever's legal range silently narrows the human's action
    space against the agent's."""
    for name, lever in LEVERS.items():
        block = re.search(rf'\["{name}",\s*([\d.]+),\s*([\d.]+),', html)
        assert block, f"{name} is missing from the viewer's lever table"
        assert float(block.group(1)) == pytest.approx(lever.minimum)
        assert float(block.group(2)) == pytest.approx(lever.maximum)


def test_no_city_state_numbers_are_displayed(html):
    """The scene endpoint deliberately omits aggregates; the viewer must not re-derive them."""
    script = html.lower()
    for banned in ("population", "treasury", "satisfaction", "health", "index", "green"):
        # Allowed to appear in prose that explains the omission, never as a rendered value.
        for match in re.finditer(banned, script):
            window = script[max(0, match.start() - 120) : match.start() + 120]
            assert "textcontent" not in window and "innerhtml" not in window, (
                f"the viewer appears to render {banned!r}: ...{window}..."
            )


def test_a_turn_advances_a_quarter_like_the_agent_modes(html):
    """The human plays the same scenario shape: twelve turns of three months."""
    from blindcity.benchmark.scenario import INFRASTRUCTURE_CRISIS

    assert f'months: {INFRASTRUCTURE_CRISIS.months_per_turn}' in html or (
        f'"months": {INFRASTRUCTURE_CRISIS.months_per_turn}' in html
    ), "the advance control does not step one scenario turn"


def test_condition_is_shown_visually_not_numerically(html):
    """Worn roads look worn. The rule that keeps the render honest."""
    assert "condition_band" in html, "building condition is not used for drawing"
    assert "wear" in html, "road wear is not used for drawing"
