# Arena: the sealed competition rehearsal

`pokergym.arena` turns the gym into a timed exercise that copies the shape of
competition day: a variant you have not seen, a fresh workspace with only
what the organizer would give you, a real 60-minute clock, one submission
per five minutes, a validator that rejects broken bots, a hidden evaluation
against opponents you never play in practice, and a postmortem.

Everything in this document that is not in `docs/spec/official_rules_v1.md`
is a **REHEARSAL** choice. Payouts and blind schedules are **synthetic**.

## One-minute tour

```
python -m pokergym.arena smoke                 # bounded end-to-end run (~90 s, stand-in competitor, no AI)
python -m pokergym.arena rehearse ~/arena/r1 --seed 7      # THE real 60-minute exercise (you press Enter to start)
```

`rehearse` creates the challenge, waits for you to press Enter, starts the
clock, reveals the variant into the workspace, serves submissions until
minute 60, then grades and writes the postmortem. Nothing in it plays for
you and nothing calls an AI. If you want an AI assistant in the loop, you
open it yourself in the competitor shell; the harness does not start one.

Split form (same thing, separate terminals):

```
python -m pokergym.arena create ~/arena/r1 --seed 7       # sealed: variant chosen, committed, not revealed
python -m pokergym.arena serve  ~/arena/r1                # host loop (terminal 1)
python -m pokergym.arena start  ~/arena/r1                # clock starts, BRIEFING.md appears (terminal 2)
python -m pokergym.arena status ~/arena/r1
python -m pokergym.arena grade  ~/arena/r1 --tables 2000 --workers 8 --all-accepted
python -m pokergym.arena postmortem ~/arena/r1
```

Competitor side, inside `~/arena/r1/workspace`, run under the sandbox:

```
SB=$(python -m pokergym.arena sandbox-profile ~/arena/r1)      # writes workspace/.sandbox.sb
PY=$(python -c 'import pokergym.arena.isolation as i; print(i.competitor_python())')
alias cpy="sandbox-exec -f $SB $PY -I -S"
cpy run_local.py my_agent.py --tables 50 --vs heuristic          # local games, latency, legality
cpy submit.py my_agent.py --check                                # free validation, no slot used
cpy submit.py my_agent.py --note "hypothesis ..."                # log a hypothesis
cpy submit.py my_agent.py                                        # uses the 5-minute slot
```

## Layout of a challenge directory

```
ROOT/
  challenge.json    public: commitment hash, clock, validation config, isolation self-test, status
  state.json        host state: start/freeze times, submissions, active index, milestones, notes
  events.jsonl      append-only replayable record of everything that happened (with elapsed seconds)
  workspace/        the ONLY thing the competitor sees (sandbox allow-list)
    kit/            copied simulator modules (cards, evaluator, rules, agent, engine, tournament, icm, checks, heuristic)
    my_agent.py     template: Agent.reset/act returning the kit's Action; check-else-fold
    run_local.py    local simulator, legality + latency report, --vs heuristic|call|random|self, --research
    submit.py       --check | --note | submit; talks to the host through ../inbox only
    README.md       the kit docs
    status.json     host-written: elapsed, next slot, active submission
    (after start) variant.json, BRIEFING.md, payouts.json, blinds.json, examples/observations.json
  inbox/            request/response files (competitor can write here; nothing else outside workspace)
  staging/          host copy of a submission for the sandboxed validator (host only)
  submissions/      immutable, read-only, sha256-named copies of every check/submit (host only)
  hidden/secret.json  the mutation, salt, hidden seeds (host only)
  results/          hidden_eval.json, per_submission.json, postmortem.md
```

## 1. Sealed challenge generator (`arena/mutations.py`)

A `Mutation` changes exactly one rule of the baseline game and carries:
machine-readable `rules` (`rules_to_dict` round trip), a `headline`, the
assumptions it invalidates, a legal-action definition, an independent
`check(result, rules)` that does not use the engine's evaluator (naive
5-of-7 enumeration in `arena/independent_eval.py`), a strategic `signal`,
and an adapted and a rule-naive reference bot.

Reserve (17 entries, 6 families): hand-ranking swaps (4), raise caps (2),
antes (2), turbo blinds (2), payouts (4), board dealing patterns (3).
`generate(seed, family=None)` picks one deterministically. The two variants
already published in `pokergym/variants.py` are excluded by test.

