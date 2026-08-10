"""Expert-authored assertions: the operating envelope a well-run city holds to.

This is what DataHub assertions are for. In a real deployment a domain expert writes them so that
anyone querying the warehouse — person or agent — is steered toward the ranges the business
actually wants, and away from the ones it does not. That guidance is the product. A catalog that
documents column names but stays silent on what a healthy value looks like is doing a fraction of
the job.

Two kinds here, and the second matters as much as the first:

  * **Guidance on what to fix.** Levers and outcomes that move the result, with the band that
    works. `income_tax_rate` below 0.10 starves the city; above 0.14 it drives residents out.
  * **Guidance on what to leave alone.** `zoning_release` spans 0.8017 to 0.8170 across its whole
    legal range — a 1.9% spread. An agent with a limited turn budget that spends turns tuning it
    is burning the budget on a lever that cannot pay. Saying so is real guidance.

**Every band is derived from the simulation, not fitted to it.** The author here is assumed to be
someone with deep knowledge of how the city works — which for us means `sim/systems.py`, where
every relationship is written down. The bands come from the mechanics:

  * road wear settles where repair meets damage, `wear* = wear_increase / ((budget/1e6) * rate)`
  * water capacity moves by `(capex/12)/6000` a month against ~0.6 of decay
  * revenue per point of satisfaction follows directly from `apply_economy` and
    `apply_satisfaction`, and it is what ranks the four revenue levers against each other

A sweep across each lever's range then confirms the numbers hold end to end.
`tests/test_operational_assertions.py` re-runs both the sweep and the arithmetic, so changing a
constant in `systems.py` without revisiting this file fails the build. That matters more here than
anywhere else in the project: this guidance *steers the agent*, so a stale band is not a harmless
inaccuracy, it is the catalog confidently sending it the wrong way.

Measured spreads, best to worst, over each lever's full legal range:

    income_tax_rate          0.685 -> 0.813   critical
    water_sewer_capex        (unwinnable at 0) -> 0.823   critical
    road_maintenance_budget  (unwinnable at 0) -> 0.813   critical
    electricity_tariff       0.776 -> 0.826   moderate
    property_tax_rate        0.797 -> 0.831   moderate
    transit_fare             0.802 -> 0.818   moderate
    power_contract_mode      0.799 -> 0.813   low
    zoning_release           0.802 -> 0.817   negligible
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LeverGuidance:
    """The band a lever should sit in, and how much it is worth moving at all."""

    lever: str
    low: float
    high: float
    # "critical" | "moderate" | "low" | "negligible" -- how much the outcome moves across the
    # lever's full range. Reported so the agent can rank its attention, not just its settings.
    impact: str
    note: str


# Measured by sweeping each lever with the others at the calibrated recovery policy. The band is
# where the final score stays within 2% of that lever's best.
LEVER_GUIDANCE: tuple[LeverGuidance, ...] = (
    LeverGuidance(
        "income_tax_rate", 0.10, 0.14, "critical",
        "the only revenue lever that pays for itself. It raises about $12.2M a month per unit of "
        "rate and costs 0.5 of satisfaction per unit -- roughly $24M of revenue for every point "
        "of satisfaction given up, nine times better than property tax and a thousand times "
        "better than the electricity tariff. Around 0.065 covers operating spend at a healthy "
        "maintenance budget; about 0.096 also clears the inherited debt and builds six months of "
        "reserve inside the horizon. Past 0.14 the lost residents cost more than the rate raises",
    ),
    LeverGuidance(
        "water_sewer_capex", 5_600_000, 7_200_000, "critical",
        "capacity moves by (annual capex / 12) / 6000 units a month against a decay of about 0.6, "
        "so roughly $43k a year merely holds capacity level and anything less shrinks it. Demand "
        "is near 2,100 against a post-shock capacity near 860: reaching a safe load ratio inside "
        "the horizon needs about $3.6M a year at the very least, and this band gets there with "
        "time left for the recovery to compound",
    ),
    LeverGuidance(
        "road_maintenance_budget", 3_200_000, 7_200_000, "critical",
        "repair is proportional to existing wear, so wear settles at an equilibrium rather than "
        "hitting a floor: wear stabilises at roughly 0.0165 / ((budget/$1M) x 0.05). That puts "
        "$2.2M a year at wear 0.15, $3.3M at 0.10 and $5.5M at 0.06. Below about $2.2M the "
        "network never comes back inside its healthy range; above this band the extra spend buys "
        "very little and the treasury pays for it",
    ),
    LeverGuidance(
        "electricity_tariff", 0.0, 0.10, "moderate",
        "the worst revenue lever in the city and the easiest to mistake for a good one. Each unit "
        "of tariff raises about $3,600 a month while taking $194,000 out of residents' disposable "
        "income -- it destroys 53 times what it collects, before the direct satisfaction penalty. "
        "Treat it as a price to keep low, never as a way to fund the recovery",
    ),
    LeverGuidance(
        "property_tax_rate", 0.0, 0.008, "moderate",
        "raises a similar amount per unit to income tax but costs eight times as much "
        "satisfaction (4.0 against 0.5 per unit), so about $2.7M per point of satisfaction "
        "against income tax's $24M. Where both can reach the same revenue, income tax is the "
        "cheaper instrument every time",
    ),
    LeverGuidance(
        # First written as "low yield" with a 0-6 band, and the sweep rejected it: the fare moves
        # the outcome 2.8% across its range. Telling the agent to ignore it would have been the
        # most damaging kind of error here -- confident, specific, and wrong.
        "transit_fare", 0.0, 2.0, "moderate",
        "a pure transfer: it collects exactly what it removes from riders' disposable income, "
        "about $22,000 a month per unit of fare in each direction, and the satisfaction penalty "
        "on the third of citizens who ride is unrecovered. There is no funding case for raising "
        "it; the cheapest fare is the best one",
    ),
    LeverGuidance(
        "power_contract_mode", 2, 2, "low",
        "hedged is the best of the three but worth only about 1.4% overall. Supply is structurally "
        "short of demand and no contract mode closes that, so set it to hedged once and stop "
        "spending turns on power",
    ),
    LeverGuidance(
        "zoning_release", 0.0, 1.0, "negligible",
        "the outcome varies by under 2% across this lever's entire legal range. There is no "
        "setting worth searching for; tuning it cannot repay the turn it costs",
    ),
)


@dataclass(frozen=True)
class OutcomeAssertion:
    """What a well-run city's data looks like, as SQL over the run's own views."""

    name: str
    table: str
    column: str
    sql: str
    # The healthy band. A reading outside it is reported with the direction it is out.
    low: float
    high: float
    note: str


_LATEST = "(SELECT max(tick) FROM ticks)"

# Bands taken from where the calibrated recovery policy actually settles, so they describe a city
# that has been run well rather than a target someone hoped for.
OUTCOME_ASSERTIONS: tuple[OutcomeAssertion, ...] = (
    OutcomeAssertion(
        "road_wear", "road_monthly", "wear",
        f"SELECT avg(wear) AS value FROM road_monthly WHERE tick = {_LATEST}",
        0.0, 0.15,
        "a maintained network settles near 0.06; sustained values near 1.0 mean no repair is "
        "reaching the roads",
    ),
    OutcomeAssertion(
        "water_load_ratio", "water_monthly", "load_ratio",
        f"SELECT load_ratio AS value FROM water_monthly WHERE tick = {_LATEST}",
        0.0, 0.80,
        "demand over installed capacity; above 1.0 the system is serving more than it can supply "
        "and failures follow",
    ),
    OutcomeAssertion(
        "citizen_satisfaction", "citizen_monthly", "satisfaction",
        f"SELECT avg(satisfaction) AS value FROM citizen_monthly WHERE tick = {_LATEST}",
        0.70, 1.0,
        "a well-run city sustains about 0.73; below 0.45 residents leave faster than they arrive",
    ),
    OutcomeAssertion(
        "treasury_months_cover", "budget_monthly", "treasury",
        (
            "SELECT treasury / NULLIF(road_spend + water_sewer_spend + other_spend, 0) AS value "
            f"FROM budget_monthly WHERE tick = {_LATEST}"
        ),
        3.0, 1e9,
        "months of operating spend held in reserve. Read it with road wear: a city that spends "
        "nothing on maintenance also accumulates cash, so a healthy-looking treasury beside worn "
        "roads is deferred cost, not solvency",
    ),
    OutcomeAssertion(
        "population_retention", "migration_monthly", "population",
        (
            f"SELECT (SELECT population FROM migration_monthly WHERE tick = {_LATEST})::float "
            "/ NULLIF((SELECT population FROM migration_monthly "
            "WHERE tick = (SELECT min(tick) FROM migration_monthly)), 0) AS value"
        ),
        0.95, 1e9,
        "population against the city's founding size; sustained decline means conditions are "
        "driving residents out faster than the city attracts them",
    ),
)


def outcome_breach(assertion: OutcomeAssertion, value: float | None) -> str | None:
    """Describe how a reading sits outside its documented band, or None when it is inside."""
    if value is None:
        return None
    if value < assertion.low:
        return f"below the documented minimum of {assertion.low:g}"
    if value > assertion.high:
        return f"above the documented maximum of {assertion.high:g}"
    return None


def lever_breach(guidance: LeverGuidance, value: float | None) -> str | None:
    """Describe how a lever sits outside its documented band, or None when it is inside."""
    if value is None:
        return None
    if value < guidance.low:
        return f"below the documented range {guidance.low:g}-{guidance.high:g}"
    if value > guidance.high:
        return f"above the documented range {guidance.low:g}-{guidance.high:g}"
    return None
