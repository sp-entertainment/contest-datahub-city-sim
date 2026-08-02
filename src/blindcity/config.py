"""Connection settings, read from the environment with defaults that match the shipped compose file.

Defaults are local-only and unauthenticated by design — see docs/DECISIONS.md, "Run locally,
unauthenticated". Nothing here is a secret, and nothing here should become one.
"""

from __future__ import annotations

import os

# The warehouse the simulation writes to and the agent queries.
# NOT to be confused with DataHub's own MySQL store on 3306. See docs/ENVIRONMENT.md.
WAREHOUSE_URL = os.environ.get(
    "BLINDCITY_WAREHOUSE_URL",
    "postgresql+psycopg://blindcity:blindcity@localhost:5432/blindcity",
)

# DataHub GMS. Accepts unauthenticated writes on the OSS quickstart, so no token is configured.
DATAHUB_GMS_URL = os.environ.get("BLINDCITY_DATAHUB_GMS_URL", "http://localhost:8080")

# The sim's FastAPI control surface: GET /state, POST /lever, POST /advance.
CONTROL_SURFACE_URL = os.environ.get("BLINDCITY_CONTROL_URL", "http://localhost:8000")
