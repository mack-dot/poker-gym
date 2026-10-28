# Poker Gym — unofficial practice simulator

Fast, verified eight-player tournament simulator for *No Limit: A Bot
Building Tournament* (Sequoia × Citadel Securities × OpenAI).

**This is not Sequoia's official starter kit.** It is an independent
rehearsal tool. The official kit, secret variant, payouts, and harness
arrive only on tournament day. Anything the organizer has not published is
labelled **SYNTHETIC** in code and docs.

Pure Python, MIT licensed, no runtime dependencies. Package: `pokergym`.
Official rules snapshot: `docs/spec/official_rules_v1.md`.

## Quick start

```
git clone https://github.com/mack-dot/poker-gym.git
cd poker-gym
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Run one eight-player sit-and-go, check invariants, and save the record:

```
python -m pokergym.cli run --seed 1 --verify --out runs/baseline_seed1.json
```

Copy the starter bot, edit `act()`, then measure it against the sparring lineup:

```
cp examples/my_bot.py my_bot.py
python -m pokergym.cli eval --bot my_bot.py:MyBot --vs sparring --tables 200 --workers 4 --baseline tag
```

`eval` seats your bot in a random seat, reports points per table with a 95%
CI, finish distribution, deadline misses, and a paired comparison against
`tag` on the same seats. Raise `--tables` once the bot is legal.

```
python -m pytest -m "not slow"     # correctness suite, ~2 min
```

## Practice (the gym)

```
cp examples/my_bot.py my_bot.py                       # edit act()
python -m pokergym.cli eval --bot my_bot.py:MyBot --vs sparring --tables 2000 --workers 8 --baseline tag
python -m pokergym.cli ladder --tables 2000 --workers 8
python -m pokergym.cli show runs/x.json --seat 0 --hands 0-40
python -m pokergym.cli equity AsKd --board 7s8s2c --opponents 2
```

`eval` seats your bot in a random seat against a lineup of sparring partners
(`tag`, `lag`, `shortstack`, `icm`, `adaptive`), reports points per table
with a 95% CI, finish distribution, deadline misses, illegal actions, and a
**paired** comparison against a baseline replayed in the same seats. Full
guide: `docs/gym.md`.

## Tournament day

```
python drills/fake_kit/run_drill.py reference_adapter.py:Adapted      # rehearse wiring to an unseen kit
python scripts/bundle.py --bot examples/my_bot.py:MyBot --out submission/bot.py   # one file, no deps, smoke-tested
```

- `docs/runbook_60min.md`: minute-by-minute plan from kit drop to final
  submission, plus a rule-variant checklist mapped to `pokergym` knobs.
- `pokergym/bridge.py`: `build_observation(**plain_values)` turns whatever
  the kit gives (card strings, stacks, bets) into our `Observation`, deriving
  pot, to-call and raise bounds; `action_to_text` / `action_from_text` are a
  REHEARSAL text codec modelled on the landing-page demo.
- `drills/fake_kit/`: a deliberately different mock kit, an answer-key
  adapter, and a runner that checks legality, decision parity with the
  native bot, and overhead. Target: PASS in 15 minutes.
- `scripts/bundle.py`: inlines the bot and every `pokergym` module it uses
  into one file with the equity table embedded (~100 KB), then plays it
  against the sparring roster before it will say "wrote".
- Every sparring bot has `configure(rules)`: the gym calls it so the bot's
  hand evaluator follows the variant's `HandRanking`.

## Sealed rehearsal (the arena)

```
python -m pokergym.arena smoke                            # ~90 s bounded end-to-end run with a stand-in competitor
python -m pokergym.arena rehearse ~/arena/r1 --seed 7     # the real 60-minute exercise; you press Enter to start
```

A concealed one-rule mutation (17 in reserve, 6 families), a sandboxed
workspace holding only what the organizer would hand over, a real 60-minute
clock with one submission per 5 minutes, a 7-stage validator, a hidden
evaluation against withheld opponents and seeds, and a postmortem with A-F
failure classes. Nothing in it starts an AI; the real run is a command you
launch yourself. Guide, measurements, and limitations: `docs/arena.md`.

## Status of the P0 deliverables

| # | Deliverable | Where |
|---|---|---|
| 1 | Working eight-player simulator | `pokergym/engine.py`, `pokergym/tournament.py` |
| 2 | Reproducible full-tournament execution | `python -m pokergym.cli run/replay`; sha256 record hash; `docs/replays/` |
| 3 | Tournament and ICM scoring | `pokergym/tournament.py` (`assign_finishes`, `run_round`, `final_score`), `pokergym/icm.py` |
| 4 | Three baseline bots | `pokergym/bots/` — `CallBot`, `RandomBot`, `HeuristicBot` (fixtures, not strong play) |
| 5 | Two verified variant mutations | `pokergym/variants.py`; specs in `docs/variants/` |
| 6 | Passing correctness tests | `tests/` — 201 tests incl. PokerKit parity, 15 injected faults, a determinism regression suite, the gym, and the arena lifecycle |
| 7 | Throughput benchmarks | `docs/benchmarks.md`, `benchmarks/results/throughput*.json` |
| 8 | Decision-latency benchmarks | `docs/benchmarks.md`, `benchmarks/results/latency.json` |
| 9 | Exact commands | below |
| 10 | Fidelity assessment and unknowns | `docs/fidelity.md`; engine choice in `docs/engine_evaluation.md` |

Headline numbers (Apple M1 Pro, CPython 3.12, median of 3 runs): 30–34k
hands/s with the mixed bot set on one core, 12k hands/s in the all-call worst
case; a 10,000-table scored round runs in 6–21 s on 8 workers. Fixture-bot
decision latency p50 is 0.1–2 µs, p99.9 ≤ 21 µs, but 1 call in 214,293
exceeded the 1 ms deadline (GC pause). See `docs/benchmarks.md`.

## Setup

`pip install -e ".[dev]"` (see Quick start) is enough. `pokerkit` is a
test-only oracle, not a runtime dependency. If you use `uv`:

```
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Run a tournament

