# Step 5 — Measured performance

All numbers are from this machine, this code. Raw JSON with the full
configuration, per-run spread, and the command line is in `benchmarks/results/`.

- Machine: Apple M1 Pro, 10 cores (8 performance + 2 efficiency), 16 GB, macOS 27.0.1 (arm64)
- Python: CPython 3.12.12 (`.venv`), pokergym 0.1.0, no compiled extensions
- Engine versions for the comparison probe in `docs/engine_evaluation.md`: pokerkit 0.7.7, pypokerengine 1.0.1
- Statistic: **median of 3 independent runs** per configuration. Earlier single runs
  varied by up to 5× on short workloads (a 0.09 s 8-worker run once reported
  32k hands/s instead of 144k), so medians are published and the min–max spread
  is kept in the JSON.
- Warm-up: 5 tournaments per process, excluded from timing. Timing covers full
  tournaments (seating, dealing, betting, showdown, elimination, scoring, ICM),
  with `deadline_mode="record"` (the 1 ms check runs and violations are counted
  but do not alter play, so a timing outlier cannot perturb the measurement —
  see `docs/fidelity.md`).
- Seeds: tournament *i* uses seed `1 + i`; every configuration plays the same tournaments.
- Bot mixes: `mixed` = call, random, heuristic, random, heuristic, call, random, heuristic;
  `heuristic` = 8 heuristic bots; `call` = 8 call bots (worst case: 200 hands, 8-way showdowns, ~24 decisions/hand).

## Throughput

```
python benchmarks/bench_throughput.py --tournaments 100 1000 --workers 1 2 4 8 --mix mixed heuristic call --repeats 3 --out benchmarks/results/throughput.json
python benchmarks/bench_throughput.py --tournaments 10000 --workers 1 8 --mix mixed --repeats 3 --out benchmarks/results/throughput_10k_mixed.json
python benchmarks/bench_throughput.py --tournaments 10000 --workers 8 --mix call heuristic --repeats 3 --out benchmarks/results/throughput_10k_worst.json
```

Single core (workers=1), median of 3:

| mix | tournaments | hands/s | tournaments/s | decisions/s | wall | hands/tournament | max RSS |
|---|---:|---:|---:|---:|---:|---:|---:|
| mixed | 100 | 34,316 | 250.9 | 134,606 | 0.40 s | 137 | 26 MB |
| mixed | 1,000 | 31,916 | 227.0 | 131,213 | 4.26 s | 141 | 28 MB |
| mixed | 10,000 | 29,667 | 207.4 | 121,784 | 44.15 s | 143 | 27 MB |
| heuristic | 1,000 | 26,509 | 134.0 | 139,230 | 7.36 s | 198 | 28 MB |
| call | 1,000 | 12,396 | 62.0 | 300,253 | 15.87 s | 200 | 28 MB |

Multi-process scaling (`multiprocessing` spawn pool), median of 3:

| mix | tournaments | workers | hands/s | tournaments/s | wall | CPU (sum) | speed-up |
|---|---:|---:|---:|---:|---:|---:|---:|
| mixed | 1,000 | 1 | 31,916 | 227 | 4.26 s | 4.19 s | 1.0× |
| mixed | 1,000 | 2 | 62,260 | 443 | 2.15 s | 4.17 s | 2.0× |
| mixed | 1,000 | 4 | 122,857 | 874 | 1.14 s | 4.25 s | 3.8× |
| mixed | 1,000 | 8 | 210,918 | 1,500 | 0.65 s | 4.42 s | 6.6× |
| call | 1,000 | 8 | 59,174 | 296 | 3.10 s | 17.87 s | 4.8× |
| heuristic | 1,000 | 8 | 161,575 | 817 | 1.22 s | 7.96 s | 6.1× |

Full scored-round scale (10,000 tables), median of 3:

| mix | workers | hands | wall | hands/s | tournaments/s |
|---|---:|---:|---:|---:|---:|
| mixed | 1 | 1.43 M | 44.2 s | 29,667 | 207 |
| mixed | 8 | 1.43 M | 6.2 s | 230,223 | 1,610 |
| heuristic | 8 | 1.98 M | 10.0 s | 195,208 | 986 |
| call (worst) | 8 | 2.00 M | 21.3 s | 91,045 | 455 |

Reading: one organizer-sized round (10,000 eight-bot tables) costs **6–21 s on
8 workers**, 44 s–2.5 min on one core, depending on how many hands tables last.
CPU time ≈ wall time at workers=1 and total CPU is constant across worker
counts, so the process is compute-bound; scaling is sub-linear mainly at 8
workers because 8 performance cores are shared with the OS and the two
efficiency cores are not used. Memory is ~30 MB per process.

## Decision latency

```
python benchmarks/bench_latency.py --tournaments 200 --repeats 3 --out benchmarks/results/latency.json
```

`in-sim` = `perf_counter_ns` around every `act()` during 600 full tournaments
(`deadline_mode="record"`, so no fallback replaces slow calls).
`isolated` = the same bot replaying recorded observations in a tight loop
(agent cost only). Timer overhead ≈ 41 ns per pair.

