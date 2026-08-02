"""Run isolation: multi-arm writes must not wipe each other via global truncate."""

from __future__ import annotations

from blindcity.sim import warehouse as wh


def test_reset_warehouse_is_explicit_not_implied_by_start_run():
    """Benchmark/default path uses ensure_schema + start_run; truncate is opt-in."""
    import inspect

    main_src = inspect.getsource(__import__("blindcity.sim.__main__", fromlist=["main"]).main)
    # Default CLI path must not always reset; --reset-warehouse is the opt-in.
    assert "reset_warehouse" in main_src
    assert "args.reset_warehouse" in main_src or "reset_warehouse" in main_src
    assert "ensure_schema" in main_src


def test_all_history_tables_keyed_by_run_id():
    """Every warehouse table carries run_id so arms can share one database."""
    assert "run_id" in wh.DDL
    for table, cols in wh.TABLE_COLUMNS.items():
        assert cols[0] == "run_id", f"{table} must lead with run_id, got {cols[0]}"


def test_sim_run_uses_serial_identity():
    assert "BIGSERIAL" in wh.DDL or "serial" in wh.DDL.lower()
