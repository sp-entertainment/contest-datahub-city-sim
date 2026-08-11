# Contributing

## Changes

`main` holds the state the entry was submitted in and is not committed to directly. Work on a
branch — `refinements` for ongoing work, or your own for anything larger — and open a pull request.

Before the deadline this was a nine-day solo sprint committing straight to `main`, and that was the
right trade then. It is not now: the published numbers are reproducible from `main`, and a commit
that lands there changes what a reader gets when they clone it.

- One concern per commit. Small commits are the substitute for review: they are what makes a bad
  change easy to find and easy to revert.
- Describe what changed and why. Link the relevant entry in `docs/DECISIONS.md` when a decision drove
  the change.
- Update `docs/FEATURES.md` when behaviour visible to a player or judge changes.
- Run `uv run pytest -q` and `uv run ruff check src tests` before you push.

## Numbers

A change to the simulation, the health index, the prompts, or the catalog invalidates every recorded
result. Say so in the commit, and do not leave `docs/RESULTS.md` claiming a figure the code can no
longer produce. Re-running is cheap for `good_policy` and `bad_policy` and expensive for the agent
modes — the honest interim state is a result marked stale, never one quietly left standing.

## Commit messages

Conventional Commits.

```
feat(sim): add road wear accumulation
fix(datahub): correct column-level lineage for migration
docs(decisions): record warehouse choice
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.

## Licensing

Apache 2.0. Do not introduce GPL-licensed code or derivatives — the submission requires Apache 2.0,
and the two are incompatible.

## Determinism

The simulation must stay reproducible from a seed. Any change that introduces unseeded randomness,
wall-clock dependence, or iteration over unordered collections breaks the evaluation harness and will
be rejected.
