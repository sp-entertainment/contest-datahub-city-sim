"""Build the initial spatial city from a seed.

Deterministic: same seed → same tiles, buildings, citizens, roads.
"""

from __future__ import annotations

from blindcity.levers import POWER_CONTRACT_MODES, defaults
from blindcity.rng import RNG
from blindcity.sim.model import (
    Building,
    Citizen,
    CityState,
    Household,
    RoadSegment,
    Tile,
    WaterState,
)

# Scale knobs. A few thousand citizens × monthly history × ~20 years reaches millions of rows
# across history tables. Recorded in docs/DECISIONS.md when chosen.
GRID_W = 32
GRID_H = 32
INITIAL_HOUSEHOLDS = 1400
MEAN_HOUSEHOLD_SIZE = 2  # plus occasional third adult via RNG
ROAD_EVERY = 4  # arterial grid spacing


def _terrain_for(rng: RNG, x: int, y: int, w: int, h: int) -> str:
    # River band and rocky corner — pure function of coords + light noise.
    if abs(x - w // 3) <= 1 and 2 < y < h - 2:
        return "water"
    if x > w - 4 and y < 4:
        return "rock"
    noise = rng.random()
    if noise < 0.02:
        return "rock"
    if noise < 0.04:
        return "water"
    return "grass"


def _initial_zoning(rng: RNG, x: int, y: int, w: int, h: int, terrain: str) -> str:
    if terrain != "grass":
        return "none"
    # Concentric-ish: core mixed/commercial, ring residential, fringe industrial pockets.
    cx, cy = w / 2, h / 2
    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
    max_d = (cx**2 + cy**2) ** 0.5
    n = dist / max_d
    roll = rng.random()
    if n < 0.25:
        return "mixed" if roll < 0.6 else "commercial"
    if n < 0.55:
        return "residential" if roll < 0.75 else "mixed"
    if n < 0.8:
        if roll < 0.15:
            return "industrial"
        if roll < 0.7:
            return "residential"
        return "none"
    if roll < 0.2:
        return "industrial"
    if roll < 0.35:
        return "residential"
    return "none"


def _build_roads(state: CityState) -> None:
    """Axis-aligned arterials every ROAD_EVERY tiles; undirected edges stored once (right/down)."""
    w, h = state.grid_w, state.grid_h
    segments: list[RoadSegment] = []
    sid = 0
    for y in range(h):
        for x in range(w):
            tile = state.tile_at(x, y)
            if tile.terrain == "water":
                continue
            on_grid = (x % ROAD_EVERY == 0) or (y % ROAD_EVERY == 0)
            if not on_grid:
                continue
            # Edge to the right
            if x + 1 < w:
                right = state.tile_at(x + 1, y)
                if right.terrain != "water" and (
                    (x + 1) % ROAD_EVERY == 0 or y % ROAD_EVERY == 0
                ):
                    segments.append(
                        RoadSegment(
                            segment_id=sid,
                            from_tile_id=tile.tile_id,
                            to_tile_id=right.tile_id,
                            from_x=x,
                            from_y=y,
                            to_x=x + 1,
                            to_y=y,
                        )
                    )
                    sid += 1
            # Edge down
            if y + 1 < h:
                down = state.tile_at(x, y + 1)
                if down.terrain != "water" and (
                    x % ROAD_EVERY == 0 or (y + 1) % ROAD_EVERY == 0
                ):
                    segments.append(
                        RoadSegment(
                            segment_id=sid,
                            from_tile_id=tile.tile_id,
                            to_tile_id=down.tile_id,
                            from_x=x,
                            from_y=y,
                            to_x=x,
                            to_y=y + 1,
                        )
                    )
                    sid += 1
    state.roads = segments
    state.next_segment_id = sid


def _place_buildings(state: CityState, rng: RNG) -> dict[str, list[Building]]:
    """Place buildings on zoned grass tiles. Returns buildings by type."""
    by_type: dict[str, list[Building]] = {
        "residential": [],
        "commercial": [],
        "industrial": [],
        "civic": [],
    }
    bid = 0
    # Stable order: tile_id ascending
    for tile in state.tiles:
        if tile.terrain != "grass" or tile.zoning == "none":
            continue
        btype = tile.zoning if tile.zoning != "mixed" else (
            "residential" if rng.random() < 0.55 else "commercial"
        )
        if btype == "none":
            continue
        # Not every zoned tile gets a building at t=0 — leave room for zoning_release growth.
        if rng.random() > 0.72:
            continue
        if btype == "residential":
            capacity = rng.randint(2, 8)
            value = 80_000 + rng.random() * 220_000
            demand_kw = 2.0 + capacity * 0.8
            water = 0.5 + capacity * 0.35
        elif btype == "commercial":
            capacity = rng.randint(4, 20)
            value = 150_000 + rng.random() * 400_000
            demand_kw = 8.0 + capacity * 1.2
            water = 1.0 + capacity * 0.2
        elif btype == "industrial":
            capacity = rng.randint(8, 40)
            value = 200_000 + rng.random() * 600_000
            demand_kw = 20.0 + capacity * 2.0
            water = 2.0 + capacity * 0.5
        else:
            capacity = rng.randint(5, 15)
            value = 100_000 + rng.random() * 100_000
            demand_kw = 5.0
            water = 1.0

        b = Building(
            building_id=bid,
            tile_id=tile.tile_id,
            building_type=btype,
            capacity=capacity,
            assessed_value=value,
            condition_score=rng.random() * 0.25,
            power_demand_kw=demand_kw,
            water_demand=water,
        )
        state.buildings.append(b)
        by_type[btype].append(b)
        bid += 1

    # One civic hall near center if missing
    if not by_type["civic"]:
        cx, cy = state.grid_w // 2, state.grid_h // 2
        center = state.tile_at(cx, cy)
        if center.terrain == "grass":
            center.zoning = "mixed"
            b = Building(
                building_id=bid,
                tile_id=center.tile_id,
                building_type="civic",
                capacity=20,
                assessed_value=500_000,
                condition_score=0.05,
                power_demand_kw=15.0,
                water_demand=2.0,
            )
            state.buildings.append(b)
            by_type["civic"].append(b)
            bid += 1

    state.next_building_id = bid
    return by_type


def _place_population(state: CityState, rng: RNG, by_type: dict[str, list[Building]]) -> None:
    residences = list(by_type["residential"])
    workplaces = list(by_type["commercial"]) + list(by_type["industrial"]) + list(by_type["civic"])
    if not residences:
        raise RuntimeError("city_init: no residential buildings to house population")
    if not workplaces:
        workplaces = list(residences)

    # Sort for stable choice indices
    residences.sort(key=lambda b: b.building_id)
    workplaces.sort(key=lambda b: b.building_id)

    hid = 0
    cid = 0
    for _ in range(INITIAL_HOUSEHOLDS):
        home = residences[rng.randint(0, len(residences) - 1)]
        if home.occupancy >= home.capacity:
            # try a few more picks
            for _try in range(8):
                home = residences[rng.randint(0, len(residences) - 1)]
                if home.occupancy < home.capacity:
                    break
        home_tile = state.tile_by_id(home.tile_id)
        hh = Household(
            household_id=hid,
            home_tile_id=home.tile_id,
            home_building_id=home.building_id,
        )
        state.households.append(hh)
        size = MEAN_HOUSEHOLD_SIZE + (1 if rng.random() < 0.25 else 0)
        for _m in range(size):
            work = workplaces[rng.randint(0, len(workplaces) - 1)]
            sector = work.building_type
            base_income = {
                "commercial": 48_000,
                "industrial": 42_000,
                "civic": 52_000,
                "residential": 30_000,
            }.get(sector, 40_000)
            income = max(12_000.0, base_income + rng.normal(0, 8_000))
            uses_transit = rng.random() < 0.35
            c = Citizen(
                citizen_id=cid,
                household_id=hid,
                home_tile_id=home.tile_id,
                workplace_tile_id=work.tile_id,
                job_sector=sector,
                income=income,
                satisfaction=0.55 + rng.random() * 0.3,
                pos_x=home_tile.x + 0.5,
                pos_y=home_tile.y + 0.5,
                uses_transit=uses_transit,
                employed=True,
            )
            state.citizens.append(c)
            home.occupancy += 1
            cid += 1
        hid += 1

    state.next_household_id = hid
    state.next_citizen_id = cid


def create_city(seed: int, levers: dict[str, float] | None = None) -> CityState:
    """Construct a fully initialized CityState at tick 0 (before the first monthly step)."""
    rng = RNG(seed)
    terrain_rng = rng.stream("terrain")
    zone_rng = rng.stream("zoning")
    build_rng = rng.stream("buildings")
    pop_rng = rng.stream("population")

    lev = dict(defaults())
    if levers:
        lev.update(levers)

    state = CityState(
        seed=seed,
        grid_w=GRID_W,
        grid_h=GRID_H,
        tick=0,
        levers=lev,
        water=WaterState(capacity=2_500.0),
    )

    tiles: list[Tile] = []
    tid = 0
    for y in range(GRID_H):
        for x in range(GRID_W):
            terrain = _terrain_for(terrain_rng, x, y, GRID_W, GRID_H)
            zoning = _initial_zoning(zone_rng, x, y, GRID_W, GRID_H, terrain)
            tiles.append(Tile(tile_id=tid, x=x, y=y, terrain=terrain, zoning=zoning))
            tid += 1
    state.tiles = tiles

    _build_roads(state)
    by_type = _place_buildings(state, build_rng)
    _place_population(state, pop_rng, by_type)

    # Seed power contract from lever
    mode_idx = round(float(state.levers["power_contract_mode"]))
    mode_idx = max(0, min(len(POWER_CONTRACT_MODES) - 1, mode_idx))
    state.power.contract_mode = POWER_CONTRACT_MODES[mode_idx]
    state.power.tariff = state.levers["electricity_tariff"]

    return state
