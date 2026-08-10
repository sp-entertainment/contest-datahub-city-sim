"""Operating-condition assertions: what the catalog claims a healthy city's data looks like.

Distinct from `schema_spec.ASSERTIONS`, which are integrity checks -- "satisfaction is in [0, 1]"
is true by construction and passes in a city that is falling apart. Those catch a broken pipeline.
These catch a broken city.

**Every threshold here was measured, not chosen.** The simulation was played to completion under
the calibrated recovery policy and the neglect policy, and a detector is only included if it fires
under neglect and stays silent under recovery. An assertion that misfires is worse than no
assertion: it points the agent at a system that is already healing and costs it a turn.
`tests/test_operational_assertions.py` re-runs that validation and fails the build if a detector
stops separating the two.

Two candidates were measured and deliberately **rejected**:

  * `treasury` and `debt`. Both policies end with a full treasury and zero debt -- neglect reaches
    it slightly *faster*, because a city that spends nothing on its roads accumulates cash. Cash
    is not a distress signal here, it is a symptom of deferred maintenance, and an assertion on it
    would have told the agent the finances were fine in precisely the run where they were not.
  * `outage_fraction`. Even under the recovery policy it never falls below ~0.17, so any threshold
    tight enough to fire under neglect also fires under a working policy.

The rejections are the reason this file exists. Three of the five obvious metrics do not
discriminate, and the two that look most like "financial health" are the actively misleading ones.
"""

from __future__ import annotations

from dataclasses import dataclass

# How many recent months a trend detector looks at. Six is a quarter of the recovery horizon:
# long enough that one noisy month cannot trip it, short enough to react inside a 12-turn run.
TREND_MONTHS = 6


@dataclass(frozen=True)
class OperationalAssertion:
    """One measured expectation about a healthy city, as SQL over the run's own views."""

    name: str
    table: str
    column: str
    # Returns a single row with a numeric `value`, scoped by the connection's search_path.
    sql: str
    # Fires when `value` is at or beyond this, in the direction given by `fires_above`.
    threshold: float
    fires_above: bool
    message: str


_LATEST = "(SELECT max(tick) FROM ticks)"

OPERATIONAL_ASSERTIONS: tuple[OperationalAssertion, ...] = (
    OperationalAssertion(
        name="road_wear_saturated",
        table="road_monthly",
        column="wear",
        sql=f"SELECT avg(wear) AS value FROM road_monthly WHERE tick = {_LATEST}",
        # Measured: recovery reaches 0.055 and holds; neglect sits pinned at 1.000 every month.
        # The gap is so wide that any threshold in between works; 0.80 is set well clear of the
        # recovering trajectory rather than close to the failing one.
        threshold=0.80,
        fires_above=True,
        message="mean road wear is at the top of its range; the network is effectively unmaintained",
    ),
    OperationalAssertion(
        name="water_demand_exceeds_capacity",
        table="water_monthly",
        column="load_ratio",
        sql=f"SELECT load_ratio AS value FROM water_monthly WHERE tick = {_LATEST}",
        # Not a target but a definition: above 1.0 the system is serving more demand than it has
        # capacity for. Measured: recovery clears 1.0 by the sixth turn, neglect never does.
        threshold=1.0,
        fires_above=True,
        message="water demand exceeds installed capacity (load ratio above 1.0)",
    ),
    OperationalAssertion(
        name="population_declining",
        table="migration_monthly",
        column="population",
        sql=(
            f"SELECT (SELECT population FROM migration_monthly WHERE tick = {_LATEST}) "
            "- (SELECT population FROM migration_monthly WHERE tick = "
            f"greatest({_LATEST} - {TREND_MONTHS}, (SELECT min(tick) FROM migration_monthly))) AS value"
        ),
        # Measured: neglect loses population every single turn; recovery dips early then grows.
        # Stated as a change over six months so an early dip under a working policy cannot trip it.
        threshold=0.0,
        fires_above=False,
        message=f"population has fallen over the last {TREND_MONTHS} months; residents are leaving",
    ),
    OperationalAssertion(
        name="satisfaction_depressed",
        table="citizen_monthly",
        column="satisfaction",
        sql=f"SELECT avg(satisfaction) AS value FROM citizen_monthly WHERE tick = {_LATEST}",
        # This one was written as a trend first and the validation rejected it, for a reason worth
        # keeping: in a failing city satisfaction *rises* late on. Neglect drives a third of the
        # population out, and the residents who remain enjoy shorter commutes and less strain on
        # the utilities, so mean satisfaction climbs 0.125 -> 0.263 while the city empties.
        # Meanwhile recovery plateaus around 0.734 and drifts down a thousandth, which a trend
        # detector reads as decline. The trend version therefore failed both halves at once: silent
        # on the failing city, firing on the healthy one -- exactly backwards.
        #
        # The level separates cleanly instead. Settled turns: recovery never below 0.731, neglect
        # never above 0.263. The threshold sits in open space between them.
        threshold=0.45,
        fires_above=False,
        message="mean citizen satisfaction is far below what a functioning city sustains",
    ),
)


def fires(assertion: OperationalAssertion, value: float | None) -> bool:
    """Whether this assertion is currently violated. A missing value never fires."""
    if value is None:
        return False
    if assertion.fires_above:
        return value >= assertion.threshold
    return value < assertion.threshold
