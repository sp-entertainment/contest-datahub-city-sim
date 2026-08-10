# Blind City — mode comparison

Seed 42 · model `gpt-5.6-luna` · green threshold 0.62 · commit `da8381d`

| Mode | Runs | Mean index | Spread | Recovered | Green turn | Tokens | LLM calls | SQL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `agent_raw` | 1 | **0.6488** | 0.0000 | 1/1 | 10 | 184,963 | 30 | 62 |
| `agent_datahub` | 1 | **0.7187** | 0.0000 | 1/1 | 5 | 213,980 | 25 | 59 |
| `agent_datahub_live` | 1 | **0.8187** | 0.0000 | 1/1 | 3 | 201,578 | 19 | 22 |
| `agent_analytics` | 1 | **0.6825** | 0.0000 | 1/1 | 5 | 1,500,818 | 12 | 0 |
| `bad_policy` | 1 | **0.3244** | 0.0000 | 0/1 | - | 0 | 0 | 0 |
| `good_policy` | 1 | **0.8132** | 0.0000 | 1/1 | 4 | 0 | 0 | 0 |

Ordering as expected: agent_datahub_live > agent_datahub > agent_raw.

Single run per mode: no variance estimate. Measured spread on repeated identical runs has reached 0.02 of final index, so treat gaps below that as unresolved.
