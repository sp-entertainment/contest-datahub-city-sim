"""Read the expert operating guidance back out of DataHub.

`catalog/operational.py` authors the guidance and `catalog/emit.py` publishes it. This is the only
route by which it reaches a running agent: `agent_datahub_live` fetches it from GMS at run start
and imports none of the constants.

That indirection is the point. The headline claim is that DataHub's assertions steer the agent, and
the only way to mean it is for the bytes the agent acts on to have come out of DataHub. Injecting a
Python tuple that happens to sit beside a catalog we also populated would demonstrate that *we* can
steer the agent, which nobody doubted. It also makes the demo real in the other direction: edit a
band in the DataHub UI and the next run plays differently, with no code change.

**A missing catalog is loud.** If GMS is unreachable, or holds no guidance, this raises rather than
returning an empty block. A silent empty block would turn `agent_datahub_live` into `agent_datahub`
while still reporting itself as the assertions mode -- the headline number would quietly become a
measurement of something else, which is precisely the failure this project keeps finding in other
guises.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from blindcity import config
from blindcity.catalog.operational import Guidance, parse_guidance
from blindcity.catalog.schema_spec import TABLES

# Tight on purpose. This is an HTTP read against a service on the same host, not a thinking budget:
# see the note in `llm.py` about never conflating the two.
FETCH_TIMEOUT_SECONDS = 30.0

PLATFORM = "postgres"
DATABASE = "blindcity.public"


class GuidanceUnavailable(RuntimeError):
    """DataHub holds no operating guidance, so the assertions mode has nothing to assert."""


def dataset_urn(table: str, *, platform: str = PLATFORM, database: str = DATABASE) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{platform},{database}.{table},PROD)"


def _custom_properties(client: httpx.Client, gms_url: str, urn: str) -> dict[str, str]:
    """One dataset's custom properties, read from the raw aspect.

    The raw aspect rather than GraphQL: `datasetProperties.customProperties` comes back through
    GraphQL as a list of `{key, value}` pairs on some versions and a map on others, and a reader
    that guesses wrong returns silently empty -- which here would read as "the catalog documents
    nothing" rather than as a bug.
    """
    r = client.get(
        f"{gms_url}/aspects/{urllib.parse.quote(urn, safe='')}"
        "?aspect=datasetProperties&version=0"
    )
    if r.status_code != 200:
        return {}
    aspect: dict[str, Any] = (r.json().get("aspect") or {}).get(
        "com.linkedin.dataset.DatasetProperties", {}
    )
    props = aspect.get("customProperties") or {}
    if isinstance(props, list):  # {key, value} pair form
        return {
            str(p.get("key")): str(p.get("value"))
            for p in props
            if isinstance(p, dict) and p.get("key")
        }
    return {str(k): str(v) for k, v in props.items()}


def fetch_guidance(
    gms_url: str | None = None, *, timeout: float = FETCH_TIMEOUT_SECONDS
) -> Guidance:
    """Every guidance property published across the catalog, reassembled.

    Gathered across all tables rather than a hard-coded few: which dataset carries which piece is
    `operational.guidance_properties`' decision, and a reader that duplicated that mapping would be
    a third copy of it to keep in step.
    """
    base = (gms_url or config.DATAHUB_GMS_URL).rstrip("/")
    merged: dict[str, str] = {}
    try:
        with httpx.Client(timeout=timeout) as client:
            for table in TABLES:
                merged.update(_custom_properties(client, base, dataset_urn(table.name)))
    except httpx.HTTPError as exc:
        raise GuidanceUnavailable(
            f"could not read operating guidance from DataHub at {base}: {exc}. "
            "The assertions mode reads its guidance from the catalog, so without it the run "
            "would score as the assertions mode while behaving like the plain catalog one."
        ) from exc

    guidance = parse_guidance(merged)
    if not guidance:
        raise GuidanceUnavailable(
            f"DataHub at {base} holds no Blind City operating guidance. Publish it with "
            "`uv run blindcity emit` before running --mode agent_datahub_live; the mode reads its "
            "assertions from the catalog and has nothing to fall back on by design."
        )
    return guidance
