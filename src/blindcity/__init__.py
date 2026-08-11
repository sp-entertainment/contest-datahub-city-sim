"""City Sim Agent Benchmark — does a data catalog make an agent better at its job?

The distribution and CLI are still named `blindcity`, which was the project's working title. The
name stayed when the project did not: renaming a published entry point costs every reader who has
a command in their notes and buys nothing the README does not already say.

Package layout mirrors the project map in AGENTS.md, with one deviation recorded there: the
metadata-emission package is `catalog`, not `datahub`, because a top-level `datahub` package
would shadow the installed `acryl-datahub` module of the same name.
"""

__version__ = "0.1.0"
