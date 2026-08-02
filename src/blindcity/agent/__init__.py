"""Auto-mode agent. The closed loop, and the original contribution of this submission.

One iteration: read state from the control surface, gather context from DataHub over MCP, query the
warehouse over SQL, decide, actuate a lever, advance the simulation, observe the consequence.

Manual mode is the upstream `datahub-analytics-agent`, unmodified, and lives outside this package.
Do not ship only that — originality is judged (AGENTS.md).

Requires `TOOLS_IS_MUTATION_ENABLED=true` in the MCP config or mutation tools are silently absent
(docs/ERRORS.md).

Runs as two benchmark arms, `agent_datahub` and `agent_raw`, over one implementation — identical
model, prompt, seed, turn budget, tool budget, and SQL access, differing only in catalog context.

Plan: TASKS.md, Slice 6.
"""
