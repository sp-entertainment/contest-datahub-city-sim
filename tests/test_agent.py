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
    Reply,
    ResponsesClient,
    ToolCall,
    ToolResult,
    Turn,
    Usage,
    user_turn,
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


def test_mode_definitions_differ_only_in_context():
    """Three modes, one implementation, each differing from the last by one named capability.

    `agent_raw` -> `agent_datahub` adds the static catalog. `agent_datahub` ->
    `agent_datahub_live` adds the per-turn assertion check and changes nothing else, so the
    original two-mode comparison still stands on its own and the third reads as an increment.
    """
    assert set(MODES) == {"agent_datahub", "agent_raw", "agent_datahub_live"}
    assert MODES["agent_raw"] == ("none", "none")
    assert MODES["agent_datahub"] == ("datahub", "none")
    assert MODES["agent_datahub_live"] == ("datahub", "assertions")

    # Exactly one field changes at each step.
    raw, hub, live = MODES["agent_raw"], MODES["agent_datahub"], MODES["agent_datahub_live"]
    assert sum(a != b for a, b in zip(raw, hub, strict=True)) == 1
    assert sum(a != b for a, b in zip(hub, live, strict=True)) == 1

    assert isinstance(build_catalog("none"), NoCatalog)
    assert isinstance(build_catalog("datahub"), DataHubCatalog)


def test_only_the_live_mode_gets_a_per_turn_injection():
    """The two original modes must keep byte-identical turn prompts, so adding a third mode
    cannot retroactively change the result the first two already produced."""
    from blindcity.agent import monitor as monitor_mod
    from blindcity.agent.monitor import AssertionMonitor, NoMonitor, build_monitor
    from blindcity.catalog.operational import Guidance, guidance_properties, parse_guidance

    assert isinstance(build_monitor("none"), NoMonitor)
    assert build_monitor("none").block(None, 1, 0) == ""

    # The assertions monitor now reads DataHub, so it is built with what the catalog published
    # rather than constructed bare.
    flat = {k: v for table in guidance_properties().values() for k, v in table.items()}
    assert isinstance(AssertionMonitor(parse_guidance(flat)), AssertionMonitor)
    assert isinstance(monitor_mod.Guidance, type) and Guidance is monitor_mod.Guidance


def test_the_live_mode_refuses_to_run_without_guidance_in_datahub(monkeypatch):
    """A missing catalog must be loud. Returning an empty block would turn `agent_datahub_live`
    into `agent_datahub` while still labelling itself the assertions mode -- the headline number
    would quietly become a measurement of something else."""
    import httpx

    from blindcity.agent import guidance as guidance_mod

    monkeypatch.setattr(
        guidance_mod, "_custom_properties", lambda client, gms, urn: {}
    )
    with pytest.raises(guidance_mod.GuidanceUnavailable, match="no City Sim operating guidance"):
        guidance_mod.fetch_guidance("http://gms.invalid")

    def explode(client, gms, urn):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(guidance_mod, "_custom_properties", explode)
    with pytest.raises(guidance_mod.GuidanceUnavailable, match="could not read"):
        guidance_mod.fetch_guidance("http://gms.invalid")


def test_the_agent_path_never_imports_the_guidance_constants():
    """The claim is that DataHub steers the agent, and it is only true if the bytes the agent acts
    on came from DataHub. While `monitor.py` imported these directly, the mode would have scored
    identically with DataHub switched off -- the catalog was decorative and the Python tuple was
    doing the work. Asserted structurally, because the import is easy to add back by reflex."""
    import inspect

    from blindcity.agent import monitor as monitor_mod

    source = inspect.getsource(monitor_mod)
    for name in ("LEVER_GUIDANCE", "OUTCOME_ASSERTIONS", "RESPONSE_LAGS"):
        assert name not in source, f"{name} is back on the agent's path; it must come from DataHub"


