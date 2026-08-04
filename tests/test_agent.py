"""The agent arms, tested without spending a token.

The headline result is `agent_datahub` versus `agent_raw`, and it is only worth anything if the
two differ in exactly one thing. That is a property of the code, so it is tested like one. Every
test here runs against a fake LLM and a fake database — no API key, no Docker, no cost.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from blindcity.agent.catalog import DataHubCatalog, NoCatalog, build_catalog
from blindcity.agent.controller import SYSTEM_PROMPT, AgentController
from blindcity.agent.llm import Reply, Usage
from blindcity.agent.run import ARMS
from blindcity.agent.tools import ToolContext, dispatch, set_levers, tool_declarations
from blindcity.levers import LEVERS, defaults


class FakeLLM:
    """Replays a scripted list of replies and records exactly what it was asked."""

    model = "fake-model"

    def __init__(self, replies: list[Reply] | None = None) -> None:
        self.replies = list(replies or [])
        self.systems: list[str] = []
        self.tool_sets: list[Any] = []
        self.contents: list[Any] = []
        self.usage = Usage()

    def generate(self, *, system, contents, tools=None):
        self.systems.append(system)
        self.tool_sets.append(tools)
        self.contents.append(json.loads(json.dumps(contents)))
        if self.replies:
            return self.replies.pop(0)
        return Reply(text="done", calls=[], usage=Usage(calls=1))


@dataclass
class _Col:
    name: str


@dataclass
class FakeCursor:
    """Mimics the real cursor, which uses psycopg's `dict_row` factory.

    Returning tuples here — as an earlier version did — is what let a live bug through: the SQL
    tool iterated rows directly, which on a mapping yields column *names*, so the model received
    a table of its own headers. A fake that is shaped differently from production tests nothing.
    """

    rows: list[dict[str, Any]] = field(default_factory=list)
    description: Any = None
    executed: list[str] = field(default_factory=list)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append(sql)

    def fetchmany(self, n):
        return self.rows[:n]

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConn:
    def __init__(self) -> None:
        self.cursor_obj = FakeCursor()
        self.committed = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass


@pytest.fixture
def controllers(monkeypatch):
    """Both arms, built identically apart from the catalog."""
    monkeypatch.setattr("blindcity.agent.runscope.create_run_views", lambda conn, run_id: "run_1")
    monkeypatch.setattr("blindcity.agent.runscope.scope_connection", lambda conn, run_id: None)

    class StubCatalog:
        name = "datahub"

        def context_block(self) -> str:
            return "## Data catalog\n\n### road_monthly\nWear and congestion per segment."

    def build(catalog, llm):
        return AgentController(
            name="arm", llm=llm, conn=FakeConn(), run_id=1, catalog=catalog, turn_budget=36
        )

    return build, StubCatalog()


# --- The parity guarantee ------------------------------------------------------------------


def test_arms_differ_only_in_catalog_context(controllers):
    """The whole result rests on this. `agent_datahub`'s prompt must be `agent_raw`'s prompt
    with a catalog block appended, and nothing else changed anywhere."""
    build, catalog = controllers
    raw = build(NoCatalog(), FakeLLM())
    hub = build(catalog, FakeLLM())

    assert raw._system == SYSTEM_PROMPT
    assert hub._system.startswith(SYSTEM_PROMPT)
    # Everything before the catalog block is byte-identical.
    assert hub._system[: len(raw._system)] == raw._system
    assert catalog.context_block() in hub._system


def test_control_arm_gets_no_placeholder(controllers):
    """Not even a note saying it has no catalog — that would itself be information."""
    build, _ = controllers
    raw = build(NoCatalog(), FakeLLM())
    lowered = raw._system.lower()
    for leak in ("catalog", "datahub", "glossary", "lineage", "metadata"):
        assert leak not in lowered, f"control arm's prompt mentions {leak!r}"


def test_both_arms_get_identical_tools(controllers):
    """A difference in tool wording is a difference in capability."""
    build, catalog = controllers
    raw_llm, hub_llm = FakeLLM(), FakeLLM()
    build(NoCatalog(), raw_llm).decide(_state(), 0, {})
    build(catalog, hub_llm).decide(_state(), 0, {})
    assert raw_llm.tool_sets == hub_llm.tool_sets
    assert raw_llm.tool_sets[0] == tool_declarations()


def test_both_arms_get_identical_turn_prompts(controllers):
    """The per-turn message carries no arm-specific content either."""
    build, catalog = controllers
    raw_llm, hub_llm = FakeLLM(), FakeLLM()
    build(NoCatalog(), raw_llm).decide(_state(), 3, {})
    build(catalog, hub_llm).decide(_state(), 3, {})
    assert raw_llm.contents[0] == hub_llm.contents[0]


def test_arm_definitions_differ_only_in_context():
    """Two arms, two context values, one implementation."""
    assert set(ARMS) == {"agent_datahub", "agent_raw"}
    assert ARMS["agent_datahub"] == "datahub"
    assert ARMS["agent_raw"] == "none"
    assert isinstance(build_catalog("none"), NoCatalog)
    assert isinstance(build_catalog("datahub"), DataHubCatalog)


# --- Information parity with the human arm --------------------------------------------------


def test_turn_prompt_carries_no_city_state(controllers):
    """The agent must discover the city through SQL. A figure in the prompt is a channel the
    other arms do not have — the same rule that forbids a dashboard in the viewer.

    Scoped to the per-turn message. The system prompt is allowed to state the goal ("get the
    city healthy"), which is the task, not an observation of the city.
    """
    build, _ = controllers
    llm = FakeLLM()
    build(NoCatalog(), llm).decide(_state(), 0, {})
    turn_prompt = json.dumps(llm.contents[0]).lower()
    for leak in ("population", "treasury", "satisfaction", "wear", "congestion", "outage"):
        assert leak not in turn_prompt, f"turn prompt carries {leak!r}"


def test_no_prompt_reveals_the_scoring_function(controllers):
    """Neither arm may be told how it is graded. An agent that knows the weights optimises the
    index; an agent that does not has to fix the city, which is the thing being measured."""
    build, catalog = controllers
    llm = FakeLLM()
    build(catalog, llm).decide(_state(), 0, {})
    everything = (json.dumps(llm.contents[0]) + llm.systems[0]).lower()
    for leak in ("health index", "threshold", "0.62", "solvency", "composite", "score"):
        assert leak not in everything, f"prompt reveals the scoring function: {leak!r}"


def test_prompt_shows_current_levers(controllers):
    """Lever positions are the controller's own input, and are the one exemption."""
    build, _ = controllers
    llm = FakeLLM()
    build(NoCatalog(), llm).decide(_state(), 0, {})
    prompt = json.dumps(llm.contents[0])
    for name in LEVERS:
        assert name in prompt


# --- Tools ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM citizen_monthly",
        "DROP TABLE road_monthly",
        "UPDATE lever_monthly SET income_tax_rate = 0",
        "INSERT INTO ticks VALUES (1)",
        "TRUNCATE tiles",
    ],
)
def test_sql_tool_refuses_writes(query):
    ctx = ToolContext(conn=FakeConn(), run_id=1, levers=defaults())
    result = dispatch(ctx, "sql_query", {"query": query})
    assert "error" in result
    assert not ctx.conn.cursor_obj.executed, "a write reached the database"


