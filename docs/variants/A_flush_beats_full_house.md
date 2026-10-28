# Variant A — hand-ranking mutation: flush beats full house

Rules object: `pokergym.variants.VARIANT_A_FLUSH_BEATS_FULL_HOUSE` (`--variant flush-beats-full-house`).

## Rule

Standard no-limit Texas Hold'em, except that the hand categories rank, from
strongest to weakest:

straight flush > four of a kind > **flush** > **full house** > straight > three of a kind > two pair > pair > high card.

Ties within a category break exactly as in standard poker. Nothing else
changes: deck, dealing, blinds, betting, side pots, ICM, scoring.

## Implementation

`HandRanking.strength` is a permutation of the nine canonical category ids.
The evaluator detects categories once and maps each through the permutation;
when a 7-card hand contains several categories it returns the best one *under
the configured order*. For this mutation the two swapped categories cannot
co-occur in seven cards, so detection is unaffected.

## Verified behaviour

- `tests/test_evaluator.py::test_custom_ranking_reorders_categories` — direct comparison; also an overlapping-category case (trips vs straight) to show the order-aware selection.
- `tests/test_engine.py::test_flush_beats_full_house_only_under_variant` — scripted showdown: seat 3's full house wins under baseline, seat 2's flush wins under the variant, same cards and actions.
- `tests/test_variants.py::test_variant_a_diverges_only_at_flush_vs_full_house_showdowns` — over 120 seeded tournaments, every divergence from the baseline record begins at a hand whose showdown contains both a flush and a full house, and the full house never wins there.
- Unchanged invariants: `check_tournament` (cards, chips, rotation, blinds, termination, points) passes for all variant tournaments.
- Full eight-player tournaments: `tests/test_tournament.py::test_variants_run_full_tournaments`.

## Reproducible replay

```
python -m pokergym.cli run --seed 21 --variant flush-beats-full-house --verify --out docs/replays/flush-beats-full-house_seed21.json
python -m pokergym.cli replay docs/replays/flush-beats-full-house_seed21.json
```

Seed 21, hand 0, board `Qs 4c Td 4d 3d`: seat 0 (`4h 3h`, full house) wins the
10,010 pot under baseline; seat 5 (`8d Jd`, flush) wins it under the variant.
Record hashes: baseline `3b5cf3bb…`, variant `e3895fd6…` (full values in the JSON files).