| bot | where | n | p50 | p99 | p99.9 | max | > 1 ms |
|---|---|---:|---:|---:|---:|---:|---:|
| call | in-sim | 81,282 | 0.1 µs | 0.2 µs | 1.0 µs | 46.9 µs | 0 |
| call | isolated | 440 | 0.1 µs | 0.1 µs | 0.3 µs | 0.3 µs | 0 |
| random | in-sim | 43,251 | 0.3 µs | 2.3 µs | 7.3 µs | 47.9 µs | 0 |
| random | isolated | 432 | 0.2 µs | 1.0 µs | 5.4 µs | 5.4 µs | 0 |
| heuristic | in-sim | 214,293 | 2.0 µs | 7.2 µs | 20.3 µs | **1,275.6 µs** | **1** |
| heuristic | isolated | 2,172 | 1.7 µs | 6.8 µs | 21.4 µs | 27.5 µs | 0 |

Full simulation cost: 338,826 decisions in 2.61 s → **7.7 µs per decision
all-in** (engine + agents + timing). The heuristic bot alone is ~2 µs p50, so
the engine is roughly 70% of the per-decision cost with these fixtures.

The 1,275 µs outlier is the important number: **1 call in 214,293 exceeded the
1 ms deadline**, at p99.9 = 20 µs. Tail events, not medians, decide rule 3.7
compliance. It is consistent with a GC pause in the measuring process. This is
why the default deadline mode records instead of enforcing: enforcing would
turn a GC pause into a changed game and an unreproducible record. For a real
submission, the bot should avoid allocation and large tables in `act()`.

### Sparring bots (added with the gym)

Same harness, `MIX` = one of every registered bot, 600 tournaments. Measured on
the same laptop but under heavy background load (load average 12–15: a
browser, a VM, Docker), which matters for the in-sim tail. Results in
`benchmarks/results/latency.json`.

| bot | isolated p50 | isolated p99 | isolated p99.9 | isolated max | in-sim p99.9 | in-sim > 1 ms |
|---|---:|---:|---:|---:|---:|---:|
| tag | 5.6 µs | 25.8 µs | 117.8 µs | 134 µs | 78 µs | 5 / 69,426 (0.007%) |
| lag | 5.8 µs | 15.5 µs | 63.2 µs | 117 µs | 70 µs | 3 / 66,276 (0.005%) |
| shortstack | 5.1 µs | 14.2 µs | 40.5 µs | 155 µs | 72 µs | 1 / 75,489 (0.001%) |
| icm | 6.3 µs | 36.8 µs | 57.2 µs | 75 µs | 111 µs | 10 / 69,174 (0.014%) |
| adaptive | 8.8 µs | 19.8 µs | 39.6 µs | 56 µs | 100 µs | 1 / 68,436 (0.001%) |
| heuristic | 1.9 µs | 5.8 µs | 35.3 µs | 592 µs | 28 µs | 0 / 68,970 (0.000%) |

Isolated (bot-only) cost is under 160 µs at the maximum for every sparring
bot, so none of them is close to the deadline on its own. (One earlier run
showed 7 isolated misses for `adaptive` with a 6.6 ms maximum; the next run
of the same code showed a 56 µs maximum. That is a preemption burst, see
below.) The `icm` bot was
the slow one before two fixes: its ICM premium is now computed once per hand
(it depends only on start-of-hand stacks) and uses a subset-DP for one
player's finishing probabilities (`icm.place_probabilities_for`, ~23 µs for
five players instead of ~120 µs for the full recursion).

The in-sim > 1 ms events are **not** the bots and **not** the garbage
collector: 300 tournaments were re-run with the default GC, with
`gc.freeze()` + high thresholds, and with `gc.disable()`, and the miss rate
was 0.022%, 0.027%, 0.027% respectively with worst cases of 18–51 ms. The
fixture bots, re-measured in the same session, missed at the same rate
(0.005–0.014%) although they missed once in 214,293 calls in the quiet P0
session. The misses are OS preemption of the measuring process on a busy
machine. Consequences: (1) compare bots on the `isolated` column, (2) run
latency checks with `--workers 1` on a quiet machine, (3) the organizer's
enforcement on their hardware will still produce some fallback actions that no
bot can prevent; `deadline_mode="enforce"` shows how a bot copes with that.

## What was optimized (and what was not)

Profiling (`cProfile`, 20 mixed tournaments) before optimization showed:
`random.shuffle` on 52 cards = 27% of runtime (51 Python-level `_randbelow`
calls); `Observation.__init__` via a `setattr` loop = 13%; `sum(paid)` per
decision and list rebuilding in the betting loop. Fixes: an exactly uniform
k-permutation dealer using one `getrandbits` call (`cards.deal_cards`,
uniformity tested by chi-square), a positional `__slots__` constructor, and a
running pot total. Result: ~1.0–2.8× depending on mix. The PokerKit
differential test passed unchanged after the rewrite.

Not done: no compiled components, no engine replacement. A 10,000-table round
already runs in seconds on 8 cores; a compiled evaluator or betting loop is
only justified if later workloads (millions of rounds for strategy search)
demand it, and then only after measuring again.

## Caveats

- Medians are stable to a few percent for runs ≥ 1 s, but this laptop was
  bench-marked for ~15 minutes continuously; later runs in the same session were
  up to 20% slower than the first (thermal state). Compare configurations only
  within one JSON file.
- `multiprocessing` scaling uses 8 workers on 8 performance cores; the 2
  efficiency cores were not used, and oversubscription (10 workers) was not measured.
- The bot fixtures are cheap. A real bot that does lookups in a 100 MB table or
  runs Monte Carlo will dominate the per-decision cost; the latency harness is
  the tool to check that, and its `in-sim` column is the one that matters.
