# The gym: practice and evaluation

The gym is the layer on top of the P0 simulator for working on a bot: a
loader for your own bot file, a roster of sparring partners that play
recognisable styles, a paired evaluation harness with confidence intervals,
a ladder, hand-history display, and the equity tables and feature helpers
the bots are built from.

Everything the organizer has not published (payouts, later blind levels, the
Agent interface) is still SYNTHETIC and every report prints that label.

## A practice session

```
# 1. start from the template
cp examples/my_bot.py my_bot.py            # edit act()/preflop()/postflop()

# 2. measure against the sparring roster, paired with a reference bot
python -m pokergym.cli eval --bot my_bot.py:MyBot --vs sparring --tables 2000 --workers 8 --baseline tag

# 3. look at hands you played
python -m pokergym.cli run --seed 5 --bots my_bot.py:MyBot,tag,lag,shortstack,icm,adaptive,tag,lag --out runs/s5.json
python -m pokergym.cli show runs/s5.json --seat 0 --hands 0-40

# 4. check a spot
python -m pokergym.cli equity AsKd --opponents 3
python -m pokergym.cli equity Th9h --board 8h7c2h --opponents 1 --range 0.2

# 5. confirm you are not slow (quiet machine, one worker)
python benchmarks/bench_latency.py --tournaments 100     # add your bot to MIX, or wrap the snippet in a script
```

### Reading an eval report

```
candidate: examples/my_bot.py:MyBot   rules: nlhe-baseline   tables: 2000   seed: 1   12.7s
lineup:    tag, lag, shortstack, icm, adaptive, tag, lag
points/table: 31.261  (95% CI 30.073 .. 32.449, se 0.606)
finish: mean 4.37   win 2.9%   top-4 54.0%   hand-cap tables 27.5%   hands/table 170.7
busted on hand 94.1 on average (when busted)
finish histogram (1..8): 1:100 2:430 3:258 4:292 5:283 6:215 7:210 8:212
decisions: 242031   >1ms: 274 (0.1132%)   errors: 0   illegal: 0
opponent points/seat: adaptive=32.52  icm=32.92  lag=28.76  shortstack=36.55  tag=32.11
vs baseline tag: 33.447 pts/table; paired diff -2.186 (95% CI -3.681 .. -0.691) -> worse
SYNTHETIC blinds: ...
SYNTHETIC payouts: ...
```

- `points/table` is the organizer's round score for one bot (rule 4.7 averages
  this over 10,000 tables). With the synthetic payouts, the table average is
  255/8 = 31.9, so a bot above that is taking points from the lineup.
- The paired `diff` is the number to watch between versions. The same table
  seeds, seats and opponents are replayed with the baseline in your seat; the
  deck sequence is identical until the first elimination changes how many
  cards are dealt, so most card luck cancels. 2,000 tables give a ±1.5 point
  95% CI on the difference; 10,000 tables give about ±0.7.
- `>1ms` counts calls over the deadline in `record` mode (nothing is replaced).
  Parallel workers on a loaded machine inflate this; see `docs/benchmarks.md`.
  `illegal` must be 0: an illegal action is replaced by the check/fold
  fallback, which is how the organizer treats errors (rule 3.7).
- `finish histogram` and `busted on hand` show the shape: a bot that wins 3%
  and finishes second 21% of the time is surviving but not closing.

### Lineups

| name | seats | purpose |
|---|---|---|
| `sparring` | tag, lag, shortstack, icm, adaptive, tag, lag | default; a mixed table of competent styles |
| `mixed` | tag, lag, shortstack, icm, adaptive, heuristic, random | one weak seat and one random seat, like a field with bad entries |
| `fixtures` | call, random, heuristic ×2 + random | sanity check only; everything should crush this |
| `tags`, `lags` | 7 copies | style-specific stress |
| any list | `--vs tag,tag,lag,my_other_bot.py:Bot,…` | fewer than 7 are filled by sampling; more than 7 are sampled per table |

## Sparring partners

Hand-built, table-driven, deterministic per seat seed. They are not solved
strategies and are not an optimizer; they are opponents that punish obvious
leaks (calling too wide, never folding, never raising, ignoring stack depth).