Each mutation passed, in `tests/test_arena_mutations.py`: executes under all
engine invariants; passes its independent check; shifts its strategic signal
versus the baseline game on the same seeds (z > 3 or a pooled count with
zero in the baseline); serialises and regenerates identically; and its
briefing carries the REHEARSAL/synthetic labels.

Swaps that were measured and dropped because they are almost never decisive
with a heuristic roster: straight>flush (0.06 showdowns/table), straight>full
house (0.08), quads>straight flush, flush>quads (~0), raise cap 3 (rarely
binding), board 3+2 (no observable change for the agent).

Sealing: `challenge.json.commitment = sha256(json(mutation) + salt)`; the
salt and the mutation live in `hidden/secret.json`; `verify_commitment()` is
checked at grading. Hidden seeds are `sha256(salt:purpose)[:8]`.

Unsupported mutation types (would need engine work, not just rules): wild
cards, hole-card counts other than two with different showdown rules,
split-pot/hi-lo, run-it-twice, bomb pots, position-dependent blinds, time
banks. The engine does support hole-card count changes
(`GameRules.hole_cards`) but no reserve entry uses it because the sparring
bots' preflop tables are two-card tables.

## 2. Isolated workspace (`arena/workspace.py`, `arena/isolation.py`)

Isolation is enforced, not promised, with macOS `sandbox-exec`:

```
(version 1)(allow default)(deny network*)
(deny file-read* file-write* (subpath "<repo realpath>"))
(deny file-read* file-write* (subpath "ROOT/hidden")) ... ROOT/submissions, ROOT/staging, ROOT/results
(allow file-read* file-write* (subpath "ROOT/workspace")) (subpath "ROOT/inbox")
```

The competitor interpreter is the real path of `sys.executable` run with
`-I -S` (no site-packages, no `PYTHONPATH`, no user site). At `create`, the
host runs `isolation.self_test` from inside the sandbox and records in
`challenge.json` that `pokergym/bots/sparring.py`, `hidden/`, and
`submissions/` are unreadable, `import pokergym` fails, the network is
closed, and the workspace is readable. `tests/test_arena_lifecycle.py` also
submits a bot that tries to read the repo and asserts it is rejected.

If `sandbox-exec` is missing (Linux), `isolation.level()` returns `"weak"`:
the interpreter flags still apply but filesystem denial is not enforced.
The challenge records this and the postmortem prints it.

The kit's `heuristic.py` is the research `HeuristicBot` with its imports
rewritten and an `evaluator` attribute so it can be pointed at the variant's
ranking. It is the strongest thing a competitor can copy; it is not a
sparring bot and no sparring/hidden-opponent code is in the kit.

## 3. Clock and submissions (`arena/session.py`)

- `start()` reveals the variant and sets `freeze_at = start + duration_s`.
  It refuses to run twice.
- Every public operation calls `tick()`, which freezes the challenge when
  the wall clock passes `freeze_at`. `serve()` also freezes on time with no
  request pending.
- `submit()` is rejected before start, after freeze, and when fewer than
  `cadence_s` seconds have passed since the last *validated* submission
  (accepted or rejected: a submission that reaches the validator uses the
  slot; this is a REHEARSAL choice because the official rule does not say).
- `check()` never uses a slot and never becomes active; milestones still
  count.
- Every check/submit is copied read-only into `submissions/` with its
  sha256; the validator runs on a staging copy inside the sandbox.
- The latest accepted submission is active; `rollback(index)` restores an
  earlier accepted one (host action, logged).
