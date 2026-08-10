# Blind City — mode comparison

Seed 42 · model `gpt-5.6-luna` · green threshold 0.62 · commit `3da6502`

| Mode | Runs | Mean index | Spread | Recovered | Green turn | Tokens | LLM calls | SQL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `agent_raw` | 3 | **0.7151** | 0.0290 | 3/3 | 6, 7, 7 | 177,287 | 27 | 65 |
| `agent_datahub` | 3 | **0.7378** | 0.0182 | 3/3 | 5, 5, 5 | 232,114 | 26 | 59 |
| `agent_datahub_live` | 3 | **0.8129** | 0.0824 | 3/3 | 4, 3, 4 | 201,490 | 19 | 13 |
| `agent_analytics` | 3 | **0.6965** | 0.0177 | 3/3 | 6, 4, 5 | 603,624 | 12 | 0 |

Ordering as expected: agent_datahub_live > agent_datahub > agent_raw.

Run-to-run spread reaches 0.0824, which is at least as large as the smallest gap between modes (0.0227). Differences that size are not distinguishable from noise at this number of repeats.