def test_published_guidance_survives_the_round_trip_through_datahub():
    """`guidance_properties` and `parse_guidance` are the only wire format between the source of
    the guidance and the agent that acts on it. If they are not exact inverses, a band is silently
    rewritten somewhere between the expert who wrote it and the run it steers."""
    from blindcity.catalog.operational import (
        LEVER_GUIDANCE,
        OUTCOME_ASSERTIONS,
        RESPONSE_LAGS,
        guidance_properties,
        parse_guidance,
    )

    by_table = guidance_properties()
    flat = {k: v for table in by_table.values() for k, v in table.items()}
    assert len(flat) == len(LEVER_GUIDANCE) + len(OUTCOME_ASSERTIONS) + len(RESPONSE_LAGS)
    # Every lever band travels on the dataset whose columns they are.
    assert set(by_table["lever_monthly"]) == {
        f"blindcity.guidance.lever.{g.lever}" for g in LEVER_GUIDANCE
    }

    back = parse_guidance(flat)
    assert back.levers == LEVER_GUIDANCE
    assert back.outcomes == OUTCOME_ASSERTIONS
    assert back.lags == RESPONSE_LAGS


def test_a_corrupt_published_property_costs_one_entry_not_the_block():
    """This reads a live catalog that anyone may have edited by hand in the DataHub UI. One
    unparseable property should cost that entry, not silently blank the whole block -- which
    would look exactly like a mode that had no assertions to make."""
    from blindcity.catalog.operational import guidance_properties, parse_guidance

    flat = {k: v for table in guidance_properties().values() for k, v in table.items()}
    flat["blindcity.guidance.lever.income_tax_rate"] = "{not json"
    flat["blindcity.guidance.outcome.road_wear"] = '{"low": "abc"}'
    flat["blindcity.unrelated.key"] = "ignored"

    back = parse_guidance(flat)
    assert len(back.levers) == 7, "a corrupt lever took others with it"
    assert len(back.outcomes) == 4
    assert all(g.lever != "income_tax_rate" for g in back.levers)


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


# --- The backend ----------------------------------------------------------------------------
#
# The controller holds the conversation in a provider-neutral form and the client serialises it.
# These assert that serialisation, so the client cannot quietly hand one mode a differently
# shaped conversation than another.


def _history():
    call = ToolCall(name="sql_query", args={"query": "SELECT 1"}, id="c1")
    return [
        Turn(role="user", text="Turn 1."),
        Turn(role="model", text="Looking.", calls=[call]),
        Turn(role="user", results=[ToolResult(call=call, payload={"rows": [[1]]})]),
    ]




def test_the_backend_serialises_a_tool_round_trip():
    items = ResponsesClient._input(_history())
    assert items[0] == {"role": "user", "content": [{"type": "input_text", "text": "Turn 1."}]}
    # The assistant's own words and its calls are separate items, not one message.
    assert items[1]["role"] == "assistant"
    assert items[2]["type"] == "function_call"
    assert items[2]["name"] == "sql_query"
    # Arguments go over the wire as a JSON *string*, not an object.
    assert json.loads(items[2]["arguments"]) == {"query": "SELECT 1"}
    # Results are keyed back to the call id, or the server cannot match them up. Getting this
    # wrong is not a crash: the model simply never learns what its own query returned.
    assert items[3]["type"] == "function_call_output"
    assert items[3]["call_id"] == "c1"
    assert json.loads(items[3]["output"]) == {"rows": [[1]]}


def test_the_system_prompt_is_not_smuggled_into_the_conversation():
    """Responses carries the system prompt in `instructions`, beside the input rather than
    inside it. A stray system turn in `_input` would be a second, differently-placed copy."""
    assert all(item.get("role") != "system" for item in ResponsesClient._input(_history()))


def test_the_tool_set_survives_the_wire_format():
    """One declaration, one wire format. The declarations are built once in `tools.py` so no
    mode can be handed a differently-worded tool than another; this checks the client does not
    quietly reshape them on the way out."""
    declared = tool_declarations()
    converted = ResponsesClient._tools(declared)

    # Responses takes flat function tools, without the {type, function: {...}} nesting that
    # /chat/completions required.
    assert [t["name"] for t in converted] == [d["name"] for d in declared]
    assert converted[0]["parameters"] == declared[0]["parameters"]
    assert converted[0]["description"] == declared[0]["description"]


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