- Milestones recorded with elapsed seconds: `first_executable_bot` (import
  passed), `first_legal_decision` (legality passed), `first_completed_game`
  (games passed), `first_accepted_submission`, `first_competitive_policy`
  (accepted and edge over the check/fold bot >= 5 points/table on the
  validator's seeds), `final_verified_submission` (at freeze).
- No fictitious durations: times are `time.time()` at the moment of the
  event; the window for the real exercise is 3600 s. Any other clock is
  stamped `NON-STANDARD CLOCK` in `challenge.json` and the postmortem.

Inbox protocol: `submit.py` writes `inbox/<id>.py` + `<id>.req.json`; the
serving host validates and writes `<id>.result.json`; `submit.py` prints
the report. The competitor process never imports host code.

## 4. Validator (`arena/validator.py`, `kit/validate_runner.py`)

Stages, in order; the first failure stops the run:

| stage | what | threshold |
|---|---|---|
| size | file size | 100 MB (rule 3.7) |
| import | module import inside the sandbox | wall timeout 180 s (host kills the process) |
| interface | `Agent` or `BOT_CLASS` present, `reset(table)` works | - |
| legality | replay 400 recorded observations (fewer in board variants) through `act()`; every action must be legal | 0 illegal, 0 exceptions |
| games | N tournaments in **enforce** mode (1 ms deadline, check/fold fallback) and N in record mode on the same seeds, plus the check/fold bot on the same seeds; `check_tournament` invariants | all invariants |
| errors | exceptions and watchdog kills during games, illegal actions during games | 0 |
| timing | share of decisions over 1 ms; startup time | <= 2 % (REHEARSAL), <= 10 s |

The watchdog is `SIGALRM` at `hard_ms` (200 ms) inside the runner: a hung
`act()` raises `HardTimeout`, is counted as an exception, and the validator
finishes instead of hanging. A hang in C code that does not return to the
interpreter, or a hang at import, is caught by the host's wall timeout and
reported as `hung`. The validator cannot pre-empt at exactly 1 ms; it
measures wall-clock around `act()` with `perf_counter`, as the gym does. No
claim of official timing parity is made.

Metrics saved per submission: decisions, illegal, errors, timeouts,
timeout_frac, points in enforce vs record mode, `fallback_effect_points`,
`points_fold_baseline`, `edge_over_fold_bot`, latency p50/p99/max, startup ms.

## 5. Hidden evaluation (`arena/hidden_eval.py`, `arena/hidden_opponents.py`)

Opponents are seven archetypes the gym's `sparring` lineup does not contain
(`nit`, `maniac`, `station`, `rock`, `trapper`, `shark`, `pusher`), all with
`configure(rules)` so they adopt the variant's ranking and payouts. Seeds
come from the hidden salt. Three paired runs:

1. candidate vs hidden lineup under the **variant** (the score), paired with
   the mutation's adapted reference in the same seats;
2. candidate vs hidden lineup under **standard** hold'em (general strength
   diagnostic), same pairing;
3. the **rule-naive** reference under the variant, same pairing: the price
   of ignoring the rule.

Output: points/table with 95 % CI, finish distribution, win and top-4
rates, per-archetype finished-above rate and point difference, busts and
survival per blind level, violations (illegal, errors, timeouts, decisions),
and two verdicts:

- `strength`: candidate minus adapted reference in the standard game, CI
  excludes zero -> stronger/weaker, else "about the reference's strength".
- `adaptation`: if adapted minus naive reference under the variant is not
  significant, "not separable" (the references cannot price the rule); else
  compare the candidate's variant-minus-standard change with the
  reference's.

Deadline mode in grading is **record**, not enforce: enforce would make the
score depend on host load (a slow opponent decision also changes the hand),
so the hidden score would not be reproducible. Over-deadline decisions are
reported as violations; the validator's competition-mode run is where
fallbacks are exercised. `reproducible_from_seed` is *verified*: the first
20 tables are replayed and compared row by row.

## 6. Postmortem (`arena/postmortem.py`)

Sections: rule changed and invalidated assumptions; timeline with every
milestone; submission table (sha, result, failed stages, edge vs check/fold
bot, p99 latency, line diff vs the previous one, hidden score when graded
with `--all-accepted`); hypotheses (`--note`); time allocation from event
gaps (implementing/debugging/testing/optimizing/idle); final hidden score;
failure classification A-F; missed opportunities; recommendations.

Failure classes (heuristic): A misread rules (recognition late / not
acting), B implementing the rules incorrectly (legality failures), C weak
strategy (below the naive reference), D poor experimental design (slots
burnt without free checks), E runtime violations (import/errors/timing
failures or hidden-eval violations), F wasting development time (long
silences, unused minutes before freeze).

## 7. Six-round exercise

Not built. The interfaces are enough: a round is a `Challenge` directory;
`grade --all-accepted` writes `per_submission.json`; a six-round driver
would create six challenges with different seeds and weights 1..6 and sum
`results/hidden_eval.json` scores. Do that only after several single rounds
have shown the single-round loop is worth repeating.

## 8. Measured runtime (`benchmarks/results/arena.json`)

Apple M1 Pro, Python 3.12, **load average 24 from other sessions** (every
figure here is pessimistic; the earlier quiet-machine throughput is in
`docs/benchmarks.md`).

