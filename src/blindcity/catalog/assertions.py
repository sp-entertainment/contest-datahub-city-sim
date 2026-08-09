"""Evaluate catalog assertions as real SQL against the warehouse.

Declarations live in `schema_spec.ASSERTIONS`. This module turns each into an executable
predicate, runs it against Postgres, and returns pass/fail with evidence. Emitting only the
declaration without evaluation is exactly the stale-metadata failure mode this entry argues
against — so emit paths call `evaluate_assertions` and attach the results.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

import psycopg

from blindcity.catalog.schema_spec import ASSERTIONS

# Spec tuple: (table, column_or_*, description)
AssertionSpec = tuple[str, str, str]


@dataclass(frozen=True)
class AssertionResult:
    """One assertion's outcome after SQL evaluation."""

    table: str
    column: str
    description: str
    sql: str
    passed: bool
    detail: str  # human-readable evidence (counts, min/max, etc.)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _scope(run_id: int | None) -> str:
    """Restrict an assertion to one simulation run.

    `uv run sim` appends, so every table holds every run ever loaded and the benchmark modes
    write concurrently. Unscoped, a row-count assertion gets easier each time anyone runs the
    simulation, and a range assertion silently pools modes that are supposed to be compared.
    The run id is bound as a parameter, never interpolated.
    """
    return " WHERE run_id = %(run_id)s" if run_id is not None else ""


def _sql_range_unit(table: str, column: str, run_id: int | None = None) -> tuple[str, str]:
    """Column in [0, 1]. Count of out-of-range rows must be 0.

    One pass reports violations and the total, so an empty table is distinguishable from a
    clean one rather than both looking like zero violations.
    """
    sql = (
        f"SELECT "
        f"COUNT(*) FILTER (WHERE {column} < 0 OR {column} > 1)::bigint AS violations, "
        f"COALESCE(MIN({column}), 0)::float8 AS lo, "
        f"COALESCE(MAX({column}), 0)::float8 AS hi, "
        f"COUNT(*)::bigint AS n "
        f"FROM {table}{_scope(run_id)}"
    )
    return sql, "range_0_1"


def _sql_non_negative(table: str, column: str, run_id: int | None = None) -> tuple[str, str]:
    sql = (
        f"SELECT "
        f"COUNT(*) FILTER (WHERE {column} < 0)::bigint AS violations, "
        f"COALESCE(MIN({column}), 0)::float8 AS lo, "
        f"COUNT(*)::bigint AS n "
        f"FROM {table}{_scope(run_id)}"
    )
    return sql, "non_negative"


def _sql_min_rows(table: str, minimum: int, run_id: int | None = None) -> tuple[str, str]:
    sql = f"SELECT COUNT(*)::bigint AS n FROM {table}{_scope(run_id)}"
    return sql, f"min_rows_{minimum}"


def latest_run_id(conn: psycopg.Connection) -> int | None:
    """Most recently started run, or None if the warehouse is empty."""
    with conn.cursor() as cur:
        cur.execute("SELECT run_id FROM sim_run ORDER BY started_at DESC, run_id DESC LIMIT 1")
        row = cur.fetchone()
    if row is None:
        return None
    return int(row["run_id"] if isinstance(row, dict) else row[0])


