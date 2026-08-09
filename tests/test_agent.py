"""The agent modes, tested without spending a token.

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
from blindcity.agent.llm import (
    GeminiClient,
    LocalClient,
    Reply,
    ToolCall,
    ToolResult,
    Turn,
    Usage,
)
from blindcity.agent.run import MODES
from blindcity.agent.tools import ToolContext, dispatch, set_levers, tool_declarations
from blindcity.levers import LEVERS, defaults


def _turn_as_dict(turn):
    return {
        "role": turn.role,
        "text": turn.text,
        "calls": [(c.name, c.args) for c in turn.calls],
        "results": [(r.call.name, r.payload) for r in turn.results],
    }


class FakeLLM:
    """Replays a scripted list of replies and records exactly what it was asked."""

    model = "fake-model"

    def __init__(self, replies: list[Reply] | None = None) -> None:
        self.replies = list(replies or [])
        self.systems: list[str] = []
        self.tool_sets: list[Any] = []
        self.contents: list[Any] = []
        self.usage = Usage()

    def generate(self, *, system, history, tools=None):
        self.systems.append(system)
        self.tool_sets.append(tools)
        # Serialised so a later mutation of the live objects cannot rewrite what we recorded.
        self.contents.append([_turn_as_dict(x) for x in history])
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

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConn:
    def __init__(self) -> None:
        self.cursor_obj = FakeCursor()
        self.committed = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def controllers(monkeypatch):
    """Both modes, built identically apart from the catalog."""
    monkeypatch.setattr("blindcity.agent.runscope.create_run_views", lambda conn, run_id: "run_1")
    monkeypatch.setattr("blindcity.agent.runscope.scope_connection", lambda conn, run_id: None)

    class StubCatalog:
        name = "datahub"

        def context_block(self) -> str:
            return "## Data catalog\n\n### road_monthly\nWear and congestion per segment."

    def build(catalog, llm):
        return AgentController(
            name="mode", llm=llm, conn=FakeConn(), run_id=1, catalog=catalog, turn_budget=36
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
        assert leak not in lowered, f"control mode's prompt mentions {leak!r}"


def test_both_arms_get_identical_tools(controllers):
    """A difference in tool wording is a difference in capability."""
    build, catalog = controllers
    raw_llm, hub_llm = FakeLLM(), FakeLLM()
    build(NoCatalog(), raw_llm).decide(_state(), 0, {})
    build(catalog, hub_llm).decide(_state(), 0, {})
    assert raw_llm.tool_sets == hub_llm.tool_sets
    assert raw_llm.tool_sets[0] == tool_declarations()


def test_both_arms_get_identical_turn_prompts(controllers):
    """The per-turn message carries no mode-specific content either."""
    build, catalog = controllers
    raw_llm, hub_llm = FakeLLM(), FakeLLM()
    build(NoCatalog(), raw_llm).decide(_state(), 3, {})
    build(catalog, hub_llm).decide(_state(), 3, {})
    assert raw_llm.contents[0] == hub_llm.contents[0]


def test_arm_definitions_differ_only_in_context():
    """Two modes, two context values, one implementation."""
    assert set(MODES) == {"agent_datahub", "agent_raw"}
    assert MODES["agent_datahub"] == "datahub"
    assert MODES["agent_raw"] == "none"
    assert isinstance(build_catalog("none"), NoCatalog)
    assert isinstance(build_catalog("datahub"), DataHubCatalog)


# --- Information parity with the human mode --------------------------------------------------


def test_turn_prompt_carries_no_city_state(controllers):
    """The agent must discover the city through SQL. A figure in the prompt is a channel the
    other modes do not have — the same rule that forbids a dashboard in the viewer.

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
    """Neither mode may be told how it is graded. An agent that knows the weights optimises the
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
    return ToolCall(name=name, args=args, id="fixed-id")


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
    """The mode is scored on a city it failed to steer. That is a real outcome, not a crash."""
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


# --- Catalog write-back ---------------------------------------------------------------------


def test_writeback_finds_only_real_tables():
    """Table names are matched against the schema, so a CTE alias or an information_schema
    probe never becomes a dataset URN that does not exist."""
    from blindcity.agent.writeback import tables_queried

    counts = tables_queried(
        [
            "SELECT * FROM road_monthly WHERE tick > 60",
            "SELECT table_name FROM information_schema.tables",
            "WITH recent AS (SELECT * FROM water_monthly) SELECT * FROM recent",
            "SELECT a.wear FROM public.road_monthly a JOIN budget_monthly b ON a.tick = b.tick",
        ]
    )
    assert counts == {"road_monthly": 2, "water_monthly": 1, "budget_monthly": 1}
    assert "recent" not in counts
    assert "tables" not in counts


def test_writeback_skips_the_control_arm():
    """Giving agent_raw a write path would be a second difference between the modes."""
    from blindcity.agent.writeback import write_back

    out = write_back({"catalog": "none", "turns": []}, "1")
    assert out.datasets == 0
    assert "control mode" in out.skipped


def test_writeback_preserves_existing_documentation(monkeypatch):
    """UPSERT replaces the whole aspect. Writing only the new keys would strip the table's
    description — the very thing agent_datahub depends on — a little more with every run."""
    from blindcity.agent import writeback

    emitted: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        writeback,
        "_emit_mcp",
        lambda gms, urn, aspect_name, aspect: emitted.append((urn, aspect_name, aspect)),
    )
    monkeypatch.setattr(
        writeback,
        "_current_properties",
        lambda client, gms, urn: {
            "name": "road_monthly",
            "description": "Traffic, wear, and congestion per segment per month.",
            "customProperties": {"agent_finding.7.mode": "agent_datahub"},
        },
    )

    report = {
        "catalog": "datahub",
        "controller": "agent_datahub",
        "turns": [
            {"queries": ["SELECT wear FROM road_monthly"], "rationale": "Roads are the problem."}
        ],
    }
    out = writeback.write_back(report, "9")

    assert out.datasets == 1
    _urn, aspect_name, aspect = emitted[0]
    assert aspect_name == "datasetProperties"
    assert aspect["description"] == "Traffic, wear, and congestion per segment per month."
    # The earlier run's finding survives alongside the new one.
    assert aspect["customProperties"]["agent_finding.7.mode"] == "agent_datahub"
    assert aspect["customProperties"]["agent_finding.9.conclusion"] == "Roads are the problem."


def test_writeback_records_failures_rather_than_swallowing_them(monkeypatch):
    """A silent skip looks identical to an agent that found nothing worth writing."""
    from blindcity.agent import writeback

    monkeypatch.setattr(
        writeback, "_current_properties", lambda client, gms, urn: {"customProperties": {}}
    )

    def boom(*args, **kwargs):
        raise RuntimeError("GMS is down")

    monkeypatch.setattr(writeback, "_emit_mcp", boom)
    out = writeback.write_back(
        {"catalog": "datahub", "turns": [{"queries": ["SELECT 1 FROM road_monthly"]}]}, "9"
    )
    assert out.datasets == 0
    assert "GMS is down" in out.failures["road_monthly"]


def test_sql_row_cap_is_enforced_in_sql_not_in_python():
    """psycopg's default cursor is client-side: `execute` pulls the whole result set before a
    single row is read. Capping with `fetchmany` let a `SELECT * FROM citizen_monthly` drag
    ~290k rows across the wire and stall a one-turn run past nine minutes."""
    ctx = ToolContext(conn=FakeConn(), run_id=1, levers=defaults())
    dispatch(ctx, "sql_query", {"query": "SELECT * FROM citizen_monthly"})
    executed = ctx.conn.cursor_obj.executed[0].lower()
    assert "limit" in executed, f"no server-side cap in: {executed}"
    assert "select * from citizen_monthly" in executed


def test_truncated_results_say_so():
    """A silently clipped result invites a conclusion drawn from the first fifty rows of an
    unordered scan."""
    from blindcity.agent.tools import MAX_ROWS

    conn = FakeConn()
    conn.cursor_obj.description = [_Col("n")]
    conn.cursor_obj.rows = [{"n": i} for i in range(MAX_ROWS + 1)]
    ctx = ToolContext(conn=conn, run_id=1, levers=defaults())
    out = dispatch(ctx, "sql_query", {"query": "SELECT n FROM t"})
    assert out["truncated"] is True
    assert out["row_count"] == MAX_ROWS
    assert "cut off" in out["note"]


def test_exactly_full_page_is_not_reported_as_truncated():
    from blindcity.agent.tools import MAX_ROWS

    conn = FakeConn()
    conn.cursor_obj.description = [_Col("n")]
    conn.cursor_obj.rows = [{"n": i} for i in range(MAX_ROWS)]
    ctx = ToolContext(conn=conn, run_id=1, levers=defaults())
    out = dispatch(ctx, "sql_query", {"query": "SELECT n FROM t"})
    assert out["truncated"] is False
    assert out["row_count"] == MAX_ROWS


# --- Backends -------------------------------------------------------------------------------
#
# The controller holds the conversation in a provider-neutral form and each backend serialises
# it. These assert the serialisation, so a backend cannot quietly hand one mode a differently
# shaped conversation than the other.


def _history():
    call = ToolCall(name="sql_query", args={"query": "SELECT 1"}, id="c1")
    return [
        Turn(role="user", text="Turn 1."),
        Turn(role="model", text="Looking.", calls=[call]),
        Turn(role="user", results=[ToolResult(call=call, payload={"rows": [[1]]})]),
    ]




def test_local_backend_serialises_a_tool_round_trip():
    messages = LocalClient._messages("SYS", _history())
    assert messages[0] == {"role": "system", "content": "SYS"}
    assert messages[1] == {"role": "user", "content": "Turn 1."}
    assistant = messages[2]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["function"]["name"] == "sql_query"
    # Arguments go over the wire as a JSON *string*, not an object.
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"query": "SELECT 1"}
    # Results are keyed back to the call id, or the server cannot match them up.
    assert messages[3]["role"] == "tool"
    assert messages[3]["tool_call_id"] == "c1"


def test_gemini_backend_serialises_a_tool_round_trip():
    contents = GeminiClient._contents(_history())
    assert contents[0] == {"role": "user", "parts": [{"text": "Turn 1."}]}
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"][-1]["functionCall"]["name"] == "sql_query"
    # Gemini returns tool output in the *user* role, as functionResponse parts.
    assert contents[2]["role"] == "user"
    assert contents[2]["parts"][0]["functionResponse"]["name"] == "sql_query"


def test_backends_agree_on_the_tool_set():
    """One declaration, two wire formats. Gemini wants upper-case OpenAPI type names; an
    OpenAI-compatible server wants plain JSON Schema nested under a `function` key."""
    declared = tool_declarations()
    local = LocalClient._tools(declared)
    gemini = GeminiClient._tools(declared)

    assert [t["function"]["name"] for t in local] == [d["name"] for d in declared]
    assert local[0]["function"]["parameters"]["type"] == "object"
    assert gemini[0]["parameters"]["type"] == "OBJECT"
    # Same tools, same descriptions - only the casing and nesting differ.
    assert [t["name"] for t in gemini] == [d["name"] for d in declared]
    assert gemini[0]["description"] == declared[0]["description"]


def test_provider_factory_rejects_an_unknown_provider():
    from blindcity.agent.llm import LLMError, build_llm

    with pytest.raises(LLMError, match="unknown LLM_PROVIDER"):
        build_llm("hal9000")


def test_sql_tool_ends_its_transaction():
    """psycopg opens a transaction on execute. A SELECT that is never committed leaves the
    session idle-in-transaction holding locks on every view it touched — which deadlocked a
    completed run against its own DROP SCHEMA cleanup for 27 minutes."""
    conn = FakeConn()
    conn.cursor_obj.description = [_Col("n")]
    conn.cursor_obj.rows = [{"n": 1}]
    ctx = ToolContext(conn=conn, run_id=1, levers=defaults())
    dispatch(ctx, "sql_query", {"query": "SELECT n FROM t"})
    assert conn.rollbacks >= 1, "read transaction was left open"


def test_tool_calls_are_timed():
    """A run that reports LLM seconds and total seconds with nothing in between cannot say
    where its time went — which is how 90% of one run stayed unexplained."""
    ctx = ToolContext(conn=FakeConn(), run_id=1, levers=defaults())
    dispatch(ctx, "sql_query", {"query": "SELECT 1"})
    assert ctx.log[0].seconds >= 0.0
    assert hasattr(ctx.log[0], "seconds")


# --- Robustness ------------------------------------------------------------------------------


def test_backoff_is_jittered_and_capped():
    """Both modes hammer one endpoint and a turn fires several calls together. Without jitter,
    everything rate-limited together retries together and collides again on every attempt."""
    from blindcity.agent.llm import _HttpClient

    c = _HttpClient(timeout=1, max_retries=5, min_interval=0, backoff_base=4.0, backoff_cap=90.0)
    waits = [c._backoff(6, None) for _ in range(40)]
    assert len(set(waits)) > 30, "backoff is not jittered"
    assert max(waits) <= c.backoff_cap, "backoff exceeded its cap"
    assert min(waits) >= 0.0


def test_backoff_prefers_a_provider_supplied_delay():
    """A provider that states its own retry delay knows better than our guess."""
    from blindcity.agent.llm import _HttpClient

    c = _HttpClient(timeout=1, max_retries=3, min_interval=0)
    waits = [c._backoff(0, 30.0) for _ in range(20)]
    assert all(30.0 <= w <= 32.0 for w in waits), waits
    assert len(set(waits)) > 1, "provider delay should still carry a little jitter"


def test_sql_survives_a_dropped_warehouse_connection():
    """Docker has dropped the warehouse mid-run more than once. Losing a scored mode to a
    container restart is far worse than retrying one query."""
    import psycopg

    dead = FakeConn()

    def explode(sql, params=None):
        raise psycopg.OperationalError("server closed the connection unexpectedly")

    dead.cursor_obj.execute = explode

    fresh = FakeConn()
    fresh.cursor_obj.description = [_Col("n")]
    fresh.cursor_obj.rows = [{"n": 7}]

    ctx = ToolContext(conn=dead, run_id=1, levers=defaults(), reconnect=lambda: fresh)
    out = dispatch(ctx, "sql_query", {"query": "SELECT n FROM t"})
    assert out.get("rows") == [[7]], out
    assert ctx.conn is fresh


def test_sql_reports_clearly_when_the_warehouse_is_gone():
    """With no way to reconnect, the model gets an error it can see rather than a crash."""
    import psycopg

    dead = FakeConn()

    def explode(sql, params=None):
        raise psycopg.OperationalError("connection refused")

    dead.cursor_obj.execute = explode
    ctx = ToolContext(conn=dead, run_id=1, levers=defaults())
    out = dispatch(ctx, "sql_query", {"query": "SELECT 1"})
    assert "warehouse unavailable" in out["error"]
