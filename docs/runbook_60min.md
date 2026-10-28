# Tournament-day runbook (60 minutes)

The organizer hands out a starter kit and announces the rule variant. The
plan: a legal bot is submitted within 25 minutes, a tuned bot before the
clock runs out, and nothing is submitted untested. Times are from the kit
drop. Practice the whole thing at least twice with `drills/fake_kit`.

Known facts (rules v1, `docs/spec/official_rules_v1.md`): 8 players per
table, 200-hand sit-and-go, 1,000 ms per decision with a check-else-fold
fallback, 100 MB submission limit. Everything else about the kit is unknown.

## 0–10 min: read, do not type

- [ ] Rule variant: what changed? Fill the **variant checklist** below.
- [ ] Kit interface: method names, what we receive, what we return.
      Find the five things that always differ (see `drills/fake_kit/README.md`):
      card spelling, raise-to vs raise-by, stack includes bets or not,
      how folded/out players appear, whether the history has streets.
- [ ] Deadline and fallback: is it still 1,000 ms / check-else-fold?
- [ ] Submission mechanics: single file? directory? entry point name?
      Is there a local checker in the kit? Run it on the kit's own template first.
- [ ] Payouts, blind schedule, starting stack: copy the real numbers into
      a `GameRules` (`pokergym/rules.py`) and mark the synthetic ones replaced.

## 10–25 min: wire and submit a safe bot

- [ ] `cp drills/fake_kit/adapter_template.py adapter.py`; fill `to_observation`,
      `to_text`, `new_table` for the real kit. `pokergym.bridge.build_observation`
      derives pot/to-call/raise bounds from plain values; pass `min_raise_to`
      /`max_raise_to` explicitly when the kit supplies them.
- [ ] If the variant changed the hand ranking: build the `HandRanking` and
      call `bot.configure(rules)` in `new_table` (all sparring bots support it).
- [ ] Bundle: `python scripts/bundle.py --bot adapter.py:Adapted --out submission/bot.py`.
      It inlines everything, embeds the equity table, and smoke-tests the
      bundle against the sparring roster (0 illegal, 0 errors, or it exits 1).
- [ ] Run the kit's own local checker on `submission/bot.py`, if there is one.
- [ ] **Submit `tag` wrapped by the adapter.** It is a known-legal, mid-ladder bot.
      A legal bot on the server beats a brilliant one on the laptop.

## 25–50 min: tune in the gym

- [ ] Pick the variant: `--variant` if it already exists, else add it to
      `pokergym/variants.py` (ranking, limit, antes, blinds, payouts) and run
      `python -m pytest -q tests/test_variants.py tests/test_variant_bots.py`.
- [ ] Baseline: `python -m pokergym.cli ladder --variant X --tables 500 --workers 8`
      to see which sparring style the variant rewards.
- [ ] Candidate: edit `examples/my_bot.py` (or pick the best sparring bot and
      adjust its `Profile`). Evaluate **paired**:
      `python -m pokergym.cli eval --bot my_bot.py:MyBot --vs sparring --variant X --tables 1000 --workers 8 --baseline tag`.
      Promote only if the paired diff's 95% CI excludes zero.
- [ ] Every 5 minutes: if the candidate is ahead, rebundle, run the kit
      checker, resubmit. Never skip the smoke test.

## 50–60 min: freeze

- [ ] Final bundle, final smoke test, final kit checker, submit.
- [ ] Confirm the server shows the latest upload (file size matches `bundle.py` output).
- [ ] Stop. No edits after the last submission you can verify.

## Variant checklist

For each line, note what the organizer said and which knob in `pokergym` it maps to.

| Possible change | Where it lives | Bot impact | Done |
|---|---|---|---|
| Hand ranking order (e.g. flush > full house) | `HandRanking.strength` in `rules.py`; `variants.py` | `bot.configure(rules)` swaps the evaluator; `hand_features` follows | [ ] |
| Betting limit (pot-limit, fixed cap) | `BettingRules.limit`, `max_raise_to` from kit | pass the kit's bounds into `build_observation`; sparring bots clamp | [ ] |
| Antes / big-blind ante | `BlindSchedule.ante_for_hand`; `Observation.ante` | pot odds shift; `pot` must include antes (pass `pot=` explicitly) | [ ] |
| Blind schedule / stack size | `BlindSchedule.levels`, `GameRules.starting_stack` | `push_width` keyed on effective BB; nothing to change in code | [ ] |
| Payout table | `PayoutSchedule.points` | `IcmBot` reads `rules.payouts`; pass the real one | [ ] |
| Short deck (no 2–5) | `cards.py` deck; evaluator category strength (flush > full house, A-6-7-8-9 straight) | equity table is **wrong**; disable `preflop_equity` use or regenerate with `scripts/gen_preflop_equity.py` | [ ] |
| Extra hole cards (Omaha-like) | engine `hole_cards` count; evaluator must enforce 2-from-hand | `hand_features` assumes 2 cards; fall back to `heuristic`/`call` unless time allows | [ ] |
| Visible information (no history, no stacks) | `build_observation` defaults | tracker degrades gracefully; `AdaptiveBot` becomes `TagBot` | [ ] |
| Decision deadline tighter than 1,000 ms | `AgentAdapter.deadline_ms` | all bots are < 1 ms p99 natively; check bundle import time | [ ] |
| Table size ≠ 8 | `num_players` everywhere | `Position` buckets scale; ICM subset DP is fine to 10 | [ ] |

If a change does not fit any row, submit the safe bot first and treat the
change as "unknown #N" in `docs/fidelity.md` style: write down what you
assumed before you code around it.
