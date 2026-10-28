# Step 1 — Engine audit and choice

Repository state at start: empty directory (no prior work to preserve). No
`Aljure` directory exists under this workspace; nothing was touched outside it.

Machine: Apple M1 Pro (8 performance + 2 efficiency cores), 16 GB, macOS 27.0.1,
CPython 3.12.12. Engines installed in `.venv`: `pokerkit==0.7.7`, `pypokerengine==1.0.1`.

## Measured, not assumed

Workload: 8-player NLHE, 2,000 stacks, blinds 10/20, random legal policy
(30% raise to a uniform legal size, 50% check/call, 20% fold), single process,
warm-up excluded. Probe scripts were kept outside the repo (`/tmp/pk_bench.py`,
`/tmp/ppe_bench.py`); the numbers below are what they printed.

| Engine | Hands/s | Decisions/s | Notes |
|---|---:|---:|---|
| PokerKit 0.7.7 | **149** | 2,188 | 2,000 hands in 13.4 s. `cProfile`: ~90% of time inside showdown hand lookup (`lookups._get_key`, `utilities.clean`, `are_suited`, `isinstance`): ~2,400 lookups per hand. |
| PyPokerEngine 1.0.1 | **216** | 6,611 | 200-hand game in 0.93 s with a call-heavy policy. (A naive run reported 19k hands/s because the table busted after 6 hands; that number was discarded.) |
| pokergym (this repo, after profiling) | **12,000–34,000** | 121k–300k | Median of 3, single core. See `docs/benchmarks.md`. Depends on the bot mix; the all-call mix is the worst case (8-way showdowns every hand). |

## Criteria

| Criterion | PokerKit | PyPokerEngine | pokergym |
|---|---|---|---|
| Correctness | High (reference-grade state machine; used here as an oracle) | Known side-pot/min-raise rough edges; Python-2-era code | Proven by tests + 800-hand parity with PokerKit (`tests/test_differential_pokerkit.py`) |
| Variant extensibility | Hand classes and lookups are deeply typed; a custom ranking means subclassing `Lookup`/`Hand`; betting structure fixed per game class | Minimal; no hook for ranking or raise rules | `HandRanking` (category permutation) and `BettingRules` are data; two mutations shipped |
| Eight-player support | Yes | Yes | Yes |
| Side pots / showdown | Yes | Yes (less trusted) | Yes; layered pots merged by eligibility, odd chip left of button |
| Python compatibility | 3.11+ | 2.7/3.x, unmaintained | 3.11+ |
| Determinism | Yes with explicit dealing | Uses global `random` | Yes: one `random.Random(seed)`; per-seat bot seeds; sha256 record hash |
| Throughput | 149 hands/s | 216 hands/s | 12k–34k hands/s single core; 59k–230k on 8 workers |
| Integration complexity | Medium (automation flags, explicit dealing API) | Low but inflexible callback interface | Owned; ~700 lines for engine+rules+agent |

## Decision

A demonstrated requirement fails for both candidates: one scored round is
10,000 tables × ~140–200 hands ≈ 1.4–2.0 M hands. At 149–216 hands/s that is
2–4 hours of single-core time per round, which makes variant rehearsal and
bot comparison impractical. The PokerKit cost is in its core hand-lookup
design (also the place where hand-ranking variants would have to be
implemented), so it is not removable by integration changes.

So the repo contains the smallest purpose-built engine that meets the
requirement, and keeps PokerKit as an **independent oracle**:

- `tests/test_evaluator.py::test_differential_against_pokerkit` — 4,000 random
  7-card pairs, ordering must agree (0 mismatches; 20,000 in the exploratory run).
- `tests/test_differential_pokerkit.py` — 800 randomized hands (2–8 players,
  random stacks, shared decision stream) must produce identical final stacks
  and identical decision counts. One known divergence is documented in
  `docs/fidelity.md` (short all-in opening bet after checks).
- Exhaustive 5-card category frequencies match the known distribution
  (1,302,540 / 1,098,240 / 123,552 / 54,912 / 10,200 / 5,108 / 3,744 / 624 / 40).

PokerKit's published benchmark numbers were not used; only the local run above.
