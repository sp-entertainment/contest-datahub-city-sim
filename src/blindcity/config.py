"""Connection settings, read from the environment with defaults that match the shipped compose file.

Defaults are local-only and unauthenticated by design — see docs/DECISIONS.md, "Run locally,
unauthenticated". Nothing here is a secret, and nothing here should become one.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path | None = None) -> None:
    """Load `.env` into the process environment, without overriding what is already set.

    Hand-rolled rather than a dependency: this needs to parse `KEY=value` and nothing else.
    Real environment variables win, so CI and the shell can always override the file.

    The file is gitignored and holds the one real secret in this project. Nothing here logs a
    value, and nothing should: see the credentials section of docs/ENVIRONMENT.md.
    """
    env_path = Path(path) if path else Path(__file__).resolve().parents[2] / ".env"
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()

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
