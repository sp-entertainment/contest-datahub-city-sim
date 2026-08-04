"""Give the agent a warehouse that contains exactly one run.

The warehouse appends: every table carries `run_id` and holds every run ever loaded. If the
agent's SQL reached the raw tables it would silently pool the crisis it is meant to diagnose with
unrelated runs, and act on a city that does not exist. Telling the model in the prompt to filter
by `run_id` is not enough — one forgotten predicate corrupts the run, and a corrupted run still
produces a plausible-looking number.

So each run gets a schema of views, one per table, each filtered to that run, and the agent's
connection has `search_path` pointing at it. The model writes `SELECT ... FROM road_monthly` and
the filtering is structural rather than remembered.

The views are cheap, disposable, and named after the run so parallel arms cannot collide.
"""

from __future__ import annotations

import psycopg
from psycopg import sql

from blindcity.catalog.schema_spec import TABLES


def schema_name(run_id: int) -> str:
    return f"run_{int(run_id)}"


def create_run_views(conn: psycopg.Connection, run_id: int) -> str:
    """Create (or replace) the per-run view schema. Returns the schema name."""
    name = schema_name(run_id)
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(name)))
        for table in TABLES:
            # sim_run is a dimension of one row per run; scope it the same way for consistency.
            cur.execute(
                sql.SQL("CREATE OR REPLACE VIEW {}.{} AS SELECT * FROM public.{} WHERE run_id = {}")
                .format(
                    sql.Identifier(name),
                    sql.Identifier(table.name),
                    sql.Identifier(table.name),
                    sql.Literal(int(run_id)),
                )
            )
    conn.commit()
    return name


def drop_run_views(conn: psycopg.Connection, run_id: int) -> None:
    """Remove a run's view schema. Safe to call when it was never created."""
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name(run_id)))
        )
    conn.commit()


def scope_connection(conn: psycopg.Connection, run_id: int) -> None:
    """Point this connection at one run's views.

    `public` is deliberately left out of the search path. A model that explicitly writes
    `public.road_monthly` can still reach the pooled tables — blocking that properly needs a
    read-only role, which is more machinery than this is worth. Both arms have identical
    exposure, so it cannot bias the comparison, and the prompt tells the model the tables are
    already scoped.
    """
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SET search_path TO {}, information_schema").format(
                sql.Identifier(schema_name(run_id))
            )
        )
    conn.commit()
