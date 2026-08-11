"""Auto-mode agent. The closed loop, and the original contribution of this submission.

One iteration: read state from the control surface, gather context from DataHub over its GraphQL
API, query the warehouse over SQL, decide, actuate levers, advance the simulation, observe the
consequence.

Runs as three benchmark modes over one implementation -- `agent_raw`, `agent_datahub` and
`agent_datahub_live` -- with identical model, prompt, seed, turn budget, tool budget and SQL
access, differing only in the catalog block. `tests/test_agent.py` fails the build if anything
else diverges.

`advisor.py` and `advisor_controller.py` are the fourth mode, `agent_analytics`, which delegates
the analysis to the upstream DataHub Analytics Agent running as its own service.
"""
