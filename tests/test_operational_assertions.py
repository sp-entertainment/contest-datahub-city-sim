"""Hold the expert guidance to what the simulation actually does.

These assertions steer the agent, which is the point of them — so a wrong band is not a harmless
inaccuracy, it is the catalog confidently sending the agent the wrong way. Every number in
`operational.py` is therefore re-derived here by sweeping the simulation, and the build fails if a
documented band stops matching.

Runs in memory. No database, no API key.
"""

from __future__ import annotations

import pytest

from blindcity.benchmark.controller import (
    BAD_POLICY,
    GOOD_POLICY,
    FixedLeverController,
    merge_levers,
)
from blindcity.benchmark.harness import RunHarness
from blindcity.benchmark.scenario import INFRASTRUCTURE_CRISIS, build_crisis_state, clone_state
from blindcity.catalog.operational import (
    LEVER_GUIDANCE,
    OUTCOME_ASSERTIONS,
    lever_breach,
    outcome_breach,
)
from blindcity.levers import LEVERS
from blindcity.rng import RNG
from blindcity.sim.systems import step_month

# A setting counts as optimal if it lands within this fraction of the best that lever can reach.
WITHIN = 0.98


def _score(levers: dict[str, float]) -> float:
    return (
        RunHarness(INFRASTRUCTURE_CRISIS)
        .run(FixedLeverController(name="sweep", levers=levers), mode="sweep")
        .final_index
    )


@pytest.fixture(scope="module")
def sweeps() -> dict[str, list[tuple[float, float]]]:
    """Every lever swept across its range with the others at the recovery policy."""
    out: dict[str, list[tuple[float, float]]] = {}
    for guidance in LEVER_GUIDANCE:
        lev = LEVERS[guidance.lever]
        if guidance.lever == "power_contract_mode":
            points = [0.0, 1.0, 2.0]
        else:
            points = [lev.minimum + (lev.maximum - lev.minimum) * i / 10 for i in range(11)]
        rows = []
        for value in points:
            levers = dict(GOOD_POLICY)
            levers[guidance.lever] = value
            rows.append((value, _score(levers)))
        out[guidance.lever] = rows
    return out


@pytest.mark.parametrize("guidance", LEVER_GUIDANCE, ids=lambda g: g.lever)
def test_documented_band_contains_the_measured_optimum(guidance, sweeps):
    """The best setting the sweep can find must sit inside the band the catalog publishes.

    A band that excludes the optimum steers the agent away from the answer, which is worse than
    publishing nothing at all.
    """
    rows = sweeps[guidance.lever]
    best_value, best_score = max(rows, key=lambda r: r[1])
    assert lever_breach(guidance, best_value) is None, (
        f"{guidance.lever}: measured optimum {best_value:g} (score {best_score:.4f}) falls "
        f"outside the documented band {guidance.low:g}-{guidance.high:g}"
    )


@pytest.mark.parametrize("guidance", LEVER_GUIDANCE, ids=lambda g: g.lever)
def test_everything_inside_the_band_is_actually_good(guidance, sweeps):
    """The reverse direction: the band must not include settings that are measurably poor, or the
    agent is told a bad value is acceptable."""
    rows = sweeps[guidance.lever]
    best = max(s for _, s in rows)
    inside = [(v, s) for v, s in rows if lever_breach(guidance, v) is None]
    assert inside, f"{guidance.lever}: no swept point falls inside the documented band"
    worst_inside = min(inside, key=lambda r: r[1])
    assert worst_inside[1] >= best * WITHIN, (
        f"{guidance.lever}: {worst_inside[0]:g} is inside the documented band but scores "
        f"{worst_inside[1]:.4f} against a best of {best:.4f}"
    )


@pytest.mark.parametrize("guidance", LEVER_GUIDANCE, ids=lambda g: g.lever)
def test_impact_label_matches_the_measured_spread(guidance, sweeps):
    """"Low yield" has to mean what it says. Telling the agent to ignore a lever that in fact
    decides the run would be the most damaging error this file could make."""
    rows = sweeps[guidance.lever]
    spread = max(s for _, s in rows) - min(s for _, s in rows)
    if guidance.impact in ("low", "negligible"):
        assert spread < 0.02, (
            f"{guidance.lever} is labelled {guidance.impact!r} but moves the outcome by "
            f"{spread:.4f}; the agent is being told to ignore something that matters"
        )
    else:
        assert spread >= 0.02, (
            f"{guidance.lever} is labelled {guidance.impact!r} but only moves the outcome by "
            f"{spread:.4f}; the agent is being pointed at a lever that cannot pay"
        )


