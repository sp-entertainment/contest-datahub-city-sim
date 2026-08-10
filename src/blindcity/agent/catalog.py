"""The catalog context block — the single difference between the two modes.

`agent_datahub` gets the text this module produces prepended to its prompt. `agent_raw` gets
nothing in its place, not even a placeholder. Everything else about the two modes is byte-identical:
same model, same temperature, same system prompt, same tools, same tool budget, same turn budget,
same seed, same scenario, same SQL access.

**On MCP.** `TASKS.md` specifies the DataHub MCP server. This reads the same metadata from the
same GMS instance over GraphQL instead, because the MCP path needs a second process running
alongside a Docker stack that has restarted repeatedly on this host, and a transport failure
mid-run would corrupt the measurement rather than merely inconvenience it. The metadata is
identical — descriptions, glossary terms, and lineage that `datahub-emit` wrote. `CatalogSource`
is an interface precisely so an MCP-backed implementation can replace this one without touching
the controller or the parity guarantees. Recorded in docs/DECISIONS.md.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from blindcity import config


class CatalogSource(Protocol):
    """Supplies the prompt block that distinguishes `agent_datahub` from `agent_raw`."""

    def context_block(self) -> str:
        """Return the catalog description, or an empty string if there is none."""
        ...


class NoCatalog:
    """The control mode's catalog: nothing at all.

    Not an empty catalog, not a stub explaining that metadata is unavailable — the absence of a
    section. A note saying "you have no catalog" would itself be information the other mode lacks.
    """

    name = "none"

    def context_block(self) -> str:
        return ""


_DATASET_QUERY = """
query($urn: String!) {
  dataset(urn: $urn) {
    properties { name description }
    glossaryTerms { terms { term { urn properties { name description } } } }
    schemaMetadata(version: 0) {
      fields { fieldPath description glossaryTerms { terms { term { urn } } } }
    }
    upstream: lineage(input: {direction: UPSTREAM, start: 0, count: 50}) {
      relationships { entity { urn } }
    }
  }
}
"""


class DataHubCatalog:
    """Reads descriptions, glossary terms, and lineage from GMS over GraphQL."""

    name = "datahub"

    def __init__(
        self,
        gms_url: str | None = None,
        *,
        platform: str = "postgres",
        database: str = "blindcity.public",
        timeout: float = 30.0,
    ) -> None:
        self.gms_url = (gms_url or config.DATAHUB_GMS_URL).rstrip("/")
        self.platform = platform
        self.database = database
        self.timeout = timeout
        self._cached: str | None = None

    def dataset_urn(self, table: str) -> str:
        return f"urn:li:dataset:(urn:li:dataPlatform:{self.platform},{self.database}.{table},PROD)"

    def _query(self, client: httpx.Client, urn: str) -> dict[str, Any] | None:
        r = client.post(
            f"{self.gms_url}/api/graphql",
            json={"query": _DATASET_QUERY, "variables": {"urn": urn}},
        )
        if r.status_code != 200:
            return None
        payload = r.json()
        return (payload.get("data") or {}).get("dataset")

    def context_block(self, tables: list[str] | None = None) -> str:
        """Build the catalog block. Cached, since it does not change during a run."""
        if self._cached is not None:
            return self._cached

        from blindcity.catalog.schema_spec import TABLES

        names = tables if tables is not None else [t.name for t in TABLES]
        sections: list[str] = []
        glossary: dict[str, str] = {}

        with httpx.Client(timeout=self.timeout) as client:
            for table in names:
                ds = self._query(client, self.dataset_urn(table))
                if not ds:
                    continue
                props = ds.get("properties") or {}
                description = (props.get("description") or "").strip()
                lines = [f"### {table}"]
                if description:
                    lines.append(description)

                for entry in ((ds.get("glossaryTerms") or {}).get("terms") or []):
                    term = (entry or {}).get("term") or {}
                    tprops = term.get("properties") or {}
                    if tprops.get("name"):
                        glossary[tprops["name"]] = (tprops.get("description") or "").strip()

                fields = ((ds.get("schemaMetadata") or {}).get("fields")) or []
                described = [
                    f"  - {f['fieldPath']}: {f['description'].strip()}"
                    for f in fields
                    if f.get("fieldPath") and (f.get("description") or "").strip()
                ]
                if described:
                    lines.append("Columns:")
                    lines.extend(described)

                upstreams = [
                    rel["entity"]["urn"].split(",")[1].split(".")[-1]
                    for rel in (((ds.get("upstream") or {}).get("relationships")) or [])
                    if rel.get("entity", {}).get("urn")
                ]
                if upstreams:
                    lines.append(f"Derived from: {', '.join(sorted(set(upstreams)))}")

                if len(lines) > 1:
                    sections.append("\n".join(lines))

        if not sections:
            self._cached = ""
            return ""

        parts = [
            "## Data catalog",
            "",
            (
                "This warehouse is catalogued in DataHub, a metadata platform that records what "
                "each table and column means, defines the business terms behind them, and tracks "
                "which tables are derived from which. That documentation is reproduced in full "
                "below -- it is everything the catalog holds about this warehouse, so there is "
                "nothing further to look up.\n\n"
                "Use it to skip discovery. You do not need to inspect information_schema or "
                "sample tables to work out what a column holds; it is described here. Lineage is "
                "generated from the simulation's own causal graph and every edge is verified "
                "against the running model, so 'derived from' states a real causal dependency "
                "rather than a guess -- it tells you which inputs actually move a given output."
            ),
            "",
        ]
        parts.extend(sections)
        if glossary:
            parts.append("")
            parts.append("### Glossary")
            parts.extend(
                f"  - {term}: {definition}" for term, definition in sorted(glossary.items())
            )

        self._cached = "\n".join(parts)
        return self._cached


def build_catalog(context: str, gms_url: str | None = None) -> CatalogSource:
    """`datahub` -> the real catalog, `none` -> the control."""
    if context == "datahub":
        return DataHubCatalog(gms_url)
    if context == "none":
        return NoCatalog()
    raise ValueError(f"unknown context {context!r}; expected 'datahub' or 'none'")
