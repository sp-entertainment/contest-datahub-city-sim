"""In-memory city state.

Pure data structures. No I/O. Order of lists is part of the determinism contract: iteration always
follows sorted ids or insertion order established at init.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Terrain and zoning vocabularies — also glossary terms.
TERRAINS = ("grass", "water", "rock")
ZONINGS = ("none", "residential", "commercial", "industrial", "mixed")
BUILDING_TYPES = ("residential", "commercial", "industrial", "civic")
# Visible condition bands the viewer will shade — never shown as numbers there.
CONDITION_BANDS = ("new", "worn", "derelict")


@dataclass
class Tile:
    tile_id: int
    x: int
    y: int
    terrain: str
    zoning: str
    # 0.0 perfect … 1.0 ruined / abandoned appearance
    condition: float = 0.0
    abandonment: float = 0.0
    power_served: bool = True
    water_load: float = 0.0
    sewer_load: float = 0.0


@dataclass
class Building:
    building_id: int
    tile_id: int
    building_type: str
    capacity: int
    assessed_value: float
    condition_score: float = 0.0  # 0 new … 1 derelict
    occupancy: int = 0
    power_served: bool = True
    power_demand_kw: float = 5.0
    water_demand: float = 1.0

    @property
    def condition_band(self) -> str:
        if self.condition_score < 0.33:
            return "new"
        if self.condition_score < 0.66:
            return "worn"
        return "derelict"


@dataclass
class Household:
    household_id: int
    home_tile_id: int
    home_building_id: int


@dataclass
class Citizen:
    citizen_id: int
    household_id: int
    home_tile_id: int
    workplace_tile_id: int
    job_sector: str  # residential work / commercial / industrial / none
    income: float
    satisfaction: float = 0.7
    # Continuous position on the map (tile centers are x+0.5, y+0.5)
    pos_x: float = 0.0
    pos_y: float = 0.0
    uses_transit: bool = False
    commute_travel_time: float = 1.0
    disposable_income: float = 0.0
    employed: bool = True


@dataclass
class RoadSegment:
    segment_id: int
    from_tile_id: int
    to_tile_id: int
    from_x: int
    from_y: int
    to_x: int
    to_y: int
    traffic: float = 0.0
    wear: float = 0.0
    congestion: float = 0.0


@dataclass
class Budget:
    income_tax_revenue: float = 0.0
    property_tax_revenue: float = 0.0
    utility_revenue: float = 0.0
    transit_revenue: float = 0.0
    road_spend: float = 0.0
    water_sewer_spend: float = 0.0
    other_spend: float = 0.0
    balance: float = 0.0
    debt: float = 0.0
    treasury: float = 1_000_000.0

    @property
    def total_revenue(self) -> float:
        return (
            self.income_tax_revenue
            + self.property_tax_revenue
            + self.utility_revenue
            + self.transit_revenue
        )

    @property
    def total_spend(self) -> float:
        return self.road_spend + self.water_sewer_spend + self.other_spend


@dataclass
class PowerState:
    demand_kw: float = 0.0
    supply_kw: float = 0.0
    outage_fraction: float = 0.0
    contract_mode: str = "spot"
    tariff: float = 0.15


@dataclass
class WaterState:
    capacity: float = 1000.0
    demand: float = 0.0
    load_ratio: float = 0.0
    failure_rate: float = 0.0


@dataclass
class MigrationState:
    arrivals: int = 0
    departures: int = 0

    @property
    def net(self) -> int:
        return self.arrivals - self.departures


@dataclass
class CityState:
    """Full mutable city at one point in simulated time."""

    seed: int
    grid_w: int
    grid_h: int
    tick: int = 0  # months since start
    levers: dict[str, float] = field(default_factory=dict)
    tiles: list[Tile] = field(default_factory=list)
    buildings: list[Building] = field(default_factory=list)
    households: list[Household] = field(default_factory=list)
    citizens: list[Citizen] = field(default_factory=list)
    roads: list[RoadSegment] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)
    power: PowerState = field(default_factory=PowerState)
    water: WaterState = field(default_factory=WaterState)
    migration: MigrationState = field(default_factory=MigrationState)
    # Monotonic id allocators
    next_building_id: int = 0
    next_household_id: int = 0
    next_citizen_id: int = 0
    next_segment_id: int = 0

    def tile_at(self, x: int, y: int) -> Tile:
        return self.tiles[y * self.grid_w + x]

    def tile_by_id(self, tile_id: int) -> Tile:
        return self.tiles[tile_id]

    def year_month(self) -> tuple[int, int]:
        """1-based calendar year/month from months-elapsed tick (tick 0 → year 1, month 1)."""
        year = self.tick // 12 + 1
        month = self.tick % 12 + 1
        return year, month

    def population(self) -> int:
        return len(self.citizens)

    def mean_satisfaction(self) -> float:
        if not self.citizens:
            return 0.0
        return sum(c.satisfaction for c in self.citizens) / len(self.citizens)

    def fingerprint(self) -> dict[str, Any]:
        """Compact deterministic summary for identity tests without dumping millions of rows."""
        cit = sorted(self.citizens, key=lambda c: c.citizen_id)
        bld = sorted(self.buildings, key=lambda b: b.building_id)
        roads = sorted(self.roads, key=lambda r: r.segment_id)
        return {
            "seed": self.seed,
            "tick": self.tick,
            "pop": len(cit),
            "buildings": len(bld),
            "mean_sat": round(self.mean_satisfaction(), 10),
            "treasury": round(self.budget.treasury, 6),
            "income_tax_rev": round(self.budget.income_tax_revenue, 6),
            "property_tax_rev": round(self.budget.property_tax_revenue, 6),
            "utility_rev": round(self.budget.utility_revenue, 6),
            "transit_rev": round(self.budget.transit_revenue, 6),
            "road_spend": round(self.budget.road_spend, 6),
            "water_spend": round(self.budget.water_sewer_spend, 6),
            "power_demand": round(self.power.demand_kw, 6),
            "power_outage": round(self.power.outage_fraction, 10),
            "water_load": round(self.water.load_ratio, 10),
            "water_capacity": round(self.water.capacity, 6),
            "migration_net": self.migration.net,
            "mean_road_wear": round(
                sum(r.wear for r in roads) / len(roads) if roads else 0.0, 10
            ),
            "mean_income": round(
                sum(c.income for c in cit) / len(cit) if cit else 0.0, 6
            ),
            "sum_pos": round(sum(c.pos_x + c.pos_y for c in cit), 6),
            "sum_building_condition": round(sum(b.condition_score for b in bld), 10),
            "zoned_tiles": sum(1 for t in self.tiles if t.zoning != "none"),
        }
