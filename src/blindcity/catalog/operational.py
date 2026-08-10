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

**This file authors the guidance; it does not deliver it.** `emit.py` publishes everything below to
DataHub as dataset properties, and `agent/monitor.py` reads it back out of DataHub at run time.
Nothing on the agent's path imports these constants. That is deliberate, and it is the difference
between a claim and a demonstration: "DataHub assertions steer the agent" has to mean the bytes the
agent acted on came from DataHub, not from a Python tuple that happens to sit beside a catalog we
also populated. It also means an expert editing a band in the DataHub UI changes how the agent
plays without a code change, which is the workflow this is modelling.

The cost is drift: the same number now exists here and in DataHub. `guidance_properties` and
`parse_guidance` below are exact inverses, so there is one wire format rather than two, and
`uv run datahub-emit --check-guidance` fails when what is published differs from what is written
here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


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


@dataclass(frozen=True)
class ResponseLag:
    """How long a column takes to reflect a lever change, and why."""

    column: str
    note: str


# --- The wire format between here and DataHub ---------------------------------------------------
#
# One prefix, so everything this project publishes as guidance can be found, audited, and deleted
# as a group, and nothing collides with the `assertion.N.column` properties `emit_assertions`
# already writes. Values are JSON because a band is structured -- a monitor that had to re-parse
# "0.10-0.14" out of prose would be a second, worse wire format hiding inside the first.

GUIDANCE_PREFIX = "blindcity.guidance"

# Which dataset carries which guidance. Levers and lags are properties of a table, so they hang off
# the table they describe; the lever bands go on `lever_monthly`, whose columns they are.
LEVER_GUIDANCE_TABLE = "lever_monthly"


def guidance_properties() -> dict[str, dict[str, str]]:
    """Everything above, as `{table: {property_key: json}}` ready for `datasetProperties`."""
    out: dict[str, dict[str, str]] = {}

    lever_props = out.setdefault(LEVER_GUIDANCE_TABLE, {})
    for g in LEVER_GUIDANCE:
        lever_props[f"{GUIDANCE_PREFIX}.lever.{g.lever}"] = json.dumps(
            {"low": g.low, "high": g.high, "impact": g.impact, "note": g.note},
            sort_keys=True,
        )

    for a in OUTCOME_ASSERTIONS:
        out.setdefault(a.table, {})[f"{GUIDANCE_PREFIX}.outcome.{a.name}"] = json.dumps(
            {
                "table": a.table,
                "column": a.column,
                "sql": a.sql,
                "low": a.low,
                "high": a.high,
                "note": a.note,
            },
            sort_keys=True,
        )

    for lag in RESPONSE_LAGS:
        table = lag.column.split(".", 1)[0]
        out.setdefault(table, {})[f"{GUIDANCE_PREFIX}.lag.{lag.column}"] = json.dumps(
            {"column": lag.column, "note": lag.note}, sort_keys=True
        )
    return out


@dataclass(frozen=True)
class Guidance:
    """The published guidance, read back. The same three tuples, from DataHub rather than source."""

    levers: tuple[LeverGuidance, ...] = ()
    outcomes: tuple[OutcomeAssertion, ...] = ()
    lags: tuple[ResponseLag, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.levers or self.outcomes or self.lags)


def parse_guidance(properties: dict[str, str]) -> Guidance:
    """Rebuild the guidance from custom properties gathered across every dataset.

    The inverse of `guidance_properties`. Unknown keys are ignored and malformed values are
    skipped rather than raised on: this reads a live catalog that anyone may have edited, and one
    bad property should cost that one entry, not the whole block. Ordering is restored from the
    source tuples so the rendered block does not reshuffle when DataHub returns a different map
    order -- two runs whose prompts differ only in the order of a list are not comparable.
    """
    levers: dict[str, LeverGuidance] = {}
    outcomes: dict[str, OutcomeAssertion] = {}
    lags: dict[str, ResponseLag] = {}

    for key, raw in properties.items():
        if not key.startswith(GUIDANCE_PREFIX + "."):
            continue
        kind, _, name = key[len(GUIDANCE_PREFIX) + 1 :].partition(".")
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        try:
            if kind == "lever":
                levers[name] = LeverGuidance(
                    name, float(payload["low"]), float(payload["high"]),
                    str(payload["impact"]), str(payload["note"]),
                )
            elif kind == "outcome":
                outcomes[name] = OutcomeAssertion(
                    name, str(payload["table"]), str(payload["column"]), str(payload["sql"]),
                    float(payload["low"]), float(payload["high"]), str(payload["note"]),
                )
            elif kind == "lag":
                lags[name] = ResponseLag(str(payload["column"]), str(payload["note"]))
        except (KeyError, TypeError, ValueError):
            continue

    def ordered(found: dict[str, Any], source: tuple[Any, ...], key: str) -> tuple[Any, ...]:
        known = [getattr(s, key) for s in source]
        head = [found[k] for k in known if k in found]
        tail = [v for k, v in sorted(found.items()) if k not in known]
        return tuple(head + tail)

    return Guidance(
        levers=ordered(levers, LEVER_GUIDANCE, "lever"),
        outcomes=ordered(outcomes, OUTCOME_ASSERTIONS, "name"),
        lags=ordered(lags, RESPONSE_LAGS, "column"),
    )


# Read from `sim/systems.py`. These are properties of how the data behaves, not tactics, and they
# are invisible in the warehouse itself: every lever is constant across the whole recorded
# history, so no query can reveal how fast anything responds to changing one.
#
# Without them an agent over-corrects. In earlier runs the control mode drove road spending
# 16M -> 5M -> 16M across consecutive turns, reading a system that had not finished responding as
# one that was not responding.
RESPONSE_LAGS: tuple[ResponseLag, ...] = (
    ResponseLag(
        "water_monthly.capacity",
        "the slowest system in the city, and the only one that grows linearly rather than "
        "converging: capacity moves a fixed number of units a month, so the deficit closes on a "
        "schedule that cannot be made up later. Closing it takes about 36 months at $3.6M a year, "
        "23 at $5.6M, 16 at $8M. Funded late, it cannot finish inside the horizon at any price",
    ),
    ResponseLag(
        "road_monthly.wear",
        "converges toward an equilibrium at (budget/$1M) x 5% a month, so the budget sets both the "
        "destination and the speed: about 13 months to close 90% of the gap at $3.2M a year, 8 at "
        "$5M, 4.5 at $8M. Read a mid-flight value as progress, not as failure",
    ),
    ResponseLag(
        "citizen_monthly.satisfaction",
        "a moving average that keeps 70% of last month's value, so about 30% of any change lands "
        "in the first month, 66% by the third and 88% by the sixth. A lever changed this turn is "
        "roughly two-thirds visible by the next one",
    ),
    ResponseLag(
        "migration_monthly.population",
        "responds to satisfaction, so it carries satisfaction's lag plus its own; population is "
        "the last thing to turn around and the last evidence that a policy worked",
    ),
)
