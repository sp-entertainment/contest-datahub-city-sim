# City Sim Agent Benchmark — mode comparison

Seed 42 · model `gpt-5.6-luna` · green threshold 0.62 · commit `81a5c9b`

| Mode | Runs | Mean index | Spread | Recovered | Green turn | Tokens | LLM calls | SQL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `agent_raw` | 3 | **0.6416** | 0.0238 | 3/3 | 9, 7, 9 | 179,499 | 28 | 64 |
| `agent_datahub` | 3 | **0.7413** | 0.0711 | 3/3 | 6, 5, 6 | 221,770 | 25 | 52 |
| `agent_datahub_live` | 3 | **0.8092** | 0.0175 | 3/3 | 3, 4, 3 | 177,444 | 17 | 16 |
| `agent_analytics` | 3 | **0.8017** | 0.0554 | 3/3 | 4, 3, 4 | 1,456,443 | 12 | 0 |
| `bad_policy` | 1 | **0.3244** | 0.0000 | 0/1 | - | 0 | 0 | 0 |
| `good_policy` | 1 | **0.8132** | 0.0000 | 1/1 | 4 | 0 | 0 | 0 |

Ordering as expected: agent_datahub_live > agent_datahub > agent_raw.

Run-to-run spread reaches 0.0711, which is at least as large as the smallest gap between modes (0.0075). Differences that size are not distinguishable from noise at this number of repeats.
