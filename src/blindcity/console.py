"""Make CLI output survive a Windows console.

Python picks the console's legacy code page (cp1252 here) for stdout, and any character
outside it raises `UnicodeEncodeError` at print time. Our output carries en dashes, arrows
and ellipses — glossary text, lineage hints, column descriptions — so a command that did all
its real work would still exit non-zero on the final status line. `datahub-emit` did exactly
that: the catalog was written, the assertions ran, and then it died printing an arrow.

Called first thing in every console entry point.
"""

from __future__ import annotations

import sys
from typing import IO, Any


def _reconfigure(stream: IO[Any] | None) -> None:
    # `reconfigure` exists on TextIOWrapper; a redirected or wrapped stream may not have it.
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):
        # Already detached, or a stream that will not take an encoding. Not worth failing over.
        pass


def configure_console() -> None:
    """Switch stdout and stderr to UTF-8, replacing anything the terminal cannot render."""
    _reconfigure(sys.stdout)
    _reconfigure(sys.stderr)