def test_sql_tool_refuses_a_write_smuggled_after_a_select():
    ctx = ToolContext(conn=FakeConn(), run_id=1, levers=defaults())
    result = dispatch(ctx, "sql_query", {"query": "SELECT 1; DROP TABLE tiles"})
    assert "error" in result
    assert not ctx.conn.cursor_obj.executed


def test_sql_tool_allows_select_and_with():
    ctx = ToolContext(conn=FakeConn(), run_id=1, levers=defaults())
    for query in ("SELECT 1", "WITH t AS (SELECT 1) SELECT * FROM t"):
        assert "error" not in dispatch(ctx, "sql_query", {"query": query})
    assert len(ctx.conn.cursor_obj.executed) == 2


def test_sql_tool_returns_values_not_column_names():
    """The regression that cost a live run: rows come back as mappings, and iterating a mapping
    yields its keys. The model was handed a table of its own headers and, seeing no data, asked
    the same question six ways until the turn budget ran out."""
    conn = FakeConn()
    conn.cursor_obj.description = [_Col("table_name"), _Col("n_rows")]
    conn.cursor_obj.rows = [
        {"table_name": "road_monthly", "n_rows": 106763},
        {"table_name": "citizen_monthly", "n_rows": 808597},
    ]
    ctx = ToolContext(conn=conn, run_id=1, levers=defaults())
    out = dispatch(ctx, "sql_query", {"query": "SELECT table_name, n_rows FROM t"})
    assert out["columns"] == ["table_name", "n_rows"]
    assert out["rows"] == [["road_monthly", 106763], ["citizen_monthly", 808597]]
    assert out["row_count"] == 2


