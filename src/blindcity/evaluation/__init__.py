"""A/B harness: the same agent, the same seed, with and without DataHub context.

This is the spine of the submission (docs/DECISIONS.md). It produces the one number the entry is
built around, so the control has to be defensible: same model, same prompt, same seed, same tool
budget, same full SQL access. Only the metadata context differs.

Named `evaluation` while the command stays `eval`, to avoid a module named after a builtin.

Plan: TASKS.md Day 7.
"""
