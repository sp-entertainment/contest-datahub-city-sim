"""The agent must be able to see the consequences of its own decisions.

`WarehouseWriter` batches at 5,000 rows. `citizen_monthly` writes ~3,235 rows a month and so
trickles through mid-run; `ticks` writes one row a month and `road_monthly` a few hundred, so
neither ever reaches the threshold and both stayed pinned at the last month of the crisis until
`finish()` ran at the very end.

For the whole of Slice 6 that meant every agent read a warehouse where `max(tick) FROM ticks`
never moved, road condition never responded to road spending, and two tables joined on `tick` were
misaligned by months. The scores were real; what the agent could see was not.
"""

from __future__ import annotations

import inspect

from blindcity.benchmark import harness


def test_the_turn_is_flushed_before_the_next_decision():
    src = inspect.getsource(harness.RunHarness.run)
    step = src.index("step_month(state")
    flush = src.index("writer.flush_all()")
    decide = src.index("controller.decide(state")
    assert step < flush, "months are stepped but never flushed before the next decision"
    # The flush has to sit inside the turn loop, after the months and before the loop repeats.
    assert decide < step, "unexpected loop shape; re-check this guard"


def test_low_volume_tables_would_not_flush_on_their_own():
    """The reason the bug was invisible: only the biggest tables ever crossed the batch line, so
    the warehouse looked alive while its clock stood still."""
    from blindcity.sim.warehouse import WarehouseWriter

    months_in_a_full_run = 36
    assert WarehouseWriter.batch_size > months_in_a_full_run, (
        "ticks writes one row a month; if the batch size ever drops below the run length this "
        "test stops describing the hazard"
    )