def test_levers_are_clamped_not_rejected():
    """A bad decision must stay a bad decision rather than becoming an error the model can
    retry its way out of."""
    ctx = ToolContext(conn=FakeConn(), run_id=1, levers=defaults())
    out = set_levers(ctx, {"income_tax_rate": 4.0})
    assert out["applied"]["income_tax_rate"] == LEVERS["income_tax_rate"].maximum
    assert "clamped" in out


def test_unknown_levers_are_reported_with_the_valid_names():
    ctx = ToolContext(conn=FakeConn(), run_id=1, levers=defaults())
    out = set_levers(ctx, {"interest_rate": 0.5, "income_tax_rate": 0.1})
    assert "interest_rate" in out["rejected"]
    assert out["applied"] == {"income_tax_rate": 0.1}
    assert out["valid_levers"] == sorted(LEVERS)


def test_unknown_tool_is_reported_not_raised():
    ctx = ToolContext(conn=FakeConn(), run_id=1, levers=defaults())
    assert "error" in dispatch(ctx, "demolish_city", {})


# --- The loop -------------------------------------------------------------------------------


def _state():
    class S:
        levers = defaults()

    return S()


def _call(name, args):
    from blindcity.agent.llm import FunctionCall

    return FunctionCall(name=name, args=args)


def test_decide_returns_the_levers_the_model_set(controllers):
    build, _ = controllers
    llm = FakeLLM(
        [
            Reply(calls=[_call("sql_query", {"query": "SELECT 1"})], usage=Usage(calls=1)),
            Reply(
                text="Roads are the problem.",
                calls=[_call("set_levers", {"levers": {"road_maintenance_budget": 5_000_000}})],
                usage=Usage(calls=1),
            ),
        ]
    )
    controller = build(NoCatalog(), llm)
    assert controller.decide(_state(), 0, {}) == {"road_maintenance_budget": 5_000_000.0}
    assert controller.history[0].sql_calls == 1
    assert controller.history[0].rationale == "Roads are the problem."


def test_committing_ends_the_turn(controllers):
    """Once levers are set the turn is over, so a talkative model cannot buy extra tool calls."""
    build, _ = controllers
    llm = FakeLLM(
        [
            Reply(calls=[_call("set_levers", {"levers": {"transit_fare": 1.0}})], usage=Usage()),
            Reply(calls=[_call("sql_query", {"query": "SELECT 2"})], usage=Usage()),
        ]
    )
    build(NoCatalog(), llm).decide(_state(), 0, {})
    assert len(llm.systems) == 1, "model was called again after committing"


def test_tool_budget_is_enforced(controllers):
    """A model that never commits must still yield the turn."""
    build, _ = controllers
    llm = FakeLLM([Reply(calls=[_call("sql_query", {"query": "SELECT 1"})]) for _ in range(50)])
    controller = build(NoCatalog(), llm)
    controller.tool_budget = 4
    assert controller.decide(_state(), 0, {}) == {}
    assert len(llm.systems) == 4


def test_llm_failure_costs_the_turn_rather_than_the_run(controllers):
    """The arm is scored on a city it failed to steer. That is a real outcome, not a crash."""
    from blindcity.agent.llm import LLMError

    build, _ = controllers

    class Failing(FakeLLM):
        def generate(self, **kwargs):
            raise LLMError("429 rate limited")

    controller = build(NoCatalog(), Failing())
    assert controller.decide(_state(), 0, {}) == {}
    assert controller.history[0].error is not None


def test_report_captures_what_an_auditor_needs(controllers):
    build, catalog = controllers
    controller = build(catalog, FakeLLM())
    controller.decide(_state(), 0, {})
    report = controller.report()
    for key in ("controller", "model", "catalog", "tool_budget", "usage", "turns"):
        assert key in report
    assert report["catalog"] == "datahub"