def test_thinking_budget_is_not_an_infrastructure_timeout():
    """Timeouts must be scoped to the resource they protect. A SQL query or a lock should never
    be slow, so those are tight. The model's reasoning legitimately takes minutes, and cutting
    it short would not measure the model — it would measure our patience, and would silently
    handicap the thing being benchmarked."""
    from blindcity.agent import runscope
    from blindcity.agent.llm import LLM_TIMEOUT_SECONDS

    assert LLM_TIMEOUT_SECONDS >= 600, "thinking budget is too tight for a reasoning model"
    assert runscope.STATEMENT_TIMEOUT_SECONDS <= 120, "a SQL runaway guard should be tight"
    # The gap is the point: the model may think for many times longer than any one query runs.
    assert LLM_TIMEOUT_SECONDS > runscope.STATEMENT_TIMEOUT_SECONDS * 5


def test_the_llm_client_uses_the_shared_thinking_budget():
    """A per-client default is how a backend ends up quietly stricter than the setting says. One
    client once sat at 90s, which would have truncated a reasoning model mid-thought."""
    import inspect

    from blindcity.agent.llm import LLM_TIMEOUT_SECONDS, ResponsesClient

    default = inspect.signature(ResponsesClient.__init__).parameters["timeout"].default
    assert default == LLM_TIMEOUT_SECONDS, f"ResponsesClient has its own timeout: {default}"


def test_there_is_exactly_one_llm_backend():
    """OpenAI is the only supported provider, and the local `/chat/completions` client and the
    Gemini client are gone. They were routes no published number ever came from, and an untested
    branch in the module that decides what the model sees is where two arms silently diverge.

    Asserted structurally rather than by reading the factory: a second client that exists but is
    unreachable today is a second client someone wires up tomorrow.
    """
    from blindcity.agent import llm as llm_module

    clients = {
        name
        for name, obj in vars(llm_module).items()
        if isinstance(obj, type)
        and issubclass(obj, llm_module._HttpClient)
        and obj is not llm_module._HttpClient
    }
    assert clients == {"ResponsesClient"}, f"unexpected LLM client(s): {sorted(clients)}"
    assert isinstance(llm_module.build_llm.__doc__, str)


