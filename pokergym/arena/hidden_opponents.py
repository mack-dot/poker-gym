"""Withheld evaluation opponents.

Seven archetypes built from the sparring engine with profiles the
competitor never sees (the public sparring bots are tag/lag/shortstack/icm/
adaptive with their published knobs; these are different knob settings and
mixes). One of each sits at every hidden-evaluation table, so per-archetype
results are comparable. Not accessible from the competitor sandbox (this
module is inside the repository, which the sandbox denies).
"""
from __future__ import annotations

from ..bots.sparring import Profile, SparringBot

# Tight, rarely bluffs, overvalues made hands: punishes loose callers.
NIT = Profile(open_pct=(0.07, 0.10, 0.17, 0.20, 0.0), iso_pct=0.08, threebet_pct=0.03, call_open_pct=0.08,
              bb_defend_pct=0.20, cbet_freq=0.5, semi_bluff_freq=0.3, bluff_freq=0.05, call_margin=0.08,
              call_shove_margin=0.09, open_size_bb=3.0)
# Hyper-aggressive: wide opens, big sizes, lots of bluffs; punishes folders.
MANIAC = Profile(open_pct=(0.28, 0.36, 0.55, 0.55, 0.0), iso_pct=0.30, threebet_pct=0.13, call_open_pct=0.18,
                 bb_defend_pct=0.5, fourbet_pct=0.06, call_3bet_pct=0.12, reshove_pct=0.2, call_shove_margin=0.0,
                 cbet_freq=0.95, semi_bluff_freq=0.95, bluff_freq=0.5, bet_frac=0.9, slowplay_freq=0.0,
                 call_margin=-0.03, open_size_bb=3.5)
# Calling station: calls wide pre and post, rarely raises; punishes bluffers.
STATION = Profile(open_pct=(0.12, 0.18, 0.30, 0.30, 0.0), iso_pct=0.10, threebet_pct=0.02, call_open_pct=0.35,
                  bb_defend_pct=0.7, fourbet_pct=0.01, call_3bet_pct=0.25, cbet_freq=0.4, semi_bluff_freq=0.3,
                  bluff_freq=0.05, bet_frac=0.5, call_margin=-0.08, call_shove_margin=-0.02, slowplay_freq=0.3)
# Solid: tag with a touch more aggression and larger c-bets.
ROCK = Profile(open_pct=(0.10, 0.15, 0.26, 0.28, 0.0), threebet_pct=0.05, cbet_freq=0.75, bet_frac=0.7,
               bluff_freq=0.12, open_size_bb=2.8, call_margin=0.05)
# Trapper: slowplays monsters, check-raises, bluffs rarely.
TRAPPER = Profile(open_pct=(0.11, 0.16, 0.26, 0.30, 0.0), slowplay_freq=0.6, cbet_freq=0.45, bluff_freq=0.08,
                  semi_bluff_freq=0.4, bet_frac=0.8)


class Nit(SparringBot):
    name = "hidden-nit"
    profile = NIT


class Maniac(SparringBot):
    name = "hidden-maniac"
    profile = MANIAC


class Station(SparringBot):
    name = "hidden-station"
    profile = STATION


class Rock(SparringBot):
    name = "hidden-rock"
    profile = ROCK


class Trapper(SparringBot):
    name = "hidden-trapper"
    profile = TRAPPER


class Shark(SparringBot):
    """Adaptive + ICM-aware tag: the strongest archetype."""

    name = "hidden-shark"
    use_icm = True
    use_tracker = True


class Pusher(SparringBot):
    """Push/fold specialist that goes short early on purpose."""

    name = "hidden-pusher"
    pushfold_only_when_short = True
    profile = Profile(shove_bb=14.0, reshove_pct=0.12, open_pct=(0.09, 0.13, 0.22, 0.26, 0.0))


HIDDEN_LINEUP = [
    "pokergym.arena.hidden_opponents:Shark@shark",
    "pokergym.arena.hidden_opponents:Rock@rock",
    "pokergym.arena.hidden_opponents:Nit@nit",
    "pokergym.arena.hidden_opponents:Maniac@maniac",
    "pokergym.arena.hidden_opponents:Station@station",
    "pokergym.arena.hidden_opponents:Trapper@trapper",
    "pokergym.arena.hidden_opponents:Pusher@pusher",
]