def _predicate_for(
    spec: AssertionSpec, run_id: int | None = None
) -> tuple[str, Callable[[dict[str, Any]], tuple[bool, str]]]:
    """Map a declared assertion to SQL + a pure pass/fail interpreter of the row."""
    table, column, _desc = spec

    if column == "*":
        if table == "tile_monthly":
            # tiles × months should be large once a multi-year run exists; floor is modest so a
            # short fixture can still pass, while empty warehouse fails.
            minimum = 1_000
            sql, _ = _sql_min_rows(table, minimum, run_id)

            def interpret(row: dict[str, Any], *, _min: int = minimum) -> tuple[bool, str]:
                n = int(row["n"])
                return n >= _min, f"row_count={n} minimum={_min}"

            return sql, interpret

        if table == "citizen_monthly":
            minimum = 10_000
            sql, _ = _sql_min_rows(table, minimum, run_id)

            def interpret(row: dict[str, Any], *, _min: int = minimum) -> tuple[bool, str]:
                n = int(row["n"])
                return n >= _min, f"row_count={n} minimum={_min}"

            return sql, interpret

        raise ValueError(f"no volume predicate for table={table}")

    # Range / sign predicates by description keywords and known columns.
    unit_cols = {
        ("citizen_monthly", "satisfaction"),
        ("road_monthly", "wear"),
        ("road_monthly", "congestion"),
        ("power_monthly", "outage_fraction"),
    }
    nonneg_cols = {
        ("citizen_monthly", "income"),
        ("budget_monthly", "income_tax_revenue"),
        ("water_monthly", "load_ratio"),
    }

    if (table, column) in unit_cols:
        sql, _ = _sql_range_unit(table, column, run_id)

        def interpret(row: dict[str, Any]) -> tuple[bool, str]:
            v = int(row["violations"])
            return v == 0, (
                f"violations={v} n={int(row['n'])} "
                f"min={float(row['lo']):.6g} max={float(row['hi']):.6g}"
            )

        return sql, interpret

    if (table, column) in nonneg_cols:
        sql, _ = _sql_non_negative(table, column, run_id)

        def interpret(row: dict[str, Any]) -> tuple[bool, str]:
            v = int(row["violations"])
            return v == 0, f"violations={v} n={int(row['n'])} min={float(row['lo']):.6g}"

        return sql, interpret

    raise ValueError(f"no SQL predicate for assertion {table}.{column}")


def assertion_sql(spec: AssertionSpec, run_id: int | None = None) -> str:
    """Public: the SQL that will be run for this assertion (for tests and docs)."""
    sql, _ = _predicate_for(spec, run_id)
    return sql


def evaluate_one(
    conn: psycopg.Connection,
    spec: AssertionSpec,
    run_id: int | None = None,
) -> AssertionResult:
    """Run one assertion against the live warehouse connection, scoped to one run."""
    table, column, description = spec
    sql, interpret = _predicate_for(spec, run_id)
    params = {"run_id": run_id} if run_id is not None else None
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        assert row is not None
        # psycopg dict_row or tuple
        if not isinstance(row, dict):
            # Fall back via cursor description
            cols = [d.name for d in cur.description]
            row = dict(zip(cols, row, strict=True))
    passed, detail = interpret(row)
    return AssertionResult(
        table=table,
        column=column,
        description=description,
        sql=sql,
        passed=passed,
        detail=detail,
    )


def evaluate_assertions(
    conn: psycopg.Connection,
    specs: tuple[AssertionSpec, ...] | None = None,
    run_id: int | None = None,
) -> list[AssertionResult]:
    """Evaluate every declared assertion. Order matches `ASSERTIONS`.

    `run_id` scopes every predicate to one simulation run. Pass None only to check the
    warehouse as a whole; the row-count assertions are not meaningful that way once more
    than one run has been loaded.
    """
    use = specs if specs is not None else ASSERTIONS
    return [evaluate_one(conn, spec, run_id) for spec in use]


def all_passed(results: list[AssertionResult]) -> bool:
    return all(r.passed for r in results)


def results_as_custom_properties(results: list[AssertionResult]) -> dict[str, str]:
    """Flat string map suitable for DataHub datasetProperties.customProperties."""
    out: dict[str, str] = {}
    for i, r in enumerate(results):
        key = f"assertion_result.{i}.{r.table}.{r.column}"
        out[key] = f"{'PASS' if r.passed else 'FAIL'}: {r.detail}"
        out[f"{key}.description"] = r.description
    out["assertion_results.summary"] = (
        f"{sum(1 for r in results if r.passed)}/{len(results)} passed"
    )
    out["assertion_results.all_passed"] = "true" if all_passed(results) else "false"
    return out
