# Drill: wire our bot into a kit we have never seen

On tournament day the organizers hand out a starter kit with their own bot
interface. Everything we built (the strategy, the evaluator, the equity
tables, the ICM code) is portable. The only new code is a thin adapter, and
it must be correct within minutes. This drill rehearses exactly that.

`fakekit.py` is a **made-up** kit. Its method names, dict keys, card
spelling, action vocabulary and raise semantics are all different from ours
on purpose, and all of it is invented. It is not the official interface; see
`docs/fidelity.md` for what we actually know.

## The drill (target: 15 minutes to PASS)

1. Start a timer.
2. Read the interface docstring at the top of `fakekit.py`. Do not read
   `reference_adapter.py`.
3. `cp drills/fake_kit/adapter_template.py drills/fake_kit/my_adapter.py` and
   fill in the three TODOs. `pokergym.bridge.build_observation` derives
   pot / to-call / raise bounds from plain values, so most of the work is
   renaming keys and fixing units.
4. `python drills/fake_kit/run_drill.py my_adapter.py:Adapted`

   ```
   legality : 0 errors in 4287 decisions over 4 tables
   parity   : 0 mismatches in 323 compared decisions
   overhead : 21 us per decision
   RESULT   : PASS
   ```

5. Stop the timer. Record the time and anything that cost you minutes in
   `drills/fake_kit/LOG.md` (your own notes; the file is gitignored).

The three checks:

- **legality**: the fake kit treats an exception or unparseable reply as the
  organizer's rule 3.7 (check, else fold). Zero tolerated.
- **parity**: your adapter hosting `TagBot` must make the same decisions as
  `TagBot` run natively on the same seeds. A mismatch means a field is
  mistranslated (common: raise-by vs raise-to, `paid` vs `wager`, a player
  marked folded when they are out, uppercase suits).
- **overhead**: translation cost per decision. Our budget is 1,000 ms per
  rule 3.7; tens of microseconds is where it should sit.

## Traps built into this fake kit (and what the real one might do instead)

| Fake kit | Our model | Likely real-kit variants to expect |
|---|---|---|
| `RAISE <by>` is on top of the call | `raise_to(total)` | raise-to, raise-by, or "amount to add to pot" |
| cards `"AS"`, `"TD"` | `"As"`, `"Td"` or ints 0..51 | `"10h"`, suits as symbols, or (rank, suit) tuples |
| `pot` includes current street bets | `pot` = all committed | pot excluding live bets; side pots listed separately |
| `players[i].status` in `{active, folded, allin, out}` | `in_hand`, `all_in`, stack+committed>0 | booleans, or absence from the list |
| `chips` = behind; `wager` = this street; `paid` = this hand | `stacks`, `bets`, `committed` | stack including bets; no per-hand total |
| `log` of dicts with a street | `(street, seat, kind, amount)` | strings, no street, or per-street lists |
| `new_hand(hand)` carries cards and dealer | both are in every `Observation` | cards only in the first state of the hand |
| `rng_seed` in config | `TableInfo.seed` | none, so seed from `seat_id` + time |

## Answer key

`reference_adapter.py` passes the drill. Read it after your attempt and diff
it against yours.

## Making a new drill

Edit `fakekit.py`: change key names, invert the raise semantics, drop the
`committed` field, put cards into `state` instead of `hand`. The runner does
not care, as long as `play_table` still returns the engine's result. A drill
partner can do this for you so the interface is genuinely unseen.
