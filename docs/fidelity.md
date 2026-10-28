# Competition fidelity assessment and remaining unknowns

This file lists every place where `pokerlab` differs from, assumes beyond, or
cannot yet verify against confirmed organizer behaviour. Update it when the
starter kit arrives.

## Implemented exactly as confirmed (rules v1)

| Organizer rule | pokerlab | Where |
|---|---|---|
| 8 bots per table, 2,000 chips, 10/20 start, +level every 25 hands, 200-hand cap | Yes | `rules.GameRules`, `tournament.run_tournament` |
| Table ends when one bot has all chips or 200 hands | Yes | `run_tournament` loop; `checks.check_termination` |
| Points by finishing position; eliminated bots get their position's points | Yes | `tournament.assign_finishes` |
| Survivors at hand cap share remaining points by ICM | Yes (Malmuth–Harville) | `icm.icm_equities`; brute-force cross-check in tests |
| 10,000 tables per scored round, random seating, average points per table | Yes (`run_round`) | `tournament.run_round` |
| Fillers when bots are not divisible by 8; fillers earn no points | Yes | `run_round` |
| Final score T1×1 … T6×6 | Yes | `tournament.final_score` |
| 1 ms decision deadline; on error/timeout fold-or-check | Yes (wall-clock `perf_counter_ns`; cannot interrupt the bot) | `agent.AgentAdapter` |
| Bot state resets per table | Yes (`Agent.reset(TableInfo)` once per tournament) | `run_tournament` |
| Opponents anonymized | Yes (seats only; no identities in `Observation`) | `agent.Observation` |

## Synthetic (must be replaced by starter-kit values)

- **Payout schedule**: `(100, 60, 40, 25, 15, 10, 5, 0)` — `rules.SYNTHETIC_PAYOUTS`.
- **Blind schedule after level 1**: `(10,20) (15,30) (25,50) (50,100) (75,150) (100,200) (150,300) (200,400)`, no antes — `rules.SYNTHETIC_BLIND_SCHEDULE`.
- **Baseline game**: standard NLHE is the reference game only; it is not a guess at the secret variant.

## Assumptions where the organizer is silent (each is a one-line config or a documented engine rule)

| Topic | pokerlab behaviour | Risk if different |
|---|---|---|
| Initial button | Random seat drawn from the tournament seed (`button_start` overrides) | Low: positional fairness only |
| Button movement | Moves to the next seat with chips; SB/BB are the next two live seats; heads-up button posts SB and acts first preflop | Low–medium: dead-button rules change who posts after a bust |
| Same-hand eliminations | Larger starting stack places higher; equal stacks tie and split the points of the spanned positions | Low: affects a few points per multi-bust hand |
| Odd chips in split pots | To the first winner clockwise from the button | Negligible |
| Short all-in raise | Does not reopen the action for players who already acted (TDA 43). PokerKit agrees for raises but **lets a player who checked re-raise after a short all-in opening bet**; pokerlab does not. Pinned by `test_short_all_in_opening_bet_does_not_reopen_for_checkers`. | Low: rare spot |
| BB all-in for less than the big blind | The full big blind is still the amount to call / minimum bet | Low |
| Minimum raise | At least the last full raise, at least one big blind; an all-in below that is allowed and is not a "full" raise | Medium if the kit expresses raises differently (raise-by vs raise-to) |
| Illegal action from a bot | Treated like an error: fold, or check if available; counted in `agent_stats["illegal"]` | Medium: the kit may reject, clamp, or penalize differently |
| Raise amount encoding | `Action(RAISE, amount)` is the total bet-to for the street | High for the adapter: must be translated to the kit's encoding |
| Deadline measurement | Wall clock around `act()`, measured in-process; the bot's own imports and `reset()` are not timed; the call cannot be interrupted | Medium: the kit may time differently or run on slower hardware |
| Card burning | None; dealing is a uniform ordered draw of exactly the cards needed | None for outcome distributions |
| Showdown information | All hole cards of non-folded players are in the hand record; `Observation` never exposes opponents' cards | Low |
| ICM | Malmuth–Harville over survivors for positions 1..k; result is floating point | Low; the kit ships its own calculator which we should call instead |

## Cross-checks performed

- Hand evaluator: exhaustive 5-card frequency table; 20,000 (exploratory) + 4,000 (test) random 7-card pair orderings against PokerKit, 0 mismatches.
- Betting + side pots + showdown: 800 randomized 2–8 player hands replayed through PokerKit with identical cards and decision streams; identical final stacks and decision counts (`tests/test_differential_pokerkit.py`).
- ICM: recursion vs brute-force enumeration of all finishing orders for n = 2..6, random stacks and payouts; hand-computed 3-player example.
- Invariants on every recorded hand: card uniqueness/conservation, no cards to busted seats, chip conservation, net-zero transfers, button/blind rotation, blind schedule, termination, point conservation (sum of points == sum of payouts in every tournament).
- Fault injection: 15 deliberately broken cases (duplicate card, card dealt to a busted seat, chip leak, non-zero net, frozen button, swapped blinds, wrong blind level, point leak, missing ICM, over-cap hands, no-flush evaluator, chip-chop ICM, tie-everything evaluator in the side-pot scenario, tampered record, engine mutation that never moves the button) are all detected.

## Open unknowns (cannot be resolved before the build phase)

1. The variant itself (3.2). Our `GameRules` currently supports: category re-ranking, pot/no-limit, raise caps, antes, hole-card count, board street sizes. Not yet supported: non-standard deck sizes (short deck), wild cards, lowball/split-pot evaluation, draw streets, multiple boards. These are the next extensibility risks to rehearse.
2. Agent interface and observation contents (3.3). Our `Observation` is a superset of what most simulators give; the adapter in `pokerlab/adapters.py` is the seam.
3. Payouts and blind schedule (3.3, 4.5).
4. Deadline semantics and the hardware the sandbox runs on (3.7).
5. Whether the kit's "local simulator" exposes seeds/decks so that hand-level parity can be checked, or only aggregate results.
6. How tables are formed when the number of entrants is large (random assignment per iteration is confirmed; seat order within a table is not).

## Parity plan for the starter kit (Step 7)

1. Wrap the kit's agent template with `adapters.OfficialAgentShim` so the three fixture bots run unchanged inside the kit's simulator.
2. Build `GameRules` from the kit's payout/blind files; set the real variant.
3. Run the three bots in both simulators with the same seating; compare per-position point distributions over N tables (aggregate parity). If the kit exposes decks, compare hand records directly (exact parity).
4. Record each confirmed difference in the table above and change the engine default, not the bots.
