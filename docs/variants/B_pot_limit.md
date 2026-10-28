# Variant B — betting-rule mutation: pot-limit raises

Rules object: `pokergym.variants.VARIANT_B_POT_LIMIT` (`--variant pot-limit`).

## Rule

Texas Hold'em with standard hand rankings, but the maximum bet or raise is
bounded by the pot:

```
max_raise_to = current_bet + to_call + pot
```

where `pot` is every chip committed so far in the hand (all streets,
including live bets) and `to_call` is what the acting player must put in to
call. Equivalently: call, then raise by the size of the pot after the call.
The minimum raise is unchanged (at least the last full raise, at least one big
blind). All-in for less than the minimum is still allowed. With blinds 10/20
and no ante the first preflop raise is capped at 70 (3.5 big blinds); after a
pot-sized open the next raise is capped at 240.

## Implementation

`BettingRules.limit = "pot_limit"`. The engine clamps `max_raise_to` with the
formula above before building the `Observation`; everything else is shared
with no-limit.

## Verified behaviour

- `tests/test_engine.py::test_pot_limit_max_raise` — scripted: UTG sees `(min 40, max 70)`, next player `(min 120, max 240)`; the same spot under no-limit shows max 2000.
- `tests/test_engine.py::test_betting_legality_random_play[pot_limit]` — 300 random hands with a probe agent asserting `max_raise_to <= current_bet + to_call + pot` at every decision.
- `tests/test_variants.py::test_variant_b_bounds_opening_raise_to_pot` — in 30 full tournaments every opening raise is ≤ 3.5 BB; the no-limit baseline produces larger opens.
- Unchanged invariants: `check_tournament` passes; baseline tests for min raise, side pots, rotation, ICM are unaffected.
- Full eight-player tournaments: `tests/test_tournament.py::test_variants_run_full_tournaments`.

## Reproducible replay

```
python -m pokergym.cli run --seed 2026 --variant pot-limit --verify --out docs/replays/pot-limit_seed2026.json
python -m pokergym.cli replay docs/replays/pot-limit_seed2026.json
```

Record hash `89918ad5…` (186 hands; the baseline at the same seed plays 200 hands and ends in ICM).
