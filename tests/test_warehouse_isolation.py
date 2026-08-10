"""Run isolation: one run's rows must never be mistaken for another's.

Two mechanisms, pulling in opposite directions and both needed. `sim` appends by `run_id` so a
demo load cannot destroy a benchmark. `agent` clears the warehouse before every run so no run
inherits another's rows, planner statistics, or leftover views — during development a clean slate
is worth more than an archive, and it keeps the two modes facing byte-identical conditions.
"""

from __future__ import annotations

from typing import Any

import pytest

from blindcity.sim import warehouse as wh


class ScriptedCursor:
    """A cursor that answers `fetchall` from a queue, so a multi-query function can be driven."""

    def __init__(self, answers: list[list[dict[str, Any]]] | None = None) -> None:
        self.answers = list(answers or [])
        self.executed: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append(str(sql))

    def fetchall(self):
        return self.answers.pop(0) if self.answers else []

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class ScriptedConn:
    def __init__(self, answers: list[list[dict[str, Any]]] | None = None) -> None:
        self.cursor_obj = ScriptedCursor(answers)
        self.committed = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def test_reset_warehouse_is_explicit_not_implied_by_start_run():
    """Benchmark/default path uses ensure_schema + start_run; truncate is opt-in."""
    import inspect

    from blindcity.commands import sim as sim_cmd

    main_src = inspect.getsource(sim_cmd.run)
    # Default CLI path must not always reset; --reset-warehouse is the opt-in.
    assert "reset_warehouse" in main_src
    assert "args.reset_warehouse" in main_src
    assert "ensure_schema" in main_src


def test_all_history_tables_keyed_by_run_id():
    """Every warehouse table carries run_id so modes can share one database."""
    assert "run_id" in wh.DDL
    for table, cols in wh.TABLE_COLUMNS.items():
        assert cols[0] == "run_id", f"{table} must lead with run_id, got {cols[0]}"


def test_sim_run_uses_serial_identity():
    assert "BIGSERIAL" in wh.DDL or "serial" in wh.DDL.lower()


def test_runs_in_flight_is_empty_when_the_warehouse_has_never_been_built():
    """The first run of a fresh database must not trip the guard against clearing a live run."""
    conn = ScriptedConn([[{"present": False}]])
    assert wh.runs_in_flight(conn) == []


def test_runs_in_flight_reports_unfinished_runs():
    conn = ScriptedConn([[{"present": True}], [{"run_id": 12}, {"run_id": 14}]])
    assert wh.runs_in_flight(conn) == [12, 14]
    # Age is decided in SQL, not in Python: the query must bound how far back it looks, or every
    # run ever killed would block every reset forever.
    assert any("started_at" in s for s in conn.cursor_obj.executed)


def test_agent_refuses_to_clear_the_warehouse_under_a_live_run(monkeypatch):
    """Clearing by default is only safe because it stops when something is still playing.

    Two modes are scored one after another against the same database. A reset that fired while
    the other mode was mid-run would delete the city it was reasoning about, and the run would
    keep going and produce a plausible number from nothing.
    """
    from blindcity.agent import run as agent_run

    monkeypatch.setattr(agent_run, "connect", lambda: ScriptedConn())
    monkeypatch.setattr(agent_run, "ensure_schema", lambda conn: None)
    monkeypatch.setattr(agent_run, "runs_in_flight", lambda conn: [41])
    monkeypatch.setattr(
        agent_run,
        "reset_warehouse",
        lambda conn: pytest.fail("reset ran despite a live run"),
    )
    monkeypatch.setattr(agent_run, "build_llm", lambda **kw: object())

    with pytest.raises(wh.WarehouseInUse) as exc:
        agent_run.run_mode("agent_raw", llm=object())
    assert "41" in str(exc.value)


def test_force_clean_overrides_the_live_run_guard(monkeypatch):
    from blindcity.agent import run as agent_run

    reset_calls: list[int] = []
    monkeypatch.setattr(agent_run, "connect", lambda: ScriptedConn())
    monkeypatch.setattr(agent_run, "ensure_schema", lambda conn: None)
    monkeypatch.setattr(agent_run, "runs_in_flight", lambda conn: [41])
    monkeypatch.setattr(agent_run, "reset_warehouse", lambda conn: reset_calls.append(1))
    monkeypatch.setattr(agent_run.runscope, "drop_all_run_views", lambda conn: [])
    # Stop the run immediately after the reset decision; nothing past it is under test.
    monkeypatch.setattr(
        agent_run.RunHarness, "prepare", lambda self, **kw: (_ for _ in ()).throw(RuntimeError("stop"))
    )

    with pytest.raises(RuntimeError, match="stop"):
        agent_run.run_mode("agent_raw", llm=object(), force_clean=True)
    assert reset_calls == [1]


def test_clearing_removes_view_schemas_before_the_tables_they_read():
    """DROP TABLE CASCADE takes a view but leaves its schema, so `run_N` shells would pile up."""
    import inspect

    src = inspect.getsource(wh.reset_warehouse)
    assert "CASCADE" in src
    run_src = inspect.getsource(__import__("blindcity.agent.run", fromlist=["run_mode"]).run_mode)
    views_at = run_src.index("drop_all_run_views")
    reset_at = run_src.index("reset_warehouse(conn)")
    assert views_at < reset_at, "view schemas must be dropped before the tables they depend on"


def test_drop_all_run_views_does_not_consult_run_state():
    """It is the reset path's tool, and the reset path has already decided. The age check lives
    in `drop_stale_run_views`; a flag that switched it off would make the two calls look alike."""
    import inspect

    from blindcity.agent import runscope

    src = inspect.getsource(runscope.drop_all_run_views)
    assert "sim_run" not in src and "finished_at" not in src

    conn = ScriptedConn([[{"nspname": "run_3"}, {"nspname": "run_9"}]])
    assert runscope.drop_all_run_views(conn) == ["run_3", "run_9"]


def test_run_cli_clears_by_default_and_can_opt_out():
    """The default is the clean slate; --keep-warehouse is the escape hatch, not the reverse.

    The two defaults are deliberately opposite: `blindcity sim` appends because it builds history
    worth keeping, `blindcity run` clears because a benchmark run must not inherit another run's
    rows, planner statistics or leftover views.
    """
    import inspect

    from blindcity import cli
    from blindcity.commands import run as run_cmd

    assert "--keep-warehouse" in inspect.getsource(cli.build_parser)
    assert "clean_warehouse=not args.keep_warehouse" in inspect.getsource(run_cmd.run)
