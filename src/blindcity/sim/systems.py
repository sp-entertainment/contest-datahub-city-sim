"""Monthly city systems.

Each function mutates CityState in place. RNG streams are named and independent so adding a system
does not shift other systems' draws. Iteration always uses sorted id order when order affects draws.
"""

from __future__ import annotations

from blindcity.levers import POWER_CONTRACT_MODES
from blindcity.rng import RNG
from blindcity.sim.model import (
    Building,
    Citizen,
    CityState,
    Household,
)


def apply_power(state: CityState, rng: RNG) -> None:
    mode_idx = round(float(state.levers["power_contract_mode"]))
    mode_idx = max(0, min(len(POWER_CONTRACT_MODES) - 1, mode_idx))
    mode = POWER_CONTRACT_MODES[mode_idx]
    state.power.contract_mode = mode
    state.power.tariff = state.levers["electricity_tariff"]

    demand = sum(b.power_demand_kw * max(0.2, b.occupancy / max(1, b.capacity)) for b in state.buildings)
    # Base supply scales with population; contract mode changes reliability and headroom.
    base_supply = 50.0 + state.population() * 1.15
    if mode == "spot":
        supply = base_supply * (0.85 + rng.random() * 0.3)
        reliability = 0.92
    elif mode == "fixed":
        supply = base_supply * 1.05
        reliability = 0.97
    else:  # hedged
        supply = base_supply * 1.12
        reliability = 0.99

    state.power.demand_kw = demand
    state.power.supply_kw = supply
    shortfall = max(0.0, demand - supply) / max(demand, 1.0)
    state.power.outage_fraction = min(1.0, shortfall + (1.0 - reliability) * 0.5)

    # Buildings lose power with probability proportional to outage; ordered by building_id.
    for b in sorted(state.buildings, key=lambda x: x.building_id):
        b.power_served = rng.random() >= state.power.outage_fraction

    # Tile power: served if its building is served; empty tiles follow city-wide outage level.
    building_by_tile = {b.tile_id: b for b in state.buildings}
    for tile in state.tiles:
        b = building_by_tile.get(tile.tile_id)
        if b is not None:
            tile.power_served = b.power_served
        else:
            tile.power_served = state.power.outage_fraction < 0.5


def apply_water(state: CityState, rng: RNG) -> None:
    # Capex is annual; convert to monthly capacity growth.
    annual_capex = state.levers["water_sewer_capex"]
    # $1 of capex → small capacity units; baseline decay without spend.
    growth = (annual_capex / 12.0) / 50_000.0
    decay = 0.5 + rng.random() * 0.2
    state.water.capacity = max(100.0, state.water.capacity + growth - decay)

    demand = sum(
        b.water_demand * max(0.15, b.occupancy / max(1, b.capacity)) for b in state.buildings
    )
    # Per-citizen base demand
    demand += state.population() * 0.15
    state.water.demand = demand
    state.water.load_ratio = demand / max(state.water.capacity, 1.0)
    state.water.failure_rate = max(0.0, state.water.load_ratio - 1.0) * 0.4

    for tile in state.tiles:
        # Local load proxy: buildings on tile + neighbors simplified as occupancy share
        tile.water_load = state.water.load_ratio
        tile.sewer_load = state.water.load_ratio * (0.9 + 0.1 * rng.random())


