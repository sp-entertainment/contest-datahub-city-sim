"""Assertion SQL evaluation — pass/fail must reflect real warehouse predicates.

A catalog that only declares assertions and always emits SUCCESS is worse than silent:
it is actively misleading. These tests drive the real predicate logic so a constant
"always pass" implementation fails.
"""

from __future__ import annotations

from typing import Any

from blindcity.catalog.assertions import (
    AssertionResult,
    assertion_sql,
    evaluate_one,
    results_as_custom_properties,
)
from blindcity.catalog.schema_spec import ASSERTIONS


class _FakeCursor:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row
        self.description = [type("C", (), {"name": k})() for k in row]
        self.executed_sql: str | None = None

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> None:
        self.executed_sql = sql

    def fetchone(self) -> dict[str, Any]:
        return self._row

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class _FakeConn:
    """Minimal connection stub: returns a fixed row for whatever SQL is run."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.cursor_obj = _FakeCursor(row)

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj


def _spec(table: str, column: str) -> tuple[str, str, str]:
    for s in ASSERTIONS:
        if s[0] == table and s[1] == column:
            return s
    raise KeyError(f"missing assertion {table}.{column}")


def test_every_declared_assertion_has_sql():
    """No assertion may be metadata-only without an executable predicate."""
    for spec in ASSERTIONS:
        sql = assertion_sql(spec)
        assert "SELECT" in sql.upper()
        assert spec[0] in sql  # table name appears


def test_satisfaction_in_range_passes():
    spec = _spec("citizen_monthly", "satisfaction")
    conn = _FakeConn({"violations": 0, "lo": 0.1, "hi": 0.9, "n": 100})
    result = evaluate_one(conn, spec)  # type: ignore[arg-type]
    assert result.passed is True
    assert "violations=0" in result.detail


def test_satisfaction_out_of_range_fails():
    """A constant always-pass implementation fails this case."""
    spec = _spec("citizen_monthly", "satisfaction")
    conn = _FakeConn({"violations": 12, "lo": -0.2, "hi": 1.4, "n": 100})
    result = evaluate_one(conn, spec)  # type: ignore[arg-type]
    assert result.passed is False
    assert "violations=12" in result.detail


def test_income_non_negative_fails_on_negatives():
    spec = _spec("citizen_monthly", "income")
    conn = _FakeConn({"violations": 3, "lo": -50.0, "n": 10})
    result = evaluate_one(conn, spec)  # type: ignore[arg-type]
    assert result.passed is False


def test_income_non_negative_passes_when_clean():
    spec = _spec("citizen_monthly", "income")
    conn = _FakeConn({"violations": 0, "lo": 0.0, "n": 10})
    result = evaluate_one(conn, spec)  # type: ignore[arg-type]
    assert result.passed is True


def test_volume_assertion_fails_when_too_few_rows():
    spec = _spec("citizen_monthly", "*")
    conn = _FakeConn({"n": 50})
    result = evaluate_one(conn, spec)  # type: ignore[arg-type]
    assert result.passed is False
    assert "row_count=50" in result.detail


def test_volume_assertion_passes_when_large_enough():
    spec = _spec("citizen_monthly", "*")
    conn = _FakeConn({"n": 50_000})
    result = evaluate_one(conn, spec)  # type: ignore[arg-type]
    assert result.passed is True


def test_results_as_custom_properties_reports_fail():
    results = [
        AssertionResult(
            table="road_monthly",
            column="wear",
            description="Road wear is in [0, 1].",
            sql="SELECT 1",
            passed=False,
            detail="violations=1 n=10 min=-0.1 max=0.5",
        ),
        AssertionResult(
            table="road_monthly",
            column="congestion",
            description="Congestion is in [0, 1].",
            sql="SELECT 1",
            passed=True,
            detail="violations=0 n=10 min=0 max=1",
        ),
    ]
    props = results_as_custom_properties(results)
    assert props["assertion_results.all_passed"] == "false"
    assert "1/2 passed" in props["assertion_results.summary"]
    assert any("FAIL" in v for v in props.values())


def test_range_sql_mentions_column_bounds():
    sql = assertion_sql(_spec("road_monthly", "congestion"))
    assert "congestion" in sql
    assert "road_monthly" in sql
    # Must actually check bounds, not just SELECT the column.
    assert "< 0" in sql or "> 1" in sql
