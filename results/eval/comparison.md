# Blind City — mode comparison

Seed 42 · model `$LLM_MODEL` · green threshold 0.62 · commit `9ad5bee`

| Mode | Runs | Mean index | Spread | Recovered | Green turn | Tokens | LLM calls | SQL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `agent_raw` | 1 | **0.6837** | 0.0000 | 1/1 | 7 | 242,289 | 30 | 77 |
| `agent_datahub` | 1 | **0.7362** | 0.0000 | 1/1 | 6 | 286,810 | 29 | 76 |
| `agent_datahub_live` | 1 | **0.8147** | 0.0000 | 1/1 | 3 | 313,163 | 26 | 39 |

Ordering as expected: agent_datahub_live > agent_datahub > agent_raw.

Single run per mode: no variance estimate. Measured spread on repeated identical runs has reached 0.02 of final index, so treat gaps below that as unresolved.
