"""The agent's hands: read-only SQL over the warehouse, and the eight levers.

**Both modes get exactly this tool set.** It is defined once, here, and neither mode may add,
remove, or reword a tool — the declarations below are what the model sees, and a difference in
tool wording is a difference in capability. The only thing that differs between `agent_datahub`
and `agent_raw` is a block of catalog context in the prompt (`catalog.py`).

Schema discovery is deliberately available to both. `agent_raw` can read `information_schema`
and find every table and column, exactly as a competent analyst with database access would. What
it cannot find is what any of them *mean*. That is the comparison: not access to data versus no
access, but described data versus undescribed data. A control that could not discover the schema
at all would be a straw man and the result would be worthless.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg

from blindcity.levers import LEVERS

# Statements the SQL tool will run. Anything else is refused before it reaches the database.
_ALLOWED_PREFIX = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)

# Refused outright even inside an otherwise-innocent query. The connection is also opened
# read-only, so this is a second line rather than the only one — but a clear refusal message
# teaches the model to stop trying, where a database error just invites a retry.
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|copy|vacuum)\b",
    re.IGNORECASE,
)

MAX_ROWS = 50
MAX_CELL_CHARS = 200
# Only for the message shown to the model; the limit itself lives in runscope.
STATEMENT_TIMEOUT_HINT = 45


@dataclass
class ToolCallRecord:
    """One tool invocation, kept so a run can be audited after the fact."""

    turn: int
    name: str
    args: dict[str, Any]
    ok: bool
    summary: str
    # Wall time for this call. Without it a run reports LLM seconds and total seconds with
    # nothing in between, which is how ~90% of a run once went unaccounted for.
    seconds: float = 0.0
    # A statement timeout specifically, as opposed to any other failure. Tracked separately
    # because it is the one error whose cost is invisible in the result: the model sees it,
    # adapts, and moves on, so the run finishes clean while a diagnosis it needed is missing.
    # A live run lost four queries and three minutes this way and reported zero errors.
    timed_out: bool = False


@dataclass
class ToolContext:
    """Everything the tools act on for a single scenario run."""

    conn: psycopg.Connection
    run_id: int
    levers: dict[str, float]
    turn: int = 0
    log: list[ToolCallRecord] = field(default_factory=list)
    # Levers the model asked for this turn, applied by the controller when the turn ends.
    pending: dict[str, float] = field(default_factory=dict)
    # Rebuilds the connection if it dies mid-run. Docker on this host has dropped the warehouse
    # out from under a run more than once, and losing a scored mode to a container restart is a
    # much worse outcome than one retried query.
    reconnect: Callable[[], psycopg.Connection] | None = None


def tool_declarations() -> list[dict[str, Any]]:
    """The function declarations sent to the model. Identical for both modes.

    Plain JSON Schema, which is what OpenAI-compatible servers expect. Defined once here so no
    backend can hand one mode a differently-worded tool than another.
    """
    lever_lines = "\n".join(
        f"  {name}: {lev.minimum} to {lev.maximum} ({lev.unit}) - {lev.description}"
        for name, lev in LEVERS.items()
    )
    return [
        {
            "name": "sql_query",
            "description": (
                "Run a read-only SQL query against the city's PostgreSQL warehouse and return up "
                "to 50 rows. Only SELECT and WITH are permitted. The warehouse holds one row per "
                "entity per simulated month. Every table has a run_id column and your query is "
                "automatically restricted to the current run, so you never need to filter on it. "
                "Use information_schema to discover tables and columns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A single SELECT or WITH statement.",
                    }
                },
                "required": ["query"],
            },
        },
        {
            "name": "set_levers",
            "description": (
                "Set one or more policy levers. Values outside the legal range are clamped rather "
                "than rejected, so a bad decision stays a bad decision instead of an error. "
                "Levers persist until changed. Levers and ranges:\n" + lever_lines
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "levers": {
                        "type": "object",
                        "description": (
                            "Map of lever name to numeric value. Include only the levers you want "
                            "to change."
                        ),
                    }
                },
                "required": ["levers"],
            },
        },
    ]


def run_sql(ctx: ToolContext, query: str) -> dict[str, Any]:
    """Execute a read-only query and return rows as JSON-safe values."""
    if not isinstance(query, str) or not query.strip():
        return {"error": "query must be a non-empty string"}
    if not _ALLOWED_PREFIX.match(query):
        return {"error": "only SELECT and WITH statements are permitted"}
    forbidden = _FORBIDDEN.search(query)
    if forbidden:
        return {"error": f"'{forbidden.group(0)}' is not permitted; this tool is read-only"}
    if ";" in query.rstrip().rstrip(";"):
        return {"error": "one statement per call"}

    # The connection's search_path already points at this run's views (see runscope.py), so the
    # predicate scoping the query to one run is structural — nothing to rewrite for that.
    #
    # The row cap, though, must be enforced in SQL rather than by `fetchmany`. psycopg's default
    # cursor is client-side: `execute` transfers the whole result set before a single row is
    # read. An unqualified `SELECT * FROM citizen_monthly` moved ~290k wide rows across the wire
    # and stalled a one-turn run past nine minutes, to show the model fifty of them.
    #
    # One extra row is fetched so `truncated` reports whether anything was actually cut.
    statement = query.rstrip().rstrip(";")
    capped = f"SELECT * FROM ({statement}) AS _agent_query LIMIT {MAX_ROWS + 1}"
    try:
        with ctx.conn.cursor() as cur:
            cur.execute(capped)
            columns = [d.name for d in (cur.description or [])]
            rows = cur.fetchall()
    except psycopg.errors.QueryCanceled:
        # A statement timeout. psycopg raises this as a subclass of OperationalError, so without
        # catching it first it looks like a dead connection. Critically it also leaves the
        # transaction aborted: in a live run one timed-out query poisoned every later query in
        # the turn with "current transaction is aborted", turning one slow query into a lost turn.
        ctx.conn.rollback()
        return {
            "error": (
                f"query exceeded the {STATEMENT_TIMEOUT_HINT}s limit and was cancelled. "
                "Narrow it with a WHERE on tick, or aggregate less data."
            ),
            "timed_out": True,
        }
    except psycopg.OperationalError as exc:
        # The connection itself failed rather than the query. Rebuild it once and retry, so a
        # warehouse blip costs one query instead of the whole mode.
        if ctx.reconnect is not None:
            try:
                ctx.conn = ctx.reconnect()
                with ctx.conn.cursor() as cur:
                    cur.execute(capped)
                    columns = [d.name for d in (cur.description or [])]
                    rows = cur.fetchall()
                ctx.conn.rollback()
            except psycopg.Error as retry_exc:
                return {"error": f"warehouse unavailable: {str(retry_exc).splitlines()[0][:220]}"}
        else:
            return {"error": f"warehouse unavailable: {str(exc).splitlines()[0][:220]}"}
    except psycopg.Error as exc:
        ctx.conn.rollback()
        message = str(exc).strip().splitlines()[0][:300]
        return {"error": message}
    else:
        # End the read transaction immediately. psycopg opens one on execute, and a SELECT that
        # is never committed leaves the session "idle in transaction" holding locks on every
        # view it touched -- which deadlocked a run against its own cleanup for 27 minutes.
        # Nothing is written here, so a rollback is the cheapest way to let go.
        ctx.conn.rollback()

    # The warehouse connection uses psycopg's dict_row factory, so a row is a mapping, not a
    # tuple. Iterating it directly yields column *names* — which is exactly what the model was
    # handed on the first live run: every query came back as a list of its own headers, so it
    # re-asked the same question six different ways and burned the whole turn budget.
    truncated = len(rows) > MAX_ROWS
    out_rows = [[_cell(row[c]) for c in columns] for row in rows[:MAX_ROWS]]
    payload: dict[str, Any] = {
        "columns": columns,
        "rows": out_rows,
        "row_count": len(out_rows),
        "truncated": truncated,
    }
    if truncated:
        # Said plainly, because a silently clipped result invites the model to draw a conclusion
        # from the first fifty rows of an unordered scan.
        payload["note"] = (
            f"Result was cut off at {MAX_ROWS} rows. Aggregate, filter, or ORDER BY to get an "
            "answer rather than a sample."
        )
    return payload


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return round(value, 6)
    text = str(value)
    return text if len(text) <= MAX_CELL_CHARS else text[:MAX_CELL_CHARS] + "..."


def set_levers(ctx: ToolContext, levers: Any) -> dict[str, Any]:
    """Stage lever changes for this turn, clamped to their legal ranges."""
    if not isinstance(levers, dict) or not levers:
        return {"error": "levers must be a non-empty object of name -> number"}

    applied: dict[str, float] = {}
    rejected: dict[str, str] = {}
    clamped: dict[str, str] = {}
    for name, raw in levers.items():
        lever = LEVERS.get(name)
        if lever is None:
            rejected[str(name)] = "unknown lever"
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            rejected[name] = f"not a number: {raw!r}"
            continue
        bounded = lever.clamp(value)
        if bounded != value:
            clamped[name] = f"{value} clamped to {bounded}"
        applied[name] = bounded

    ctx.pending.update(applied)
    result: dict[str, Any] = {"applied": applied}
    if clamped:
        result["clamped"] = clamped
    if rejected:
        result["rejected"] = rejected
        result["valid_levers"] = sorted(LEVERS)
    return result


DISPATCH = {"sql_query": run_sql, "set_levers": set_levers}


def dispatch(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Route one model-issued call, recording it and its cost for the audit trail."""
    started = time.monotonic()
    handler = DISPATCH.get(name)
    if handler is None:
        payload = {"error": f"unknown tool {name!r}; available: {sorted(DISPATCH)}"}
        ctx.log.append(
            ToolCallRecord(ctx.turn, name, args, False, payload["error"], time.monotonic() - started)
        )
        return payload

    if name == "sql_query":
        payload = handler(ctx, args.get("query", ""))
        summary = (
            payload.get("error")
            or f"{payload.get('row_count', 0)} rows, columns={payload.get('columns')}"
        )
    else:
        payload = handler(ctx, args.get("levers"))
        summary = payload.get("error") or f"applied={payload.get('applied')}"

    ctx.log.append(
        ToolCallRecord(
            ctx.turn, name, args, "error" not in payload, str(summary)[:300],
            time.monotonic() - started,
            bool(payload.get("timed_out", False)),
        )
    )
    return payload
