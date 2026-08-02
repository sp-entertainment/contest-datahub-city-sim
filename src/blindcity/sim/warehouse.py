"""Warehouse schema and bulk writers.

Batch inserts keep a 20-year citizen-scale run practical. Each `sim` invocation truncates the
warehouse so two back-to-back runs on one seed are not confounded by leftover rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from blindcity import config
from blindcity.sim.model import CityState

DDL = """
CREATE TABLE IF NOT EXISTS sim_run (
    run_id          BIGSERIAL PRIMARY KEY,
    seed            INTEGER NOT NULL,
    years           INTEGER NOT NULL,
    grid_w          INTEGER NOT NULL,
    grid_h          INTEGER NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ticks (
    run_id          BIGINT NOT NULL REFERENCES sim_run(run_id) ON DELETE CASCADE,
    tick            INTEGER NOT NULL,
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    PRIMARY KEY (run_id, tick)
);

CREATE TABLE IF NOT EXISTS tiles (
    run_id          BIGINT NOT NULL REFERENCES sim_run(run_id) ON DELETE CASCADE,
    tile_id         INTEGER NOT NULL,
    x               INTEGER NOT NULL,
    y               INTEGER NOT NULL,
    terrain         TEXT NOT NULL,
    zoning          TEXT NOT NULL,
    PRIMARY KEY (run_id, tile_id)
);

CREATE TABLE IF NOT EXISTS tile_monthly (
    run_id          BIGINT NOT NULL,
    tick            INTEGER NOT NULL,
    tile_id         INTEGER NOT NULL,
    condition       DOUBLE PRECISION NOT NULL,
    abandonment     DOUBLE PRECISION NOT NULL,
    power_served    BOOLEAN NOT NULL,
    water_load      DOUBLE PRECISION NOT NULL,
    sewer_load      DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, tick, tile_id)
);

CREATE TABLE IF NOT EXISTS buildings (
    run_id          BIGINT NOT NULL REFERENCES sim_run(run_id) ON DELETE CASCADE,
    building_id     INTEGER NOT NULL,
    tile_id         INTEGER NOT NULL,
    building_type   TEXT NOT NULL,
    capacity        INTEGER NOT NULL,
    assessed_value  DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, building_id)
);

CREATE TABLE IF NOT EXISTS building_monthly (
    run_id          BIGINT NOT NULL,
    tick            INTEGER NOT NULL,
    building_id     INTEGER NOT NULL,
    condition_band  TEXT NOT NULL,
    condition_score DOUBLE PRECISION NOT NULL,
    occupancy       INTEGER NOT NULL,
    power_served    BOOLEAN NOT NULL,
    power_demand_kw DOUBLE PRECISION NOT NULL,
    water_demand    DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, tick, building_id)
);

CREATE TABLE IF NOT EXISTS households (
    run_id              BIGINT NOT NULL REFERENCES sim_run(run_id) ON DELETE CASCADE,
    household_id        INTEGER NOT NULL,
    home_tile_id        INTEGER NOT NULL,
    home_building_id    INTEGER NOT NULL,
    PRIMARY KEY (run_id, household_id)
);

CREATE TABLE IF NOT EXISTS citizens (
    run_id          BIGINT NOT NULL REFERENCES sim_run(run_id) ON DELETE CASCADE,
    citizen_id      INTEGER NOT NULL,
    household_id    INTEGER NOT NULL,
    PRIMARY KEY (run_id, citizen_id)
);

CREATE TABLE IF NOT EXISTS citizen_monthly (
    run_id              BIGINT NOT NULL,
    tick                INTEGER NOT NULL,
    citizen_id          INTEGER NOT NULL,
    household_id        INTEGER NOT NULL,
    home_tile_id        INTEGER NOT NULL,
    workplace_tile_id   INTEGER NOT NULL,
    job_sector          TEXT NOT NULL,
    income              DOUBLE PRECISION NOT NULL,
    disposable_income   DOUBLE PRECISION NOT NULL,
    satisfaction        DOUBLE PRECISION NOT NULL,
    pos_x               DOUBLE PRECISION NOT NULL,
    pos_y               DOUBLE PRECISION NOT NULL,
    employed            BOOLEAN NOT NULL,
    uses_transit        BOOLEAN NOT NULL,
    PRIMARY KEY (run_id, tick, citizen_id)
);