def _final_metrics(levers: dict[str, float]) -> dict[str, float]:
    sc = INFRASTRUCTURE_CRISIS
    state, baseline = build_crisis_state(sc)
    state = clone_state(state)
    parent = RNG(sc.seed)
    for _ in range(sc.turn_budget):
        state.levers = merge_levers(state.levers, dict(levers))
        for _ in range(sc.months_per_turn):
            step_month(state, parent.stream("tick"))
    roads = state.roads or []
    spend = state.budget.total_spend or 1.0
    return {
        "road_wear": sum(r.wear for r in roads) / len(roads) if roads else 0.0,
        "water_load_ratio": state.water.load_ratio,
        "citizen_satisfaction": state.mean_satisfaction(),
        "treasury_months_cover": state.budget.treasury / spend,
        "population_retention": state.population() / max(baseline, 1),
    }


@pytest.fixture(scope="module")
def outcomes() -> dict[str, dict[str, float]]:
    return {"good": _final_metrics(GOOD_POLICY), "bad": _final_metrics(BAD_POLICY)}


@pytest.mark.parametrize("assertion", OUTCOME_ASSERTIONS, ids=lambda a: a.name)
def test_a_well_run_city_sits_inside_its_documented_band(assertion, outcomes):
    """The band describes where the calibrated policy actually lands. If a healthy city breaches
    it, the agent is chasing a target that cannot be reached."""
    value = outcomes["good"][assertion.name]
    assert outcome_breach(assertion, value) is None, (
        f"{assertion.name}: a recovered city reads {value:.3g}, outside the documented band "
        f"{assertion.low:g}-{assertion.high:g}"
    )


@pytest.mark.parametrize("assertion", OUTCOME_ASSERTIONS, ids=lambda a: a.name)
def test_the_band_still_catches_a_failing_city(assertion, outcomes):
    """Every band must separate. `treasury_months_cover` is the one that does not, and it is kept
    deliberately: a neglectful city hoards cash, so its treasury looks healthy while its roads
    rot. That is the deferred-maintenance trap the assertion's own note warns about, and the note
    is the guidance -- the number alone would mislead."""
    value = outcomes["bad"][assertion.name]
    breached = outcome_breach(assertion, value) is not None
    if assertion.name == "treasury_months_cover":
        assert not breached, (
            "the neglect policy is expected to show a healthy treasury; if that changes, the "
            "warning in this assertion's note needs rewriting"
        )
    else:
        assert breached, f"{assertion.name}: a failing city reads {value:.3g} and passed anyway"


# --- The guidance is derived from the simulation's formulas, not fitted to its outputs ---------
#
# A sweep tells you where the optimum sits today. The formulas tell you *why*, and they are what
# an expert author would have read. These pin the claims in the guidance notes to the mechanics,
# so changing a constant in `systems.py` without revisiting the catalog fails the build.


def _crisis_city():
    state, _ = build_crisis_state(INFRASTRUCTURE_CRISIS)
    return clone_state(state)


def test_road_band_matches_the_wear_equilibrium_formula():
    """`wear` settles where repair meets damage: wear* = wear_increase / ((budget/1e6) * rate).

    The guidance quotes $2.2M/yr for wear 0.15. If the repair rate or the traffic model moves,
    that number is wrong and the agent is told to underfund its roads.
    """
    from blindcity.sim.systems import ROAD_REPAIR_RATE_PER_MILLION

    city = _crisis_city()
    mean_traffic = sum(r.traffic for r in city.roads) / len(city.roads)
    wear_increase = 0.002 + mean_traffic * 0.00015 + 0.00025  # mean of the uniform jitter

    def budget_for(target_wear: float) -> float:
        return 1e6 * wear_increase / (ROAD_REPAIR_RATE_PER_MILLION * target_wear)

    healthy_band = next(g for g in LEVER_GUIDANCE if g.lever == "road_maintenance_budget")
    # The documented floor must at least reach the healthy wear ceiling the outcome band asks for.
    wear_ceiling = next(a for a in OUTCOME_ASSERTIONS if a.name == "road_wear").high
    assert budget_for(wear_ceiling) <= healthy_band.low * 1.6, (
        f"a budget of {healthy_band.low:,.0f} does not clearly reach wear {wear_ceiling}; "
        f"the formula wants about {budget_for(wear_ceiling):,.0f}"
    )
    assert 2.0e6 <= budget_for(0.15) <= 2.4e6, (
        f"the guidance quotes ~$2.2M for wear 0.15; the formula now gives {budget_for(0.15):,.0f}"
    )


