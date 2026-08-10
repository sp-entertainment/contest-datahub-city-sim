"""One handler per subcommand of the `blindcity` CLI.

Each module exposes `run(args) -> int` and does the work; `blindcity/cli.py` owns argparse and
nothing else. Handlers are plain functions over a parsed-args object so a test can call them
directly without going through the parser.

Imports inside the handlers are deliberately lazy. `blindcity --help` and every subcommand's
`--help` must work on a clean checkout with no database, no API key and no Docker running, which
means nothing heavy may be imported at module scope.
"""
