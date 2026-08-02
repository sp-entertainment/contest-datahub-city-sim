"""Entry point for `uv run sim`."""

from __future__ import annotations

import argparse
import sys
import time

from blindcity.sim.city_init import GRID_H, GRID_W
from blindcity.sim.engine import run_simulation
from blindcity.sim.warehouse import (
    WarehouseWriter,
    connect,
    reset_warehouse,
    row_counts,
    start_run,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sim", description="Run the Blind City simulation.")
    parser.add_argument("--seed", type=int, default=42, help="Seed. Same seed, same city, always.")
    parser.add_argument("--years", type=int, default=20, help="Simulated years to run.")
    parser.add_argument("--serve", action="store_true", help="Expose the FastAPI control surface.")
    parser.add_argument(
        "--no-warehouse",
        action="store_true",
        help="Run in-memory only (no Postgres writes). Useful for tests and lever sweeps.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.serve:
        print("sim: --serve is Slice 4 (FastAPI control surface); not implemented yet.")
        return 1

    print(f"sim: seed={args.seed} years={args.years} warehouse={not args.no_warehouse}")
    t0 = time.perf_counter()

    if args.no_warehouse:
        state = run_simulation(args.seed, args.years)
        elapsed = time.perf_counter() - t0
        fp = state.fingerprint()
        print(f"sim: complete in {elapsed:.1f}s (in-memory)")
        print(
            f"sim: pop={fp['pop']} buildings={fp['buildings']} "
            f"mean_sat={fp['mean_sat']:.4f} treasury={fp['treasury']:.0f}"
        )
        return 0

    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001 — CLI surface
        print(f"sim: failed to connect to warehouse: {exc}", file=sys.stderr)
        print(
            "sim: start Postgres with: docker compose -f infra/postgres/docker-compose.yml up -d",
            file=sys.stderr,
        )
        return 1

    try:
        reset_warehouse(conn)
        run_id = start_run(conn, args.seed, args.years, GRID_W, GRID_H)
        writer = WarehouseWriter(conn, run_id)

        def on_month(state) -> None:
            writer.write_month(state)
            if state.tick > 0 and state.tick % 12 == 0:
                year = state.tick // 12
                print(
                    f"sim: year {year}/{args.years} pop={state.population()} "
                    f"sat={state.mean_satisfaction():.3f} "
                    f"treasury={state.budget.treasury:,.0f}"
                )

        state = run_simulation(args.seed, args.years, on_month=on_month, record_initial=True)
        writer.finish(args.years)
        counts = row_counts(conn)
        total = sum(counts.values())
        elapsed = time.perf_counter() - t0
        print(f"sim: complete in {elapsed:.1f}s run_id={run_id}")
        print(
            f"sim: pop={state.population()} buildings={len(state.buildings)} "
            f"mean_sat={state.mean_satisfaction():.4f} treasury={state.budget.treasury:,.0f}"
        )
        print(f"sim: warehouse rows total={total:,}")
        for name in sorted(counts):
            print(f"  {name}: {counts[name]:,}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