def test_a_timed_out_query_does_not_poison_the_rest_of_the_turn():
    """psycopg raises QueryCanceled as a subclass of OperationalError, so a statement timeout
    reads as a dead connection unless caught first — and it leaves the transaction aborted. In a
    live run one slow query made every later query in that turn fail with 'current transaction is
    aborted', turning a single timeout into a lost turn."""
    import psycopg

    conn = FakeConn()
    calls = {"n": 0}

    def sometimes_slow(sql, params=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")

    conn.cursor_obj.execute = sometimes_slow
    conn.cursor_obj.description = [_Col("n")]
    conn.cursor_obj.rows = [{"n": 1}]

    ctx = ToolContext(conn=conn, run_id=1, levers=defaults())
    first = dispatch(ctx, "sql_query", {"query": "SELECT slow FROM t"})
    assert first.get("timed_out") is True
    assert "cancelled" in first["error"]
    assert conn.rollbacks >= 1, "aborted transaction was not rolled back"

    # The turn continues: the next query still works.
    second = dispatch(ctx, "sql_query", {"query": "SELECT n FROM t"})
    assert second.get("rows") == [[1]], second


# --- Memory across turns --------------------------------------------------------------------


def _sql_then_commit(query="SELECT 1", lever=1.0):
    """The shape of a normal turn: one query, then a decision."""
    return [
        Reply(calls=[_call("sql_query", {"query": query})], usage=Usage(calls=1)),
        Reply(
            text=f"Setting fare to {lever}.",
            calls=[_call("set_levers", {"levers": {"transit_fare": lever}})],
            usage=Usage(calls=1),
        ),
    ]


def test_the_agent_remembers_earlier_turns(controllers):
    """Governing is a multi-quarter problem: a decision shows its effect two turns later.

    Without this the agent re-derived the city every turn from a blank conversation. Over one
    live 12-turn run that meant 29 repeated `information_schema` queries and the same fan-out
    join issued on four separate turns, each killed by the 45s statement timeout, because nothing
    carried the lesson forward. Neither mode ever revisited a tax rate it had set.
    """
    build, _ = controllers
    llm = FakeLLM(_sql_then_commit("SELECT first", 1.0) + _sql_then_commit("SELECT second", 2.0))
    controller = build(NoCatalog(), llm)
    controller.decide(_state(), 0, {})
    controller.decide(_state(), 1, {})

    opening_of_turn_two = llm.contents[2]
    flat = json.dumps(opening_of_turn_two)
    assert "SELECT first" in flat, "the query it ran last turn is gone"
    assert "Setting fare to 1.0" in flat, "its own reasoning from last turn is gone"
    assert len(opening_of_turn_two) > len(llm.contents[0]), "turn 2 opened no richer than turn 1"


def test_old_results_are_compacted_but_reasoning_and_errors_survive(controllers):
    """Rows read eight turns ago describe a city that no longer exists; conclusions do not go
    stale. Errors are kept verbatim precisely because forgetting one is how the same fatal query
    got written four times."""
    from blindcity.agent.controller import RESULTS_KEPT_IN_FULL

    build, _ = controllers
    llm = FakeLLM()
    controller = build(NoCatalog(), llm)

    # A turn old enough to be compacted, holding one good result and one failure.
    old = [
        user_turn("Turn 1."),
        Turn(role="model", text="Checking the roads.", calls=[_call("sql_query", {"query": "Q"})]),
        Turn(
            role="user",
            results=[
                ToolResult(
                    call=_call("sql_query", {"query": "Q"}),
                    payload={"columns": ["wear"], "rows": [[0.97]], "row_count": 1},
                ),
                ToolResult(
                    call=_call("sql_query", {"query": "BAD"}),
                    payload={"error": "query exceeded the 45s limit", "timed_out": True},
                ),
            ],
        ),
    ]
    controller._segments = [old] + [[user_turn(f"Turn {i}.")] for i in range(RESULTS_KEPT_IN_FULL)]
    flat = json.dumps([_turn_as_dict(t) for t in controller._conversation()])

    assert "Checking the roads." in flat, "reasoning was dropped"
    assert '"wear"' in flat, "column names were dropped; the model loses what it already looked at"
    assert "0.97" not in flat, "stale rows were kept"
    assert "exceeded the 45s limit" in flat, "the error was forgotten, so it will be repeated"


def test_recent_results_are_kept_in_full(controllers):
    """Compaction must not eat the turn the model is actually reasoning from."""
    build, _ = controllers
    llm = FakeLLM(_sql_then_commit("SELECT recent", 1.0) + _sql_then_commit("SELECT now", 2.0))
    controller = build(NoCatalog(), llm)
    llm.replies[0] = Reply(
        calls=[_call("sql_query", {"query": "SELECT recent"})], usage=Usage(calls=1)
    )
    controller.decide(_state(), 0, {})
    controller.decide(_state(), 1, {})
    # The immediately preceding turn is inside the full-detail window.
    assert "SELECT recent" in json.dumps(llm.contents[2])


def test_both_modes_remember_identically(controllers):
    """Memory is a capability. If one mode kept more of it than the other, the headline result
    would measure the memory instead of the metadata."""
    build, stub_catalog = controllers
    shape = _sql_then_commit("SELECT x", 1.0) + _sql_then_commit("SELECT y", 2.0)

    seen = []
    for catalog in (stub_catalog, NoCatalog()):
        llm = FakeLLM(list(shape))
        controller = build(catalog, llm)
        controller.decide(_state(), 0, {})
        controller.decide(_state(), 1, {})
        seen.append(llm.contents)

    assert seen[0] == seen[1], "the two modes were handed differently-shaped conversations"


def test_timed_out_queries_are_reported_not_silently_absorbed(controllers):
    """A timeout does not fail the turn -- the model reads the error and adapts -- which is
    exactly why it has to be recorded. A live run lost four queries and three minutes this way
    and printed '0 errors', which read as a clean comparison and was not one."""
    build, _ = controllers
    llm = FakeLLM(
        [
            Reply(calls=[_call("sql_query", {"query": "SELECT huge"})], usage=Usage(calls=1)),
            Reply(calls=[_call("set_levers", {"levers": {"transit_fare": 1.0}})], usage=Usage()),
        ]
    )
    controller = build(NoCatalog(), llm)

    # The real dispatch has to run: it is what writes the audit record, so a stubbed one would
    # test the stub. Fail at the database instead, which is where a timeout actually comes from.
    import psycopg

    def cancelled(sql, params=None):
        raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")

    controller.conn.cursor_obj.execute = cancelled

    controller.decide(_state(), 0, {})

    report = controller.report()
    assert report["timeouts"] == 1, report["timeouts"]
    assert "SELECT huge" in report["turns"][0]["timed_out_queries"][0]
    # The turn itself did not fail: an LLM error is a different thing entirely.
    assert report["turns"][0]["error"] is None


def test_the_model_is_told_what_its_decision_actually_became(controllers):
    """A value silently clamped to a bound is a decision the model did not make.

    Until now it was never told: the turn ended on the set_levers call, so the only signal was a
    different number in the next turn's lever list, a quarter later and with no reason given.
    """
    build, _ = controllers
    llm = FakeLLM(
        [
            Reply(
                calls=[
                    _call("set_levers", {"levers": {"income_tax_rate": 0.9, "nonsense": 1}})
                ],
                usage=Usage(calls=1),
            )
        ]
    )
    controller = build(NoCatalog(), llm)
    controller.decide(_state(), 0, {})
    prompt = controller._turn_prompt(_state(), 1)

    assert "0.9 clamped to 0.4" in prompt, "the model was not told its value was clamped"
    assert "nonsense" in prompt and "rejected" in prompt, "a rejected lever went unmentioned"
    assert "income_tax_rate=0.4" in prompt, "the value that actually took effect was not confirmed"

    report = controller.report()
    assert report["turns"][0]["clamped"], "clamps left no trace in the audit trail"
    assert report["turns"][0]["rejected"]


def test_a_clean_decision_adds_no_confirmation_noise(controllers):
    """In-range levers need no explanation; only surprises are worth the tokens."""
    build, _ = controllers
    llm = FakeLLM(
        [Reply(calls=[_call("set_levers", {"levers": {"transit_fare": 1.5}})], usage=Usage())]
    )
    controller = build(NoCatalog(), llm)
    controller.decide(_state(), 0, {})
    prompt = controller._turn_prompt(_state(), 1)
    assert "clamped" not in prompt and "rejected" not in prompt
    assert "transit_fare=1.5" in prompt


def test_the_transcript_records_what_the_model_was_actually_sent(tmp_path):
    """Every context bug here was invisible in the results and obvious in the transcript.

    The catalog promised a glossary and shipped none for a whole slice: twenty terms were emitted
    to DataHub and never linked to a dataset, and every run report looked perfect. A score says a
    mode did badly. Only this says what the mode could see.
    """
    from blindcity.agent.transcript import RecordingLLM

    path = tmp_path / "t.jsonl"
    inner = FakeLLM([Reply(text="hi", calls=[_call("sql_query", {"query": "SELECT 1"})])])
    rec = RecordingLLM(inner, path, mode="agent_raw")
    rec.generate(system="SYS-PROMPT", history=[user_turn("turn one")], tools=tool_declarations())

    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    request = next(x for x in lines if x["phase"] == "request")
    reply = next(x for x in lines if x["phase"] == "reply")

    assert request["system"] == "SYS-PROMPT", "the system prompt was not captured verbatim"
    assert request["history"][0]["text"] == "turn one"
    assert "sql_query" in request["tools"] and "set_levers" in request["tools"]
    assert reply["calls"][0]["name"] == "sql_query"
    assert rec.model == inner.model, "the wrapper must be transparent to the controller"


def test_the_transcript_survives_a_provider_failure(tmp_path):
    """A run that dies mid-call is exactly when the evidence matters most, so the request is
    written before the call and the failure is recorded rather than swallowed."""
    from blindcity.agent.llm import LLMError
    from blindcity.agent.transcript import RecordingLLM

    class Exploding:
        model = "boom"

        def generate(self, *, system, history, tools=None):
            raise LLMError("provider refused")

    path = tmp_path / "t.jsonl"
    rec = RecordingLLM(Exploding(), path, mode="agent_raw")
    with pytest.raises(LLMError):
        rec.generate(system="S", history=[user_turn("q")])

    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert [x["phase"] for x in lines] == ["request", "error"]
    assert "provider refused" in lines[1]["error"]


def test_a_rerun_does_not_append_to_the_previous_transcript(tmp_path):
    """Two runs concatenated into one file would read as a single very long run."""
    from blindcity.agent.transcript import RecordingLLM

    path = tmp_path / "t.jsonl"
    RecordingLLM(FakeLLM(), path, mode="a").generate(system="S", history=[user_turn("first")])
    RecordingLLM(FakeLLM(), path, mode="a").generate(system="S", history=[user_turn("second")])

    text = path.read_text(encoding="utf-8")
    assert "first" not in text and "second" in text


def test_reasoning_effort_is_set_explicitly_and_shared():
    """The reasoning budget is a property of the thing being benchmarked, so it must be stated
    rather than inherited from a provider default -- and it must be the same for every mode.

    It ran on the unstated default through every result up to 2026-08-09: about 256 output tokens
    a call including reasoning, which is a model barely thinking. `low` is then a deliberate
    choice, not thrift: a large budget lets the control mode brute-force its way to the same
    conclusions by querying more, compressing the difference the catalog is supposed to make.
    """
    from blindcity.agent.llm import LLM_REASONING_EFFORT, ResponsesClient

    assert LLM_REASONING_EFFORT in {"minimal", "low", "medium", "high"}, LLM_REASONING_EFFORT

    sent: dict[str, Any] = {}

    class Client(ResponsesClient):
        def post(self, url, body, headers):
            sent.update(body)
            return {"output": [], "usage": {}}

    client = Client(model="m", api_key="k")
    client.generate(system="s", history=[user_turn("q")], tools=tool_declarations())
    assert sent["reasoning"] == {"effort": LLM_REASONING_EFFORT}, sent.get("reasoning")


def test_the_transcript_wrapper_does_not_hide_the_reasoning_budget(tmp_path):
    """Recording a run must not cost the run's own record of how it was configured.

    `model` was proxied explicitly and nothing else was, so `reasoning_effort` and
    `reasoning_sent` both read `None` in the report of every run that wrote a transcript --
    which, once transcripts became the default, was every run. The budget was applied correctly
    and the audit trail said "unknown", which is the exact failure this module exists to prevent.
    """
    from blindcity.agent.transcript import RecordingLLM

    class Client(FakeLLM):
        reasoning_effort = "low"
        reasoning_sent = True
        rate_limited = 3

    rec = RecordingLLM(Client(), tmp_path / "t.jsonl", mode="agent_raw")

    assert rec.reasoning_effort == "low"
    assert rec.reasoning_sent is True
    # Delegation is by name rather than a list, so a field added to the client later is visible
    # here without anyone remembering to proxy it.
    assert rec.rate_limited == 3
    # ...and the wrapper's own attributes still win over the client's.
    assert rec.mode == "agent_raw"