| name | style | what it punishes |
|---|---|---|
| `tag` | tight-aggressive: opens 11/16/27/30% by position, 3-bets ~4.5%, c-bets 65%, value-bets, folds weak pairs to pressure | limping, calling stations, bluffing into strength |
| `lag` | loose-aggressive: opens 20/27/42/42%, 3-bets 9%, c-bets 85%, bluffs more, bigger sizes | over-folding, playing fit-or-fold |
| `shortstack` | nit when deep; push/fold specialist below ~14 BB using `push_width` (rough Nash-shaped widths) | ignoring stack depth, calling shoves too wide |
| `icm` | `tag` plus an exact ICM risk premium with ≤5 players and extra caution in the last 40 hands | gambling on the bubble, ignoring the hand cap |
| `adaptive` | `tag` plus `OpponentTracker`: steals more vs blinds that fold, value-bets thinner vs stations, 3-bets wider vs loose openers | predictable play |

Ladder over 2,000 tables (seed 1, eight distinct bots, all eight seated every table):

```
rank bot            pts/table    95% CI
   1 shortstack       43.1     41.8..44.3
   2 tag              42.9     41.5..44.3
   3 icm              42.0     40.6..43.4
   4 lag              40.8     39.2..42.4
   5 adaptive         40.5     39.1..41.9
   6 heuristic        34.1     33.1..35.0
   7 random            7.5      6.9..8.1
   8 call              4.2      3.9..4.5
```

The five sparring styles are within each other's confidence intervals on a
mixed table; all of them are 6–9 points above the old heuristic fixture and
35+ points above the call and random fixtures.

Among themselves only (five bots, three filler copies that do not score), the
`shortstack` style wins (36.6 vs 28–33), which is a property of the synthetic
blind schedule: blinds reach 100/200 by hand 125 with 2,000-chip stacks, so
the table is a short-stack game for most of its life. When the organizer
publishes the real schedule, re-run the ladder; the ranking may change.

Known limits: the preflop model is "top X% by heads-up equity", not
position-specific ranges; postflop strength is a made-hand class plus outs,
not an equity calculation; the adaptive bot only sees actions that happen
before its own decisions (see `stats.py`), so its reads are biased towards
preflop behaviour. These are deliberate: they keep every decision under
~100 µs and leave room for a candidate bot to be clearly better.

## Equity tables

`pokergym/data/preflop_equity.json` (regenerate with
`python scripts/gen_preflop_equity.py --samples 50000 --seed 2026 --workers 8`,
~4 min):

- `equity[n-1][class]`: Monte Carlo equity (win share, ties split) of each of
  the 169 hand classes against `n` = 1..7 random hands, 50,000 samples per
  class (standard error ≈ 0.22 points; per-cell seeds are SHA-256 mixed, since
  a first version with consecutive integer seeds produced correlated low draws).
  Checked against known values: AA vs 1 = 0.852, AA vs 7 = 0.389, AKs vs 1 =
  0.670, 72o vs 1 = 0.347 (`tests/test_equity.py`).
- `vs_top[j][class]`: heads-up equity against a uniformly random combo from the
  top X% of hands, X ∈ {3, 6, 10, 15, 20, 30, 40, 55, 75, 100}%, where "top"
  is ranked by the heads-up column. `equity_vs_top` interpolates.
- `hand_percentile(c1, c2)`: fraction of the 1,326 combos at least as strong
  heads-up (AA = 0.0045, worst = 1.0). This is the "top X%" scale the sparring
  bots use.

Runtime Monte Carlo (`equity_vs_random`, `equity_vs_ranges`) costs ~6 µs per
sample heads-up and ~19 µs per sample 8-way with this evaluator, so it is an
offline tool; inside the 1 ms deadline use the tables.

## Opponent statistics

`stats.OpponentTracker` keeps per-seat counts from the actions a bot can see:
VPIP, PFR, 3-bet (opportunities and count), fold-to-steal, c-bet and
fold-to-c-bet, postflop aggression. Rates are shrunk toward population priors
with 8 pseudo-observations so they are usable from hand one. Feed it with
`observe(obs)` on every decision (in play) or `ingest_record(hand_dict)`
(post-hoc, complete information). The in-play view is partial: nothing after
the bot's own fold is visible in the rehearsal protocol. Whether the official
interface exposes complete hand logs to the bot is unknown.

## Costs

8 workers on the M1 Pro: a 2,000-table eval ≈ 6–13 s; 10,000 tables ≈ 28 s;
with `--baseline` roughly double. The ladder with eight bots over 2,000
tables ≈ 5 s. Use `--workers 1` when you care about the `>1ms` count.
