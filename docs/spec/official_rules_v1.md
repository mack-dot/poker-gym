# Official rules — local specification v1

- Source: https://pokerbot.sequoiacap.com/rules.html
- Retrieved: 2026-10-28 02:09 UTC-4
- Raw copy: `docs/spec/rules_2026-10-28.html` (sha256 `92f966770875d757098e88e459e104bcb978a7deec42b1f647fd0d83e0bca7bf`)
- Spec version: v1 (first retrieval). Bump the version and keep old copies when the page changes.

## Confirmed competition constraints (with rule section)

| Constraint | Value | Section |
|---|---|---|
| Bot language / interface | Python, "the provided Agent interface" | 3.3 |
| Build window | 60 minutes | 3.3 |
| Starter kit contents | agent template, local simulator, ICM calculator, payout structure, blind schedule | 3.3 |
| Variant | Secret, revealed at the start of the build phase | 3.2 |
| Submission cadence | One bot every five minutes; latest accepted = active bot | 3.5 |
| Sandbox | No network, no external APIs/AI tools during gameplay | 3.6, 7.1 |
| Decision deadline | 1 millisecond per decision | 3.7 |
| Submission size | 100 MB max | 3.7 |
| Error/timeout fallback | Bot folds, or checks if checking is available | 3.7 |
| State | Bot state resets at the start of each table | 3.8 |
| Opponents | Anonymized | 3.8 |
| Scored tournaments | Six (T1–T6); T1 starts at end of build phase; 20 minutes apart | 4.1 |
| Freeze | Active bot frozen at each tournament start | 4.2 |
| Tournament size | 10,000 simulated eight-bot sit-and-gos; random table assignment | 4.3 |
| Table end | One bot has all chips, or 200 hands | 4.4 |
| Starting stack | 2,000 chips | 4.4 |
| Blinds | Start 10/20, increase every 25 hands | 4.4 |
| Points | By finishing position; distribution may vary by variant; announced at build start | 4.5 |
| Hand cap | Remaining points allocated among survivors by ICM | 4.5 |
| Filler bots | Random copies fill seats when bot count is not divisible by 8; fillers earn no points | 4.6 |
| Round score | Average points per table over 10,000 iterations | 4.7 |
| Final score | T1×1 + T2×2 + T3×3 + T4×4 + T5×5 + T6×6 | 4.7 |
| Ties | Tie-breaker challenge decided by Organizer | 4.8 |
| Hand logs | Retained for dispute resolution | 6.3 |

## Not specified by the rules page (kept configurable, defaults labelled SYNTHETIC)

- The poker variant itself.
- The point distribution by finishing position (`rules.PayoutSchedule`, default `SYNTHETIC_PAYOUTS`).
- Blind amounts after the first level (`rules.BlindSchedule`, default `SYNTHETIC_BLIND_SCHEDULE`); whether antes exist.
- The Agent interface: method names, observation fields, action encoding, how raise sizes are expressed.
- Timing semantics of the 1 ms deadline (wall vs CPU time; whether the first call / import time counts; machine speed).
- Dealer button placement at table start and the button-movement rule after eliminations.
- Ranking of players eliminated in the same hand; odd-chip rules for split pots.
- Whether a short all-in reopens the betting; whether the full big blind is the minimum bet when the BB is all-in for less.
- Whether the simulator burns cards (irrelevant to the distribution of outcomes if the deck is uniformly shuffled).
- The ICM calculator's exact algorithm (Malmuth–Harville assumed) and numerical precision.
- How an exception or illegal action is handled beyond "folds, or checks if checking is available".
- Whether an illegal action (as opposed to an error/timeout) is treated the same way.