def apply_roads(state: CityState, rng: RNG) -> None:
    if not state.roads:
        return

    # Traffic from commuting citizens: Manhattan distance home→work contributes to corridors.
    # Simplified: each citizen adds traffic to a random arterial proportional to commute length.
    traffic = {r.segment_id: 0.0 for r in state.roads}
    road_list = sorted(state.roads, key=lambda r: r.segment_id)
    n_roads = len(road_list)

    for c in sorted(state.citizens, key=lambda x: x.citizen_id):
        ht = state.tile_by_id(c.home_tile_id)
        wt = state.tile_by_id(c.workplace_tile_id)
        dist = abs(ht.x - wt.x) + abs(ht.y - wt.y)
        # Touch a few segments deterministically from citizen id
        touches = 1 + min(6, dist // 2)
        for k in range(touches):
            # Stable pseudo-index without extra RNG for assignment base; use stream for jitter
            idx = (c.citizen_id * 17 + k * 31) % n_roads
            traffic[road_list[idx].segment_id] += 1.0 + dist * 0.05

    annual_maint = state.levers["road_maintenance_budget"]
    monthly_maint = annual_maint / 12.0
    # Spread maintenance across segments
    maint_per = monthly_maint / max(n_roads, 1)

    for r in road_list:
        r.traffic = traffic[r.segment_id]
        wear_increase = 0.002 + r.traffic * 0.00015 + rng.random() * 0.0005
        wear_repair = maint_per / 500_000.0  # $500k/year citywide ≈ meaningful repair
        r.wear = min(1.0, max(0.0, r.wear + wear_increase - wear_repair))
        # Congestion: traffic relative to capacity degraded by wear
        capacity = 40.0 * (1.0 - 0.6 * r.wear)
        r.congestion = min(1.0, r.traffic / max(capacity, 1.0))


def apply_commute(state: CityState, rng: RNG) -> None:
    """Update commute travel times and citizen positions (home at night snapshot)."""
    mean_congestion = (
        sum(r.congestion for r in state.roads) / len(state.roads) if state.roads else 0.0
    )
    mean_wear = sum(r.wear for r in state.roads) / len(state.roads) if state.roads else 0.0

    for c in sorted(state.citizens, key=lambda x: x.citizen_id):
        ht = state.tile_by_id(c.home_tile_id)
        wt = state.tile_by_id(c.workplace_tile_id)
        dist = abs(ht.x - wt.x) + abs(ht.y - wt.y)
        base = 1.0 + dist * 0.35
        road_factor = 1.0 + mean_congestion * 0.8 + mean_wear * 0.4
        transit_factor = 0.75 if c.uses_transit else 1.0
        # Higher transit fare doesn't change time but is felt in satisfaction elsewhere
        c.commute_travel_time = base * road_factor * transit_factor * (0.95 + rng.random() * 0.1)
        # End-of-month position: at home (viewer can animate later)
        c.pos_x = ht.x + 0.3 + rng.random() * 0.4
        c.pos_y = ht.y + 0.3 + rng.random() * 0.4


def apply_economy(state: CityState, rng: RNG) -> None:
    tax = state.levers["income_tax_rate"]
    prop = state.levers["property_tax_rate"]
    tariff = state.levers["electricity_tariff"]
    fare = state.levers["transit_fare"]

    income_tax = 0.0
    for c in state.citizens:
        monthly_income = c.income / 12.0
        tax_paid = monthly_income * tax
        income_tax += tax_paid
        c.disposable_income = monthly_income - tax_paid
        # Electricity share of bill
        elec = tariff * 120.0  # ~120 kWh household-ish per adult proxy
        if c.uses_transit:
            c.disposable_income -= fare * 20.0  # ~20 rides/month
        c.disposable_income -= elec / max(1, 2)  # shared roughly

    # Property tax monthly (annual rate / 12)
    prop_rev = sum(b.assessed_value * prop / 12.0 for b in state.buildings)

    # Utility revenue from tariff × demand
    util_rev = tariff * state.power.demand_kw * 24.0 * 30.0 * 0.001  # rough kWh month scale

    transit_users = sum(1 for c in state.citizens if c.uses_transit)
    transit_rev = transit_users * fare * 20.0

    state.budget.income_tax_revenue = income_tax
    state.budget.property_tax_revenue = prop_rev
    state.budget.utility_revenue = util_rev
    state.budget.transit_revenue = transit_rev
    state.budget.road_spend = state.levers["road_maintenance_budget"] / 12.0
    state.budget.water_sewer_spend = state.levers["water_sewer_capex"] / 12.0
    state.budget.other_spend = 50_000.0 + state.population() * 2.0

    state.budget.balance = state.budget.total_revenue - state.budget.total_spend
    state.budget.treasury += state.budget.balance
    if state.budget.treasury < 0:
        state.budget.debt += -state.budget.treasury
        state.budget.treasury = 0.0
    else:
        # Pay down debt slightly when flush
        pay = min(state.budget.debt, state.budget.treasury * 0.05)
        state.budget.debt -= pay
        state.budget.treasury -= pay


def apply_satisfaction(state: CityState, rng: RNG) -> None:
    tax = state.levers["income_tax_rate"]
    prop = state.levers["property_tax_rate"]
    tariff = state.levers["electricity_tariff"]
    fare = state.levers["transit_fare"]
    water_penalty = max(0.0, state.water.load_ratio - 0.85) * 0.3

    home_power = {b.building_id: b.power_served for b in state.buildings}
    hh_building = {h.household_id: h.home_building_id for h in state.households}

    for c in sorted(state.citizens, key=lambda x: x.citizen_id):
        di = c.disposable_income
        income_term = min(0.5, max(0.0, di / 8_000.0))
        tax_term = tax * 0.5 + prop * 4.0
        commute_term = min(0.4, c.commute_travel_time / 40.0)
        elec_term = tariff * 0.25
        transit_term = (fare / 10.0) * 0.15 if c.uses_transit else 0.0
        powered = home_power.get(hh_building.get(c.household_id, -1), True)
        power_term = 0.0 if powered else 0.25

        target = (
            0.75
            + income_term
            - tax_term
            - commute_term
            - elec_term
            - transit_term
            - power_term
            - water_penalty
            + rng.normal(0, 0.02)
        )
        target = max(0.0, min(1.0, target))
        c.satisfaction = max(0.0, min(1.0, c.satisfaction * 0.7 + target * 0.3))


def apply_building_condition(state: CityState, rng: RNG) -> None:
    for b in sorted(state.buildings, key=lambda x: x.building_id):
        decay = 0.001 + rng.random() * 0.002
        if not b.power_served:
            decay += 0.003
        if state.water.load_ratio > 1.0:
            decay += 0.002
        # Occupancy protects somewhat (maintained buildings)
        if b.occupancy > 0:
            decay *= 0.7
        else:
            decay += 0.004
        b.condition_score = min(1.0, b.condition_score + decay)
        # Vacancy → abandonment signal on tile
        tile = state.tile_by_id(b.tile_id)
        if b.occupancy == 0:
            tile.abandonment = min(1.0, tile.abandonment + 0.01)
            tile.condition = min(1.0, tile.condition + 0.008)
        else:
            tile.abandonment = max(0.0, tile.abandonment - 0.005)
            tile.condition = b.condition_score


def apply_zoning_growth(state: CityState, rng: RNG) -> None:
    """zoning_release opens undeveloped grass tiles and may spawn buildings."""
    release = state.levers["zoning_release"]
    # Each month, attempt to zone a fraction of unzoned grass
    candidates = [t for t in state.tiles if t.terrain == "grass" and t.zoning == "none"]
    candidates.sort(key=lambda t: t.tile_id)
    n_open = int(len(candidates) * release * 0.05)  # 5% of release fraction per month
    n_open = min(n_open, len(candidates))
    for i in range(n_open):
        t = candidates[i]
        roll = rng.random()
        if roll < 0.6:
            t.zoning = "residential"
        elif roll < 0.85:
            t.zoning = "commercial"
        else:
            t.zoning = "industrial"

    # Possibly build on zoned empty tiles
    occupied = {b.tile_id for b in state.buildings}
    buildable = [
        t
        for t in state.tiles
        if t.terrain == "grass" and t.zoning != "none" and t.tile_id not in occupied
    ]
    buildable.sort(key=lambda t: t.tile_id)
    # Higher release → more construction attempts
    attempts = int(2 + release * 8)
    for i in range(min(attempts, len(buildable))):
        if rng.random() > 0.35 + release * 0.4:
            continue
        t = buildable[i]
        btype = t.zoning if t.zoning != "mixed" else "residential"
        capacity = rng.randint(2, 10) if btype == "residential" else rng.randint(4, 16)
        b = Building(
            building_id=state.next_building_id,
            tile_id=t.tile_id,
            building_type=btype,
            capacity=capacity,
            assessed_value=90_000 + rng.random() * 200_000,
            condition_score=0.0,
            power_demand_kw=3.0 + capacity,
            water_demand=0.5 + capacity * 0.3,
        )
        state.next_building_id += 1
        state.buildings.append(b)


def apply_migration(state: CityState, rng: RNG) -> None:
    mean_sat = state.mean_satisfaction()
    # Arrivals when satisfaction high and housing available; departures when low.
    residences = [b for b in state.buildings if b.building_type == "residential"]
    residences.sort(key=lambda b: b.building_id)
    free_slots = sum(max(0, b.capacity - b.occupancy) for b in residences)

    arrival_pressure = max(0.0, mean_sat - 0.5) * 40.0
    depart_pressure = max(0.0, 0.45 - mean_sat) * 50.0
    # Tax flight
    depart_pressure += state.levers["income_tax_rate"] * 15.0
    depart_pressure += state.levers["property_tax_rate"] * 80.0

    arrivals = min(free_slots, int(arrival_pressure + rng.random() * 3))
    # Departures as whole households
    n_hh = len(state.households)
    departures_hh = min(n_hh // 4, int(depart_pressure + rng.random() * 2))

    # Process departures first (highest household_id first for stability of remaining list rebuild)
    state.migration.arrivals = 0
    state.migration.departures = 0

    if departures_hh > 0 and state.households:
        members_by_hh: dict[int, list[Citizen]] = {}
        for c in state.citizens:
            members_by_hh.setdefault(c.household_id, []).append(c)
        hh_by_id = {h.household_id: h for h in state.households}
        hh_sat = []
        for hid, members in members_by_hh.items():
            sat = sum(c.satisfaction for c in members) / len(members) if members else 0.0
            hh_sat.append((sat, hid))
        hh_sat.sort(key=lambda x: (x[0], x[1]))  # lowest satisfaction first
        leave_ids = {hh_sat[i][1] for i in range(min(departures_hh, len(hh_sat)))}

        bld_by_id = {b.building_id: b for b in state.buildings}
        new_citizens: list[Citizen] = []
        for c in state.citizens:
            if c.household_id in leave_ids:
                state.migration.departures += 1
                hh = hh_by_id.get(c.household_id)
                if hh is not None:
                    b = bld_by_id.get(hh.home_building_id)
                    if b is not None:
                        b.occupancy = max(0, b.occupancy - 1)
            else:
                new_citizens.append(c)
        state.citizens = new_citizens
        state.households = [h for h in state.households if h.household_id not in leave_ids]

    # Arrivals
    workplaces = [
        b
        for b in state.buildings
        if b.building_type in ("commercial", "industrial", "civic")
    ]
    workplaces.sort(key=lambda b: b.building_id)
    if not workplaces:
        workplaces = list(residences)

    for _ in range(arrivals):
        # find residence with space
        home = None
        for b in residences:
            if b.occupancy < b.capacity:
                home = b
                break
        if home is None:
            break
        work = workplaces[rng.randint(0, len(workplaces) - 1)]
        hid = state.next_household_id
        state.next_household_id += 1
        state.households.append(
            Household(
                household_id=hid,
                home_tile_id=home.tile_id,
                home_building_id=home.building_id,
            )
        )
        size = 1 + (1 if rng.random() < 0.5 else 0)
        for _m in range(size):
            if home.occupancy >= home.capacity:
                break
            cid = state.next_citizen_id
            state.next_citizen_id += 1
            ht = state.tile_by_id(home.tile_id)
            income = max(12_000.0, 40_000 + rng.normal(0, 7_000))
            state.citizens.append(
                Citizen(
                    citizen_id=cid,
                    household_id=hid,
                    home_tile_id=home.tile_id,
                    workplace_tile_id=work.tile_id,
                    job_sector=work.building_type,
                    income=income,
                    satisfaction=0.5 + rng.random() * 0.2,
                    pos_x=ht.x + 0.5,
                    pos_y=ht.y + 0.5,
                    uses_transit=rng.random() < 0.35,
                    employed=True,
                )
            )
            home.occupancy += 1
            state.migration.arrivals += 1


def step_month(state: CityState, rng: RNG) -> None:
    """Advance the city one simulated month. Order is part of the causal model."""
    apply_zoning_growth(state, rng.stream(f"zoning:{state.tick}"))
    apply_power(state, rng.stream(f"power:{state.tick}"))
    apply_water(state, rng.stream(f"water:{state.tick}"))
    apply_roads(state, rng.stream(f"roads:{state.tick}"))
    apply_commute(state, rng.stream(f"commute:{state.tick}"))
    apply_economy(state, rng.stream(f"economy:{state.tick}"))
    apply_satisfaction(state, rng.stream(f"satisfaction:{state.tick}"))
    apply_building_condition(state, rng.stream(f"buildings:{state.tick}"))
    apply_migration(state, rng.stream(f"migration:{state.tick}"))
    state.tick += 1
