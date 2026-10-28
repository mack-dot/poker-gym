# pokerlab — P0: fast, verified eight-player tournament simulator

Rehearsal simulator for *No Limit: A Bot Building Tournament* (Sequoia ×
Citadel Securities × OpenAI). Pure Python, no dependencies at runtime.

Official rules: `docs/spec/official_rules_v1.md` (source URL, retrieval date,
raw HTML copy). Anything the organizer has not published is labelled
**SYNTHETIC** in code and docs.

## Status of the P0 deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Working eight-player simulator | `pokerlab/engine.py`, `pokerlab/tournament.py` |
| 2 | Reproducible full-tournament execution | `python -m pokerlab.cli run/replay`; sha256 record hash; `docs/replays/` |
| 3 | Tournament and ICM scoring | `pokerlab/tournament.py` (`assign_finishes`, `run_round`, `final_score`), `pokerlab/icm.py` |
| 4 | Three baseline bots | `pokerlab/bots/` — `CallBot`, `RandomBot`, `HeuristicBot` (fixtures, not strong play) |
| 5 | Two verified variant mutations | `pokerlab/variants.py`; specs in `docs/variants/` |
| 6 | Passing correctness tests | `tests/` — 74 tests incl. PokerKit parity and 15 injected faults (11 fault-detection tests) |
| 7 | Throughput benchmarks | `docs/benchmarks.md`, `benchmarks/results/throughput*.json` |
| 8 | Decision-latency benchmarks | `docs/benchmarks.md`, `benchmarks/results/latency.json` |
| 9 | Exact commands | below |
| 10 | Fidelity assessment and unknowns | `docs/fidelity.md`; engine choice in `docs/engine_evaluation.md` |

Headline numbers (Apple M1 Pro, CPython 3.12, single core): 34k hands/s with
the mixed bot set, 13k hands/s in the all-call worst case; a 10,000-table
scored round runs in 6–21 s on 8 workers. Fixture-bot decision latency p50 is
0.1–2 µs, p99.9 ≤ 15 µs; the engine costs ~7 µs per decision all-in.

## Setup

```
cd /Users/mackianni/poker-gym
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -e . pytest pokerkit==0.7.7     # pokerkit is only used as a test oracle
```

## Run a tournament

```
# one eight-player sit-and-go, verify all invariants, save the record
python -m pokerlab.cli run --seed 1 --verify --out runs/baseline_seed1.json

# replay from the record's seed and compare the sha256 hash
python -m pokerlab.cli replay runs/baseline_seed1.json

# variants
python -m pokerlab.cli run --seed 21   --variant flush-beats-full-house --verify
python -m pokerlab.cli run --seed 2026 --variant pot-limit --verify

# choose seating (8 names from: call, random, heuristic)
python -m pokerlab.cli run --seed 3 --bots heuristic,heuristic,call,random,heuristic,call,random,random

# a scored round: N tables, random seating per table, average points per bot
python -m pokerlab.cli round --tables 1000 --seed 1
```

From Python:

```python
from pokerlab.tournament import run_tournament, run_round, final_score
from pokerlab.bots import CallBot, RandomBot, HeuristicBot
from pokerlab.variants import VARIANTS
from pokerlab.checks import check_tournament

bots = [CallBot(), RandomBot(), HeuristicBot(), RandomBot(), HeuristicBot(), CallBot(), RandomBot(), HeuristicBot()]
res = run_tournament(bots, rules=VARIANTS["baseline"], seed=1)
check_tournament(res, VARIANTS["baseline"])
print(res.points, res.positions, res.icm_applied, res.record_hash)
```

## Tests and benchmarks

```
python -m pytest                       # 74 tests, ~12 s (includes the exhaustive 2.6M-hand evaluator check)
python -m pytest -m "not slow"         # ~8 s
python benchmarks/bench_throughput.py --tournaments 100 1000 --workers 1 2 4 8 --mix mixed heuristic call
python benchmarks/bench_latency.py --tournaments 200
```

## Layout and the replaceable boundary

```
pokerlab/
  cards.py       card ints, exact-uniform dealer
  evaluator.py   5–7 card evaluator with configurable category order
  rules.py       GameRules / BlindSchedule / PayoutSchedule / BettingRules / HandRanking (synthetic defaults labelled)
  agent.py       rehearsal Agent protocol: Observation, Action, TableInfo, AgentAdapter (deadline, errors, legality)
  engine.py      one hand: blinds, dealing, betting rounds, side pots, showdown
  icm.py         Malmuth–Harville ICM + brute-force reference
  tournament.py  sit-and-go runner, elimination ranking, record hash, run_round, final_score
  checks.py      invariant checkers (used by tests, CLI --verify, fault-injection tests)
  variants.py    the two rule mutations
  adapters.py    seam for the official starter kit (no invented signatures)
  testing.py     ScriptedAgent / PolicyAgent / build_deck for exact scenarios
  bots/          call, random, heuristic
tests/           correctness, PokerKit differential, fault injection, variants
benchmarks/      throughput and latency harnesses + results
docs/            spec, engine evaluation, variants, benchmarks, fidelity
```

Bots talk only to `pokerlab.agent`. Rules are data in `pokerlab.rules`.
Scoring is separate from the engine. See `docs/fidelity.md` for the parity
plan once the starter kit is available.
