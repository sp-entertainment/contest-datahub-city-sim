"""The player's entire control surface.

Eight levers, defined once here and consumed by the simulation, the viewer's lever panel, the
FastAPI control surface, and the agent's actuation step. They are named in docs/FEATURES.md; this
module is the single source of truth for their ranges and defaults.

Bounds were recalibrated against the `infrastructure_neglect` scenario (2026-08-02) so a recovery
policy can reverse road wear and water strain within the 36-turn budget while a neglect policy
cannot. See docs/DECISIONS.md.

Note the one wrinkle: FEATURES.md calls the levers eight scalars, but `power_contract_mode` is
genuinely categorical. It is modelled here as a discrete index so the control surface stays a
uniform vector of numbers, which keeps the agent's action space simple.
"""

from __future__ import annotations

from dataclasses import dataclass

POWER_CONTRACT_MODES = ("spot", "fixed", "hedged")


@dataclass(frozen=True)
class Lever:
    """One control, with the range the player and the agent are held to."""

    name: str
    minimum: float
    maximum: float
    default: float
    unit: str
    description: str

    def clamp(self, value: float) -> float:
        """Constrain a requested value to the legal range.

        Both the human and the agent go through this. An agent that asks for a 400% tax rate gets a
        clamped value rather than an exception, so a bad decision stays a bad decision instead of
        becoming a crash.
        """
        return max(self.minimum, min(self.maximum, value))


LEVERS: dict[str, Lever] = {
    lever.name: lever
    for lever in (
        Lever("income_tax_rate", 0.0, 0.40, 0.10, "fraction", "Tax on household income."),
        Lever("property_tax_rate", 0.0, 0.05, 0.012, "fraction", "Annual tax on assessed value."),
        Lever("electricity_tariff", 0.0, 1.00, 0.15, "currency/kWh", "Retail rate charged to households."),
        # Raised max 5M → 8M so an aggressive recovery can outpace wear under full traffic.
        Lever(
            "road_maintenance_budget",
            0.0,
            8_000_000.0,
            600_000.0,
            "currency/year",
            "Spend on road repair.",
        ),
        # Raised max 5M → 8M and default 400k → 500k so water capacity can recover in-scenario.
        Lever(
            "water_sewer_capex",
            0.0,
            8_000_000.0,
            500_000.0,
            "currency/year",
            "Capital spend on water and sewer capacity.",
        ),
        Lever("transit_fare", 0.0, 10.0, 2.50, "currency/ride", "Fare charged per transit trip."),
        Lever("zoning_release", 0.0, 1.0, 0.10, "fraction", "Share of undeveloped land opened for development."),
        Lever("power_contract_mode", 0, len(POWER_CONTRACT_MODES) - 1, 0, "index", f"One of {POWER_CONTRACT_MODES}."),
    )
}


def defaults() -> dict[str, float]:
    """The starting position of every lever."""
    return {name: lever.default for name, lever in LEVERS.items()}
