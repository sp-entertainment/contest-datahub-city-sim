# Contributing

## Changes

Work on `main` and commit straight to it. This is a nine-day solo sprint against a fixed deadline —
branch-and-review ceremony buys nothing here and costs time the schedule does not have. Branch only
if you actually want one, for something long-running or risky.

- One concern per commit. Small commits are the substitute for review: they are what makes a bad
  change easy to find and easy to revert.
- Describe what changed and why. Link the relevant entry in `docs/DECISIONS.md` when a decision drove
  the change.
- Update `docs/FEATURES.md` when behaviour visible to a player or judge changes.
- Keep `main` working. Run `uv run pytest -q` before you push. Committing to `main` directly means
  nothing catches a broken commit before it lands.

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