| measurement | value |
|---|---|
| throughput, hidden lineup + heuristic, deadline off / record / enforce | 42.7 / 43.8 / 37.1 tournaments/s (single core) |
| decisions over 1 ms, record mode, 182k decisions | 205 (0.11 %) — load-induced, see caveat |
| `Observation.to_dict` + `json.dumps` + `json.loads` | 4.3 + 5.8 + 6.9 us, 602 bytes/observation |
| sandboxed interpreter start / kit import | 52 ms / 37 ms |
| template validation (6 tables x 2 modes + fold baseline, legality replay) | 0.42 s |
| hidden evaluation 100 tables, workers 1/4/8 | 12.8 / 5.6 / 3.5 s |
| hidden evaluation 1000 tables, workers 1/4/8 | 65 / 22 / 17 s |
| hidden evaluation 10000 tables, workers 4/8 | 187 / 124 s |
| reproducibility (same seed, workers 1 vs 4, 200 tables) | identical rows |

A full hidden evaluation runs ~3.2x the table count (variant + reference
paired, baseline game, naive reference, replay check), so 10,000 tables is
about 32,000 tournaments.

## 9. What works and what does not (honest list)

Works, demonstrated by tests and the smoke rehearsal:

- Sealed generation with a verifiable commitment; variant invisible before
  `start`.
- Enforced filesystem and network isolation (sandbox-exec), self-tested at
  create and tested by a hostile submission.
- Real wall clock, cadence rejections, no restart, freeze on time, immutable
  hashed submissions, rollback, milestones, append-only events.
- 7-stage validation including hung-bot termination, illegal and exception
  bots, size, timing, and competition-mode fallback exercise.
- Hidden evaluation that is reproducible from the seed, with archetype and
  blind-level breakdowns and violation counts.
- Postmortem with timeline, time allocation, A-F classes, recommendations.
- Bounded smoke rehearsal (`smoke`) with a stand-in competitor acting only
  through the sandboxed `submit.py`.

Limitations:

- **Adaptation is rarely separable.** For most mutations the adapted and
  rule-naive references score within noise of each other against the
  heuristic roster (ranking swaps: -1.1 +/- 1.7 points/table for the
  "adapted" bot; payouts WTA: +1.4 +/- 2.1). So the `adaptation` verdict
  usually says "not separable". The mechanical signal that the rule is in
  force is strong; its strategic *value* with these bots is small. Stronger
  references would be strategy research, which this brief excludes.
- The opponents are heuristic archetypes, not hidden *strong* bots. The
  check/fold template scores near par against them (survival to the ICM
  cap). The hidden score measures adaptation and robustness more than
  absolute strength.
- Timing: Python wall-clock sampling, SIGALRM at 200 ms, host wall timeout;
  no 1 ms pre-emption and no official harness parity. On this loaded
  machine even sparring bots show 0.1 % decisions over 1 ms.
- Isolation is macOS-only in its enforced form. The competitor can still
  read the whole repo *outside* the sandbox; honesty about not doing so is
  on the person rehearsing. Do not open `pokergym/arena/mutations.py` or
  run `reserve` before a rehearsal if you want the reserve concealed.
- The competitor interpreter uses `-I -S`: no third-party packages (the
  real kit may or may not allow numpy; unknown).
- Payouts, blind schedule, submission-slot semantics (rejected submissions
  use a slot), the 2 % timeout tolerance, and the watchdog value are
  REHEARSAL choices.
- The validator rejects a bot after the first failing stage; it does not
  run the later stages for diagnostics.
- No six-round orchestration, no AI-in-the-loop automation, no scoreboard.

## Bugs found while building this

- `Observation.to_dict()` raised on any non-empty history (it unpacked
  3-tuples; history entries are `(street, seat, kind, amount)`), and the
  `AgentAdapter` swallowed the exception, so the kit's example observations
  file contained one observation. Fixed in `pokergym/agent.py`.
- Evaluator kicker computation produced negative values for 4-card inputs
  (2-card boards in board variants) and crashed the sparring bots. Fixed.
- `SparringBot._compute_risk_premium` returned 0 always; rewritten as a
  doubling break-even premium.
- The hidden evaluation in enforce mode was not reproducible even with zero
  candidate timeouts: an opponent's slow decision also changes the hand.
  Grading now records instead of enforces, and verifies the replay.