CREATE TABLE IF NOT EXISTS road_segments (
    run_id          BIGINT NOT NULL REFERENCES sim_run(run_id) ON DELETE CASCADE,
    segment_id      INTEGER NOT NULL,
    from_tile_id    INTEGER NOT NULL,
    to_tile_id      INTEGER NOT NULL,
    from_x          INTEGER NOT NULL,
    from_y          INTEGER NOT NULL,
    to_x            INTEGER NOT NULL,
    to_y            INTEGER NOT NULL,
    PRIMARY KEY (run_id, segment_id)
);

CREATE TABLE IF NOT EXISTS road_monthly (
    run_id          BIGINT NOT NULL,
    tick            INTEGER NOT NULL,
    segment_id      INTEGER NOT NULL,
    traffic         DOUBLE PRECISION NOT NULL,
    wear            DOUBLE PRECISION NOT NULL,
    congestion      DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, tick, segment_id)
);

CREATE TABLE IF NOT EXISTS commute_monthly (
    run_id          BIGINT NOT NULL,
    tick            INTEGER NOT NULL,
    citizen_id      INTEGER NOT NULL,
    home_tile_id    INTEGER NOT NULL,
    workplace_tile_id INTEGER NOT NULL,
    travel_time     DOUBLE PRECISION NOT NULL,
    uses_transit    BOOLEAN NOT NULL,
    PRIMARY KEY (run_id, tick, citizen_id)
);

CREATE TABLE IF NOT EXISTS budget_monthly (
    run_id                  BIGINT NOT NULL,
    tick                    INTEGER NOT NULL,
    income_tax_revenue      DOUBLE PRECISION NOT NULL,
    property_tax_revenue    DOUBLE PRECISION NOT NULL,
    utility_revenue         DOUBLE PRECISION NOT NULL,
    transit_revenue         DOUBLE PRECISION NOT NULL,
    road_spend              DOUBLE PRECISION NOT NULL,
    water_sewer_spend       DOUBLE PRECISION NOT NULL,
    other_spend             DOUBLE PRECISION NOT NULL,
    balance                 DOUBLE PRECISION NOT NULL,
    debt                    DOUBLE PRECISION NOT NULL,
    treasury                DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, tick)
);

CREATE TABLE IF NOT EXISTS lever_monthly (
    run_id                      BIGINT NOT NULL,
    tick                        INTEGER NOT NULL,
    income_tax_rate             DOUBLE PRECISION NOT NULL,
    property_tax_rate           DOUBLE PRECISION NOT NULL,
    electricity_tariff          DOUBLE PRECISION NOT NULL,
    road_maintenance_budget     DOUBLE PRECISION NOT NULL,
    water_sewer_capex           DOUBLE PRECISION NOT NULL,
    transit_fare                DOUBLE PRECISION NOT NULL,
    zoning_release              DOUBLE PRECISION NOT NULL,
    power_contract_mode         DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, tick)
);

CREATE TABLE IF NOT EXISTS power_monthly (
    run_id              BIGINT NOT NULL,
    tick                INTEGER NOT NULL,
    demand_kw           DOUBLE PRECISION NOT NULL,
    supply_kw           DOUBLE PRECISION NOT NULL,
    outage_fraction     DOUBLE PRECISION NOT NULL,
    contract_mode       TEXT NOT NULL,
    tariff              DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, tick)
);

CREATE TABLE IF NOT EXISTS water_monthly (
    run_id          BIGINT NOT NULL,
    tick            INTEGER NOT NULL,
    capacity        DOUBLE PRECISION NOT NULL,
    demand          DOUBLE PRECISION NOT NULL,
    load_ratio      DOUBLE PRECISION NOT NULL,
    failure_rate    DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, tick)
);

CREATE TABLE IF NOT EXISTS migration_monthly (
    run_id          BIGINT NOT NULL,
    tick            INTEGER NOT NULL,
    arrivals        INTEGER NOT NULL,
    departures      INTEGER NOT NULL,
    net             INTEGER NOT NULL,
    population      INTEGER NOT NULL,
    PRIMARY KEY (run_id, tick)
);
"""

# Tables wiped at the start of each sim run (order respects FKs via CASCADE from sim_run).
ALL_TABLES = (
    "migration_monthly",
    "water_monthly",
    "power_monthly",
    "lever_monthly",
    "budget_monthly",
    "commute_monthly",
    "road_monthly",
    "road_segments",
    "citizen_monthly",
    "citizens",
    "households",
    "building_monthly",
    "buildings",
    "tile_monthly",
    "tiles",
    "ticks",
    "sim_run",
)


def sqlalchemy_url_to_psycopg(url: str) -> str:
    """Convert postgresql+psycopg://... to postgresql://... for psycopg.connect."""
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://") :]
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + url[len("postgresql+psycopg2://") :]
    return url


