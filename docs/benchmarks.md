# Step 5 — Measured performance

All numbers are from this machine, this code, single run each. Raw JSON with
the full configuration is in `benchmarks/results/`.

- Machine: Apple M1 Pro, 10 cores (8 performance + 2 efficiency), 16 GB, macOS 27.0.1 (arm64)
- Python: CPython 3.12.12 (`.venv`), pokerlab 0.1.0, no compiled extensions
- Engine versions for comparison probes: pokerkit 0.7.7, pypokerengine 1.0.1
- Warm-up: 5 tournaments per process, excluded from timing. Timing covers full
  tournaments (seating, dealing, betting, showdown, elimination, scoring, ICM),
  with `deadline_mode="enforce"` (the 1 ms check is on).
- Seeds: tournament *i* uses seed `1 + i`; every configuration plays the same tournaments.
- Bot mixes: `mixed` = call, random, heuristic, random, heuristic, call, random, heuristic;
  `heuristic` = 8 heuristic bots; `call` = 8 call bots (worst case: 200 hands, 8-way showdowns, ~24 decisions/hand).

## Throughput

Command:

```
python benchmarks/bench_throughput.py --tournaments 100 1000 --workers 1 2 4 8 --mix mixed heuristic call --out benchmarks/results/throughput.json
python benchmarks/bench_throughput.py --tournaments 10000 --workers 1 8 --mix mixed --out benchmarks/results/throughput_10k_mixed.json
python benchmarks/bench_throughput.py --tournaments 10000 --workers 8 --mix call heuristic --out benchmarks/results/throughput_10k_worst.json
```

Single core (workers=1):

| mix | tournaments | hands/s | tournaments/s | decisions/s | wall | hands/tournament | max RSS |
|---|---:|---:|---:|---:|---:|---:|---:|
| mixed | 100 | 34,699 | 253.7 | 136,106 | 0.39 s | 137 | 26 MB |
| mixed | 1,000 | 33,690 | 239.6 | 138,503 | 4.17 s | 141 | 30 MB |
| mixed | 10,000 | 34,011 | 237.8 | 139,616 | 42.05 s | 143 | 27 MB |
| heuristic | 1,000 | 28,013 | 141.6 | 147,127 | 7.06 s | 198 | 30 MB |
| call | 1,000 | 13,249 | 66.3 | 320,917 | 15.09 s | 200 | 31 MB |

Multi-process scaling (`multiprocessing` spawn pool, 1,000 tournaments):

| mix | workers | hands/s | tournaments/s | wall | CPU (sum) | speed-up |
|---|---:|---:|---:|---:|---:|---:|
| mixed | 1 | 33,690 | 240 | 4.17 s | 4.14 s | 1.0× |
| mixed | 2 | 67,192 | 478 | 2.09 s | 4.06 s | 2.0× |
| mixed | 4 | 126,456 | 899 | 1.11 s | 4.15 s | 3.8× |
| mixed | 8 | 221,093 | 1,573 | 0.64 s | 4.37 s | 6.6× |
| call | 8 | 93,530 | 468 | 2.14 s | 15.84 s | 7.1× |

Full scored-round scale (10,000 tables):

| mix | workers | hands | wall | hands/s | tournaments/s |
|---|---:|---:|---:|---:|---:|
| mixed | 1 | 1.43 M | 42.1 s | 34,011 | 238 |
| mixed | 8 | 1.43 M | 6.1 s | 235,493 | 1,646 |
| heuristic | 8 | 1.98 M | 9.8 s | 201,857 | 1,020 |
| call (worst) | 8 | 2.00 M | 21.1 s | 94,898 | 475 |

Reading: one organizer-sized round (10,000 eight-bot tables) costs 6–21 s on
8 workers, 42 s–2.5 min on one core, depending on how many hands tables last.
Memory is ~30 MB per process. CPU time ≈ wall time at workers=1, so the
process is compute-bound and nothing is waiting on I/O.

## Decision latency

Command: `python benchmarks/bench_latency.py --tournaments 200 --out benchmarks/results/latency.json`

`in-sim` = `perf_counter_ns` around every `act()` during 200 full tournaments
(`deadline_mode="record"`, so no fallback replaces slow calls).
`isolated` = the same bot replaying recorded observations in a tight loop
(agent cost only). Timer overhead ≈ 42 ns per pair.

| bot | where | n | p50 | p99 | p99.9 | max | > 1 ms |
|---|---|---:|---:|---:|---:|---:|---:|
| call | in-sim | 27,094 | 0.1 µs | 0.2 µs | 0.7 µs | 7.1 µs | 0 |
| call | isolated | 440 | 0.1 µs | 0.2 µs | 1.4 µs | 1.4 µs | 0 |
| random | in-sim | 14,417 | 0.3 µs | 2.5 µs | 6.9 µs | 28.9 µs | 0 |
| random | isolated | 432 | 0.2 µs | 1.0 µs | 2.3 µs | 2.3 µs | 0 |
| heuristic | in-sim | 71,431 | 2.0 µs | 6.6 µs | 14.5 µs | 227.6 µs | 0 |
| heuristic | isolated | 2,172 | 1.6 µs | 5.2 µs | 12.4 µs | 73.8 µs | 0 |

Full simulation cost: 112,942 decisions in 0.84 s → **7.4 µs per decision
all-in** (engine + agents + timing). The heuristic bot alone is ~2 µs p50, so
the engine is ~70% of the per-decision cost with these fixtures. The 1 ms
deadline is therefore ~500× the median cost of the heuristic fixture; the
risk at the event is not the median but tail events (GC pauses, first-call
imports, allocation spikes), which the organizer's timing semantics will
decide. Two in-sim maxima (228 µs, 74 µs) were observed across ~113k calls
and are consistent with GC pauses.

## What was optimized (and what was not)

Profiling (`cProfile`, 20 mixed tournaments) before optimization showed:
`random.shuffle` on 52 cards = 27% of runtime (51 Python-level `_randbelow`
calls); `Observation.__init__` via a `setattr` loop = 13%; `sum(paid)` per
decision and list rebuilding in the betting loop. Fixes: an exactly uniform
k-permutation dealer using one `getrandbits` call (`cards.deal_cards`,
uniformity tested by chi-square), a positional `__slots__` constructor, and a
running pot total. Result: ~1.5–1.8× (mixed mix 21k → 34k hands/s). The
PokerKit differential test passed unchanged after the rewrite.

Not done: no compiled components, no engine replacement. The current rate
already runs a 10,000-table round in seconds on 8 cores; a compiled evaluator
or betting loop is only justified if later workloads (e.g. millions of rounds
for strategy search) demand it, and then only after measuring again.

## Caveats

- Single runs; expect ±5–10% run-to-run variation on a laptop (thermal state, background load).
- `multiprocessing` scaling uses 8 workers on 8 performance cores; adding the 2 efficiency cores was not measured.
- The bot fixtures are cheap. A real bot that does lookups in a 100 MB table or runs Monte Carlo will dominate the per-decision cost; the latency harness is the tool to check that.