```
# one eight-player sit-and-go, verify all invariants, save the record
python -m pokergym.cli run --seed 1 --verify --out runs/baseline_seed1.json

# replay from the record's seed and compare the sha256 hash
python -m pokergym.cli replay runs/baseline_seed1.json

# variants
python -m pokergym.cli run --seed 21   --variant flush-beats-full-house --verify
python -m pokergym.cli run --seed 2026 --variant pot-limit --verify

# choose seating: 8 bot specs (registry names, file.py:Class, or pkg.module:Class)
python -m pokergym.cli run --seed 3 --bots tag,lag,shortstack,icm,adaptive,heuristic,random,call

# a scored round: N tables, random seating per table, average points per bot
python -m pokergym.cli round --tables 1000 --seed 1
```

From Python:

```python
from pokergym.tournament import run_tournament, run_round, final_score
from pokergym.bots import CallBot, RandomBot, HeuristicBot
from pokergym.variants import VARIANTS
from pokergym.checks import check_tournament

bots = [CallBot(), RandomBot(), HeuristicBot(), RandomBot(), HeuristicBot(), CallBot(), RandomBot(), HeuristicBot()]
res = run_tournament(bots, rules=VARIANTS["baseline"], seed=1)
check_tournament(res, VARIANTS["baseline"])
print(res.points, res.positions, res.icm_applied, res.record_hash)
```

## Tests and benchmarks

```
python -m pytest                       # 201 tests, ~3-4 min (sandboxed arena lifecycle, a 45 s real-clock smoke rehearsal, 2.6M-hand evaluator check)
python -m pytest -m "not slow"         # ~2 min
python benchmarks/bench_arena.py --out benchmarks/results/arena.json
python benchmarks/bench_throughput.py --tournaments 100 1000 --workers 1 2 4 8 --mix mixed heuristic call --repeats 3
python benchmarks/bench_latency.py --tournaments 200 --repeats 3
```

## Layout and the replaceable boundary

```
pokergym/
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
  bridge.py      build_observation from plain kit values; REHEARSAL text action codec
  testing.py     ScriptedAgent / PolicyAgent / build_deck for exact scenarios
  gym.py         load a bot by spec, lineups, paired evaluate(), ladder()
  equity.py      169 hand classes, Monte Carlo equity, precomputed preflop + vs-range tables
  stats.py       OpponentTracker (VPIP, PFR, 3-bet, fold-to-steal, c-bet, aggression)
  data/          preflop_equity.json (generated by scripts/gen_preflop_equity.py)
  bots/          fixtures: call, random, heuristic; sparring: tag, lag, shortstack, icm, adaptive
  bots/features.py  position, stack depth, made-hand class, draws/outs, board texture
examples/        my_bot.py starter template
drills/fake_kit/ mock kit + reference adapter + drill runner (wiring rehearsal)
scripts/         bundle.py (single-file submission), gen_preflop_equity.py
tests/           correctness, PokerKit differential, fault injection, variants, gym, bridge, bundle, drill
benchmarks/      throughput and latency harnesses + results
docs/            spec, engine evaluation, variants, benchmarks, fidelity, gym, 60-minute runbook
```

Bots talk only to `pokergym.agent`. Rules are data in `pokergym.rules`.
Scoring is separate from the engine. See `docs/fidelity.md` for the parity
plan once the starter kit is available.

## License

MIT. See `LICENSE`.

`docs/spec/rules_2026-10-28.html` is a retrieved copy of Sequoia's published
rules page and is not covered by this license. Tournament names and
organizer marks belong to their owners. This project is unaffiliated with
Sequoia, Citadel Securities, and OpenAI.
