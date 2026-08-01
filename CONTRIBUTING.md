# Contributing

## Pull requests

- Branch from `main`. Never commit directly to it.
- One concern per pull request.
- Describe what changed and why. Link the relevant entry in `docs/DECISIONS.md` when a decision drove
  the change.
- Update `docs/FEATURES.md` when behaviour visible to a player or judge changes.

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
