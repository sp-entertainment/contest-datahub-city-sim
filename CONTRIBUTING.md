# Contributing

## Project status

**This project was built for a contest and is not maintained.** It was written as an entry to
[Build with DataHub: The Agent Hackathon](https://datahub.devpost.com/), it does what it set out to
do, and it is finished.

**Pull requests and issues are not accepted.** Nobody is watching the queue, so an open PR here
would sit unread rather than be reviewed.

**Fork it and make it your own.** The licence is Apache 2.0 and the grant is deliberate: take the
simulation, the catalog authoring, the benchmark harness, or the whole thing, and do what you like
with it. No attribution beyond what the licence already requires, and no need to ask.

The rest of this file is the conventions the code was written to. It is here so a fork inherits the
rules that keep the benchmark meaningful, not as a contribution process.

## Determinism

The simulation must stay reproducible from a seed. Any change that introduces unseeded randomness,
wall-clock dependence, or iteration over unordered collections breaks the evaluation harness — the
A/B comparison means nothing if the two arms are not facing the same city.

## Numbers

A change to the simulation, the health index, the prompts, or the catalog invalidates every recorded
result. Say so in the commit, and do not leave `docs/RESULTS.md` claiming a figure the code can no
longer produce. Re-running is fast for `good_policy` and `bad_policy` and expensive for the agent
modes — a result marked stale is honest, one quietly left standing is not.

## Changes

- One concern per commit. Small commits are what make a bad change easy to find and easy to revert.
- Describe what changed and why. Link the relevant entry in `docs/DECISIONS.md` when a decision
  drove the change.
- Update `docs/FEATURES.md` when behaviour visible to a player or judge changes.
- Run `uv run pytest -q` and `uv run ruff check src tests` before you push.

## Commit messages

Conventional Commits.

```
feat(sim): add road wear accumulation
fix(datahub): correct column-level lineage for migration
docs(decisions): record warehouse choice
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.

## Licensing

Apache 2.0. Do not introduce GPL-licensed code or derivatives — the two licences are incompatible.
