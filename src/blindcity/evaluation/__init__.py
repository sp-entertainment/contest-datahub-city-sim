"""Run the three benchmark modes and compare them.

The project is a benchmark (docs/DECISIONS.md, 2026-08-02): a scenario puts the city into a crisis,
a controller pulls levers over a fixed turn budget, and a composite health index scores whether it
recovered. Three modes face identical conditions — `human`, `agent_datahub`, `agent_raw`.

`agent_datahub` vs `agent_raw` is the headline and its control has to be defensible: same model,
prompt, seed, turn budget, tool budget, and SQL access. Only the catalog context differs.

Named `evaluation` rather than `eval`, which shadows a builtin. The command is
`blindcity compare`; only the pure comparison functions live here now, the runner having moved
to `blindcity/commands/run.py`.

Plan: TASKS.md, Slice 8. Build the harness; a human runs the scored evaluation (task H3).
"""