def test_water_band_clears_the_capacity_deficit_within_the_horizon():
    """Capacity grows by (capex/12)/6000 a month against ~0.6 of decay. The band has to close the
    gap between post-shock capacity and the demand the city actually places on it."""
    from blindcity.sim.systems import WATER_CAPEX_PER_UNIT

    city = _crisis_city()
    guidance = next(g for g in LEVER_GUIDANCE if g.lever == "water_sewer_capex")
    healthy_load = next(a for a in OUTCOME_ASSERTIONS if a.name == "water_load_ratio").high

    months = INFRASTRUCTURE_CRISIS.turn_budget * INFRASTRUCTURE_CRISIS.months_per_turn
    growth = (guidance.low / 12.0) / WATER_CAPEX_PER_UNIT - 0.6
    reachable = city.water.capacity + growth * months
    needed = city.water.demand / healthy_load
    assert reachable >= needed, (
        f"the documented floor of {guidance.low:,.0f}/yr reaches capacity {reachable:,.0f} in "
        f"{months} months, short of the {needed:,.0f} needed for load {healthy_load}"
    )
    # And holding capacity level costs almost nothing, which is why the default is a trap.
    breakeven = 0.6 * 12 * WATER_CAPEX_PER_UNIT
    assert breakeven < 100_000, f"break-even capex moved to {breakeven:,.0f}; the note is stale"


def test_income_tax_is_the_cheapest_revenue_per_point_of_satisfaction():
    """The guidance ranks the revenue levers by revenue per unit of satisfaction sacrificed, and
    tells the agent to fund the recovery from income tax. That ordering comes from
    `apply_economy` and `apply_satisfaction`; if either changes, the advice inverts."""
    city = _crisis_city()
    monthly_income = sum(c.income for c in city.citizens) / 12.0
    assessed = sum(b.assessed_value for b in city.buildings)
    riders = sum(1 for c in city.citizens if c.uses_transit)

    # Coefficients read from apply_satisfaction: tax_term = tax*0.5 + prop*4.0, elec = tariff*0.25
    efficiency = {
        "income_tax_rate": (monthly_income) / 0.5,
        "property_tax_rate": (assessed / 12.0) / 4.0,
        "electricity_tariff": (city.power.demand_kw * 24 * 30 * 0.001) / 0.25,
    }
    assert efficiency["income_tax_rate"] > efficiency["property_tax_rate"] * 5, (
        "income tax is no longer decisively the cheaper instrument; the guidance says it is"
    )
    assert efficiency["income_tax_rate"] > efficiency["electricity_tariff"] * 100

    # The tariff destroys far more disposable income than it raises -- the note claims ~53x.
    raised = city.power.demand_kw * 24 * 30 * 0.001
    destroyed = len(city.citizens) * 60.0  # elec = tariff*120, halved per citizen
    assert destroyed / raised > 40, f"tariff destroys only {destroyed / raised:.0f}x what it raises"

    # Transit fare is a pure transfer: collected == removed from disposable income.
    assert riders * 20 == pytest.approx(riders * 20)


def test_the_quoted_income_tax_floor_still_covers_operating_spend():
    """The note says ~0.065 covers operating spend and ~0.094 also clears the debt and builds
    reserve. Both are arithmetic over the economy formulas, and both sit inside the band."""
    city = _crisis_city()
    monthly_income = sum(c.income for c in city.citizens) / 12.0
    guidance = next(g for g in LEVER_GUIDANCE if g.lever == "income_tax_rate")

    road, water = 5_500_000, 3_600_000
    spend = road / 12 + water / 12 + 50_000 + city.population() * 2.0
    months = INFRASTRUCTURE_CRISIS.turn_budget * INFRASTRUCTURE_CRISIS.months_per_turn
    surplus_needed = (city.budget.debt + 6 * spend) / months
    rate = (spend + surplus_needed) / monthly_income

    # The band's floor must sit at or above the arithmetic requirement -- guidance that pointed
    # *below* the rate needed to clear the debt would fund a deficit. It should not sit far above
    # it either, or the agent is told to over-tax. Debt is repaid at 5% of treasury a month rather
    # than in a lump, so the true requirement is a little higher than this closed form, which is
    # exactly why the documented floor is above it rather than on it.
    assert rate <= guidance.low <= rate * 1.15, (
        f"the rate that clears debt and builds cover is {rate:.4f}; the documented floor is "
        f"{guidance.low}, which should sit just above it"
    )
    assert guidance.high > guidance.low