def connect(url: str | None = None) -> psycopg.Connection:
    dsn = sqlalchemy_url_to_psycopg(url or config.WAREHOUSE_URL)
    return psycopg.connect(dsn, row_factory=dict_row)


def ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def reset_warehouse(conn: psycopg.Connection) -> None:
    """Drop all known tables so a fresh run starts clean."""
    with conn.cursor() as cur:
        for table in ALL_TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    conn.commit()
    ensure_schema(conn)


@dataclass
class WarehouseWriter:
    """Buffers monthly rows and flushes in batches."""

    conn: psycopg.Connection
    run_id: int
    batch_size: int = 5_000
    _static_written: bool = False
    _buffers: dict[str, list[tuple[Any, ...]]] = field(default_factory=dict)

    def _buf(self, table: str) -> list[tuple[Any, ...]]:
        return self._buffers.setdefault(table, [])

    def _maybe_flush(self, table: str, force: bool = False) -> None:
        buf = self._buffers.get(table)
        if not buf:
            return
        if not force and len(buf) < self.batch_size:
            return
        self._flush_table(table)

    def _flush_table(self, table: str) -> None:
        buf = self._buffers.get(table)
        if not buf:
            return
        cols = TABLE_COLUMNS[table]
        col_list = ",".join(cols)
        with self.conn.cursor() as cur, cur.copy(f"COPY {table} ({col_list}) FROM STDIN") as copy:
            for row in buf:
                copy.write_row(row)
        buf.clear()

    def flush_all(self) -> None:
        for table in list(self._buffers.keys()):
            self._flush_table(table)
        self.conn.commit()

    def write_static(self, state: CityState) -> None:
        if self._static_written:
            return
        with self.conn.cursor() as cur:
            for t in state.tiles:
                cur.execute(
                    "INSERT INTO tiles (run_id, tile_id, x, y, terrain, zoning) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (self.run_id, t.tile_id, t.x, t.y, t.terrain, t.zoning),
                )
            for b in state.buildings:
                cur.execute(
                    "INSERT INTO buildings (run_id, building_id, tile_id, building_type, "
                    "capacity, assessed_value) VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        self.run_id,
                        b.building_id,
                        b.tile_id,
                        b.building_type,
                        b.capacity,
                        b.assessed_value,
                    ),
                )
            for h in state.households:
                cur.execute(
                    "INSERT INTO households (run_id, household_id, home_tile_id, "
                    "home_building_id) VALUES (%s,%s,%s,%s)",
                    (self.run_id, h.household_id, h.home_tile_id, h.home_building_id),
                )
            for c in state.citizens:
                cur.execute(
                    "INSERT INTO citizens (run_id, citizen_id, household_id) VALUES (%s,%s,%s)",
                    (self.run_id, c.citizen_id, c.household_id),
                )
            for r in state.roads:
                cur.execute(
                    "INSERT INTO road_segments (run_id, segment_id, from_tile_id, to_tile_id, "
                    "from_x, from_y, to_x, to_y) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.run_id,
                        r.segment_id,
                        r.from_tile_id,
                        r.to_tile_id,
                        r.from_x,
                        r.from_y,
                        r.to_x,
                        r.to_y,
                    ),
                )
        self.conn.commit()
        self._static_written = True

    def write_month(self, state: CityState) -> None:
        """Snapshot the current state. Call after each step (and optionally at tick 0)."""
        # Static entities can grow (migration, zoning). Re-upsert dimension tables simply by
        # rewriting missing rows: for MVP we snapshot dimensions each month into monthly tables
        # and keep initial static for map skeleton; new buildings/citizens go into monthly only
        # plus we refresh citizens/buildings lists when needed.
        self._refresh_dimensions(state)

        year, month = state.year_month()
        # After step_month, tick has already been incremented. History is stored under the
        # completed tick index (state.tick - 0 for initial). For initial record, tick is 0.
        tick = state.tick
        # When called after step, tick is the new time; we want the tick we just completed.
        # Convention: on_month is called with state whose `tick` is the label for this snapshot.
        # engine calls on_month after step (tick already advanced) OR at initial tick 0.
        # For post-step, year_month uses current tick which is correct for "start of next month".
        # Simpler convention: store state.tick as-is. Initial is 0; after first month is 1, etc.

        self._buf("ticks").append((self.run_id, tick, year, month))
        self._maybe_flush("ticks")

        lev = state.levers
        self._buf("lever_monthly").append(
            (
                self.run_id,
                tick,
                lev["income_tax_rate"],
                lev["property_tax_rate"],
                lev["electricity_tariff"],
                lev["road_maintenance_budget"],
                lev["water_sewer_capex"],
                lev["transit_fare"],
                lev["zoning_release"],
                lev["power_contract_mode"],
            )
        )
        self._maybe_flush("lever_monthly")

        b = state.budget
        self._buf("budget_monthly").append(
            (
                self.run_id,
                tick,
                b.income_tax_revenue,
                b.property_tax_revenue,
                b.utility_revenue,
                b.transit_revenue,
                b.road_spend,
                b.water_sewer_spend,
                b.other_spend,
                b.balance,
                b.debt,
                b.treasury,
            )
        )
        self._maybe_flush("budget_monthly")

        p = state.power
        self._buf("power_monthly").append(
            (
                self.run_id,
                tick,
                p.demand_kw,
                p.supply_kw,
                p.outage_fraction,
                p.contract_mode,
                p.tariff,
            )
        )
        self._maybe_flush("power_monthly")

        w = state.water
        self._buf("water_monthly").append(
            (
                self.run_id,
                tick,
                w.capacity,
                w.demand,
                w.load_ratio,
                w.failure_rate,
            )
        )
        self._maybe_flush("water_monthly")

        m = state.migration
        self._buf("migration_monthly").append(
            (
                self.run_id,
                tick,
                m.arrivals,
                m.departures,
                m.net,
                state.population(),
            )
        )
        self._maybe_flush("migration_monthly")

        for t in state.tiles:
            self._buf("tile_monthly").append(
                (
                    self.run_id,
                    tick,
                    t.tile_id,
                    t.condition,
                    t.abandonment,
                    t.power_served,
                    t.water_load,
                    t.sewer_load,
                )
            )
        self._maybe_flush("tile_monthly")

        for bld in state.buildings:
            self._buf("building_monthly").append(
                (
                    self.run_id,
                    tick,
                    bld.building_id,
                    bld.condition_band,
                    bld.condition_score,
                    bld.occupancy,
                    bld.power_served,
                    bld.power_demand_kw,
                    bld.water_demand,
                )
            )
        self._maybe_flush("building_monthly")

        for c in state.citizens:
            self._buf("citizen_monthly").append(
                (
                    self.run_id,
                    tick,
                    c.citizen_id,
                    c.household_id,
                    c.home_tile_id,
                    c.workplace_tile_id,
                    c.job_sector,
                    c.income,
                    c.disposable_income,
                    c.satisfaction,
                    c.pos_x,
                    c.pos_y,
                    c.employed,
                    c.uses_transit,
                )
            )
            self._buf("commute_monthly").append(
                (
                    self.run_id,
                    tick,
                    c.citizen_id,
                    c.home_tile_id,
                    c.workplace_tile_id,
                    c.commute_travel_time,
                    c.uses_transit,
                )
            )
        self._maybe_flush("citizen_monthly")
        self._maybe_flush("commute_monthly")

        for r in state.roads:
            self._buf("road_monthly").append(
                (
                    self.run_id,
                    tick,
                    r.segment_id,
                    r.traffic,
                    r.wear,
                    r.congestion,
                )
            )
        self._maybe_flush("road_monthly")

    def __post_init__(self) -> None:
        self._known_buildings: set[int] = set()
        self._known_households: set[int] = set()
        self._known_citizens: set[int] = set()
        self._last_zoning: dict[int, str] = {}

    def _refresh_dimensions(self, state: CityState) -> None:
        """Insert any buildings/citizens/households not yet in dimension tables."""
        if not self._static_written:
            self.write_static(state)
            self._known_buildings = {b.building_id for b in state.buildings}
            self._known_households = {h.household_id for h in state.households}
            self._known_citizens = {c.citizen_id for c in state.citizens}
            self._last_zoning = {t.tile_id: t.zoning for t in state.tiles}
            return

        with self.conn.cursor() as cur:
            for b in state.buildings:
                if b.building_id in self._known_buildings:
                    continue
                cur.execute(
                    "INSERT INTO buildings (run_id, building_id, tile_id, building_type, "
                    "capacity, assessed_value) VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        self.run_id,
                        b.building_id,
                        b.tile_id,
                        b.building_type,
                        b.capacity,
                        b.assessed_value,
                    ),
                )
                self._known_buildings.add(b.building_id)
            for h in state.households:
                if h.household_id in self._known_households:
                    continue
                cur.execute(
                    "INSERT INTO households (run_id, household_id, home_tile_id, "
                    "home_building_id) VALUES (%s,%s,%s,%s)",
                    (
                        self.run_id,
                        h.household_id,
                        h.home_tile_id,
                        h.home_building_id,
                    ),
                )
                self._known_households.add(h.household_id)
            for c in state.citizens:
                if c.citizen_id in self._known_citizens:
                    continue
                cur.execute(
                    "INSERT INTO citizens (run_id, citizen_id, household_id) "
                    "VALUES (%s,%s,%s)",
                    (self.run_id, c.citizen_id, c.household_id),
                )
                self._known_citizens.add(c.citizen_id)
            for t in state.tiles:
                if self._last_zoning.get(t.tile_id) == t.zoning:
                    continue
                cur.execute(
                    "UPDATE tiles SET zoning = %s WHERE run_id = %s AND tile_id = %s",
                    (t.zoning, self.run_id, t.tile_id),
                )
                self._last_zoning[t.tile_id] = t.zoning
        self.conn.commit()

    def finish(self, years: int) -> None:
        self.flush_all()
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE sim_run SET finished_at = NOW(), years = %s WHERE run_id = %s",
                (years, self.run_id),
            )
        self.conn.commit()


TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "ticks": ("run_id", "tick", "year", "month"),
    "tile_monthly": (
        "run_id",
        "tick",
        "tile_id",
        "condition",
        "abandonment",
        "power_served",
        "water_load",
        "sewer_load",
    ),
    "building_monthly": (
        "run_id",
        "tick",
        "building_id",
        "condition_band",
        "condition_score",
        "occupancy",
        "power_served",
        "power_demand_kw",
        "water_demand",
    ),
    "citizen_monthly": (
        "run_id",
        "tick",
        "citizen_id",
        "household_id",
        "home_tile_id",
        "workplace_tile_id",
        "job_sector",
        "income",
        "disposable_income",
        "satisfaction",
        "pos_x",
        "pos_y",
        "employed",
        "uses_transit",
    ),
    "commute_monthly": (
        "run_id",
        "tick",
        "citizen_id",
        "home_tile_id",
        "workplace_tile_id",
        "travel_time",
        "uses_transit",
    ),
    "road_monthly": ("run_id", "tick", "segment_id", "traffic", "wear", "congestion"),
    "budget_monthly": (
        "run_id",
        "tick",
        "income_tax_revenue",
        "property_tax_revenue",
        "utility_revenue",
        "transit_revenue",
        "road_spend",
        "water_sewer_spend",
        "other_spend",
        "balance",
        "debt",
        "treasury",
    ),
    "lever_monthly": (
        "run_id",
        "tick",
        "income_tax_rate",
        "property_tax_rate",
        "electricity_tariff",
        "road_maintenance_budget",
        "water_sewer_capex",
        "transit_fare",
        "zoning_release",
        "power_contract_mode",
    ),
    "power_monthly": (
        "run_id",
        "tick",
        "demand_kw",
        "supply_kw",
        "outage_fraction",
        "contract_mode",
        "tariff",
    ),
    "water_monthly": (
        "run_id",
        "tick",
        "capacity",
        "demand",
        "load_ratio",
        "failure_rate",
    ),
    "migration_monthly": (
        "run_id",
        "tick",
        "arrivals",
        "departures",
        "net",
        "population",
    ),
}


def start_run(conn: psycopg.Connection, seed: int, years: int, grid_w: int, grid_h: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sim_run (seed, years, grid_w, grid_h) VALUES (%s,%s,%s,%s) "
            "RETURNING run_id",
            (seed, years, grid_w, grid_h),
        )
        row = cur.fetchone()
        assert row is not None
        run_id = int(row["run_id"])
    conn.commit()
    return run_id


def row_counts(conn: psycopg.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in ALL_TABLES:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = %s)",
                (table,),
            )
            exists = cur.fetchone()
            if not exists or not exists["exists"]:
                continue
            cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
            counts[table] = int(cur.fetchone()["n"])
    return counts


def parse_host(url: str | None = None) -> str:
    raw = sqlalchemy_url_to_psycopg(url or config.WAREHOUSE_URL)
    return urlparse(raw).hostname or "localhost"
